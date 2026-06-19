"""Detector-trace widget (R-2026-06-13).

The user reported that the TUI's chat log only showed a static
``[[ 38 detectors ]]`` line in the footer -- they had no visibility
into which detectors were running, which had finished, which had
been skipped, and which had errored. This module implements a
``DetectorTraceBlock`` widget that is the *single* place where
detector lifecycle information surfaces in the TUI.

## Three-layer structure (consistent with turn_block.py)

  1. **Chat** -- user input + assistant reply only. The detector
     block lives in layer 2.
  2. **DetectorTrace** -- a per-turn ``Collapsible``-style block
     (we use ``Static`` with a custom render so the layout stays
     tight). Default collapsed, showing only a one-line summary::

         detectors 12/38 done · 1 running · 0 findings · 4 skipped

     The user opens it (Enter or click) to see the per-detector
     list, grouped by category.
  3. **DebugDrawer** -- raw JSON for any power user who needs it.
     See turn_block.py for the DebugDrawer.

## Event integration

The block subscribes to the *global* ``EventBus`` (not the
per-run subscription the pipeline uses) so multiple jobs over the
session lifetime all feed the same widget instance -- a new
detector job clears the previous trace. The widget re-renders on
every event.

A ``DetectorTraceBlockListener`` is registered on the bus for
the lifetime of the chat app; it calls
``block.on_event_received(event)`` which delegates to a
``DetectorTrace``-shaped in-memory model.

The same listener also fires ``write_summary`` to disk on
``job.completed`` so the JSON artifact is up-to-date even if the
TUI is closed before the run finishes.

## Why a single widget (not N per-detector rows)

Per the user's "不刷屏" rule: the previous design mounted a row
per detector as it fired, which clobbered the chat log with 38+
rows. This widget subscribes to events and updates a single
visible block in place.

## Raw results do NOT appear in this block

Per the user's "detector 的 raw result 只进入 raw_trace.json / debug
drawer" rule: the block shows the per-detector status, duration,
finding count, and (when applicable) skip reason, but never the
raw finding list. The DebugDrawer holds the raw output.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual.widgets import Static

from ..detector_trace import (
    DETECTOR_DONE,
    DETECTOR_ERROR,
    DETECTOR_PROGRESS,
    DETECTOR_SKIPPED,
    DETECTOR_STARTED,
    ALL_DETECTOR_EVENTS,
    DetectorEntry,
    DetectorTrace,
    write_summary,
)
from ..events import Event, get_bus


# Status icon table -- matches turn_block.py's convention so the
# two blocks look consistent in the chat log.
_STATUS_ICON: dict[str, tuple[str, str]] = {
    DETECTOR_DONE: ("\u2713 ", "green"),       # check
    DETECTOR_SKIPPED: ("\u21b7 ", "yellow"),   # hook
    DETECTOR_ERROR: ("\u26a0 ", "red"),         # warning
    DETECTOR_STARTED: ("\u2807 ", "yellow"),   # braille dots
    DETECTOR_PROGRESS: ("\u2807 ", "yellow"),
}


# Display order for groups. Keeps the expanded view readable.
_CATEGORY_ORDER: tuple[str, ...] = (
    "PDF / metadata",
    "Image forensics",
    "Tables / statistics",
    "Text / references",
    "Reporting",
)


# --------------------- public event bridge ---------------------

class DetectorTraceBlockListener:
    """An EventBus listener that forwards detector events to a
    ``DetectorTraceBlock`` widget.

    The listener is intentionally separate from the widget so the
    widget can be unit-tested without an active EventBus, and the
    bus can be wired up by the chat app on startup.
    """

    name = "detector_trace_block"

    def __init__(self, block: "DetectorTraceBlock") -> None:
        self._block = block

    def on_event(self, event: Event) -> None:
        # Ignore non-detector events so we do not pay the cost
        # of attribute access on every event bus fire.
        if event.type not in ALL_DETECTOR_EVENTS:
            return
        # ``is_mounted`` is False during unit tests; skip the
        # widget re-render path in that case. The DetectorTrace
        # itself still records the event.
        self._block.on_event_received(event)


# --------------------- the widget itself ---------------------

@dataclass
class _RunHeader:
    """Header info for the current pipeline run, captured at
    ``job.started`` time."""
    trace_id: str = ""
    total: int = 0
    started_at: float = 0.0


class DetectorTraceBlock(Static):
    """A single widget showing all per-detector progress + status.

    Renders collapsed (one line) by default. When the user
    presses Enter / Space on it, the expanded view shows one row
    per detector, grouped by category.

    Re-renders on every event received from the listener. The
    re-render is cheap (we own the layout, no rich DOM diff).
    """

    DEFAULT_CSS: str = """
    DetectorTraceBlock {
        height: auto;
        padding: 0 1 0 3;
        margin: 0 0 1 0;
        background: #181825;
        color: #a6adc8;
    }
    .detector-trace-summary {
        color: #a6adc8;
    }
    .detector-trace-summary-running {
        color: #f9e2af;
        text-style: bold;
    }
    .detector-trace-entry {
        height: 1;
        color: #a6adc8;
    }
    .detector-trace-entry-icon-done {
        color: #a6e3a1;
    }
    .detector-trace-entry-icon-skipped {
        color: #f9e2af;
    }
    .detector-trace-entry-icon-error {
        color: #f38ba8;
    }
    .detector-trace-entry-icon-running {
        color: #f9e2af;
    }
    .detector-trace-category-header {
        color: #cdd6f4;
        text-style: bold;
    }
    """

    def __init__(
        self,
        *children: Any,
        collapsed: bool = True,
        classes: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*children, classes=classes or "detector-trace")
        self._collapsed: bool = collapsed
        # The trace object. We do NOT share it with the
        # pipeline's per-run trace (different scopes: the
        # pipeline's trace is written to JSON; this one drives
        # the widget UI). They both end up with the same data
        # because they both subscribe to the same events.
        self._trace = DetectorTrace(trace_id="", total=0)
        self._header = _RunHeader()
        self._rerender()

    # ----- public API -----

    def on_event_received(self, event: Event) -> None:
        """Forward a ``detector.*`` event to the trace, then
        re-render. Also handle the ``job.started`` event to
        reset the trace for a new run."""
        p = event.payload
        if event.type == "job.started":
            # Reset for a new run.
            self._header = _RunHeader(
                trace_id=p.get("trace_id", ""),
                total=int(p.get("detector_count", 0) or 0),
                started_at=time.time(),
            )
            self._trace = DetectorTrace(
                trace_id=self._header.trace_id,
                total=self._header.total,
            )
            self._rerender()
            return
        if event.type == "job.completed":
            # The pipeline will write its own detector_summary.json.
            # We do not need to write again here. Just re-render
            # so the final state shows up.
            self._rerender()
            return
        # detector.* events
        detector = p.get("detector", "?")
        if event.type == DETECTOR_STARTED:
            self._trace.record_started(detector, p.get("phase", ""))
        elif event.type == DETECTOR_PROGRESS:
            self._trace.record_progress(detector, p.get("phase", ""))
        elif event.type == DETECTOR_DONE:
            self._trace.record_done(
                detector,
                int(p.get("duration_ms", 0) or 0),
                int(p.get("findings_count", 0) or 0),
            )
        elif event.type == DETECTOR_SKIPPED:
            self._trace.record_skipped(detector, p.get("reason", ""))
        elif event.type == DETECTOR_ERROR:
            self._trace.record_error(
                detector,
                p.get("error", ""),
                int(p.get("duration_ms", 0) or 0),
            )
        self._rerender()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._rerender()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    @property
    def trace(self) -> DetectorTrace:
        return self._trace

    # ----- internal -----

    def _rerender(self) -> None:
        if self._collapsed:
            text = self._summary_line()
        else:
            text = self._expanded_block()
        if not self.is_mounted:
            return
        self.update(text)

    def _summary_line(self) -> Text:
        # If the run has not started yet, show a placeholder.
        if not self._header.trace_id and not self._trace.records:
            t = Text("  ◌ detectors", style="dim")
            t.stylize("yellow")
            return t
        c = self._trace.counts()
        n_done = c.get(DETECTOR_DONE, 0)
        n_skipped = c.get(DETECTOR_SKIPPED, 0)
        n_error = c.get(DETECTOR_ERROR, 0)
        n_running = c.get(DETECTOR_STARTED, 0) + c.get(
            DETECTOR_PROGRESS, 0
        )
        findings = self._trace.findings_total()
        total = self._header.total
        out = Text()
        # Summary prefix: "detectors 12/38 done".
        if total:
            out.append(
                f"  ◌ detectors {n_done}/{total} done",
                style="dim",
            )
        else:
            out.append(f"  ◌ detectors {n_done} done", style="dim")
        if n_running:
            out.append(
                f" · {n_running} running", style="yellow bold"
            )
        if findings:
            out.append(f" · {findings} findings", style="green")
        if n_skipped:
            out.append(f" · {n_skipped} skipped", style="yellow")
        if n_error:
            out.append(f" · {n_error} error", style="red")
        # If the run is still in progress, add a "running…" hint.
        if n_running and not c.get(DETECTOR_DONE, 0) == total:
            out.append(" · running…", style="yellow")
        return out

    def _expanded_block(self) -> Text:
        out = Text()
        out.append_text(self._summary_line())
        out.append("\n")
        # Group detectors by category.
        by_cat: dict[str, list[DetectorEntry]] = {}
        for r in self._trace.records:
            by_cat.setdefault(r.category, []).append(r)
        for cat in _CATEGORY_ORDER:
            entries = by_cat.get(cat, [])
            if not entries:
                continue
            out.append(f"\n  {cat}\n", style="bold")
            for e in entries:
                out.append_text(self._format_entry(e))
                out.append("\n")
        # Any ungrouped detectors (unknown category) at the end.
        for cat, entries in by_cat.items():
            if cat in _CATEGORY_ORDER:
                continue
            out.append(f"\n  {cat}\n", style="bold")
            for e in entries:
                out.append_text(self._format_entry(e))
                out.append("\n")
        return out

    def _format_entry(self, e: DetectorEntry) -> Text:
        icon, color = _STATUS_ICON.get(e.status, ("\u2022 ", "dim"))
        # Build the line. Format mirrors the user's spec:
        #   "✓ image_dup 310ms no high-risk duplicate"
        #   "⠋ image_forensics running scanning figure panels"
        #   "↷ stat_grim skipped: no eligible integer table"
        #   "! stat_pvalue error: missing p-value column"
        out = Text("    ")
        out.append(icon, style=color)
        out.append(e.detector, style="bold " + color)
        if e.status == DETECTOR_STARTED or e.status == DETECTOR_PROGRESS:
            if e.phase:
                out.append(f"  {e.phase}", style="yellow")
            else:
                out.append("  running", style="yellow")
        elif e.status == DETECTOR_SKIPPED:
            reason = e.skip_reason or "no reason given"
            out.append(f"  skipped: {reason}", style="yellow")
        elif e.status == DETECTOR_ERROR:
            err = e.error or "unknown error"
            out.append(f"  error: {err}", style="red")
        else:
            # done
            if e.duration_ms is not None:
                out.append(f"  {e.duration_ms}ms", style="dim")
            if e.finding_count:
                out.append(
                    f"  {e.finding_count} finding"
                    f"{'s' if e.finding_count != 1 else ''}",
                    style="green",
                )
            else:
                out.append("  no findings", style="dim")
        return out


# --------------------- bus subscription helper ---------------------

def install_default_listener(
    block: DetectorTraceBlock,
) -> DetectorTraceBlockListener:
    """Subscribe a ``DetectorTraceBlockListener`` to the global
    bus and return the handle. The chat app calls this once on
    startup; the listener lives for the life of the app.
    """
    listener = DetectorTraceBlockListener(block)
    get_bus().subscribe(listener)
    return listener