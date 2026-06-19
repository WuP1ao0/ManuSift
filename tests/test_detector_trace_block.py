"""Tests for the DetectorTraceBlock widget
(R-2026-06-13).

These tests focus on the *content* the widget renders (not its
visual layout -- that requires a running textual app, which
``textualize.App.run_test()`` provides but the unit-test
harness here keeps simpler by calling ``_summary_line`` /
``_expanded_block`` directly).

Covers:

  1. **Default state** (test_default_state_renders_placeholder):
     the widget renders a placeholder when no run is active.
  2. **Running -> Done transition** (test_done_event_updates_summary):
     a done event flips the summary's running count to done.
  3. **Skip reason** (test_skip_event_appears_in_expanded):
     a skip event appears in the expanded view with its reason.
  4. **Final summary** (test_final_summary_block_matches_spec):
     the collapsed summary matches the user's spec
     ``detectors 38/38 done · 5 findings · 7 skipped · 0 errors``.
  5. **Category grouping** (test_expanded_groups_by_category):
     detectors are grouped by category in the expanded view.
  6. **No raw JSON in main widget** (test_no_raw_finding_json_in_widget):
     the widget never includes raw finding JSON.
  7. **Listener ignores non-detector events**
     (test_listener_ignores_unrelated_events): the
     DetectorTraceBlockListener does not raise on
     non-detector events.
"""
from __future__ import annotations

from rich.text import Text

from manusift.detector_trace import (
    DETECTOR_DONE,
    DETECTOR_SKIPPED,
    DetectorTrace,
)
from manusift.events import Event
from manusift.tui.detector_block import (
    DetectorTraceBlock,
    DetectorTraceBlockListener,
)


def _text(t: Text) -> str:
    """Flatten a Rich ``Text`` to a plain string for substring
    checks. ``str(Text)`` does the right thing for our purposes
    (the colors are stripped)."""
    return t.plain


# ---------- 1. default state ----------

def test_default_state_renders_placeholder() -> None:
    """A fresh widget with no events shows a placeholder line."""
    block = DetectorTraceBlock()
    summary = block._summary_line()
    s = _text(summary)
    assert "detectors" in s
    # No run yet -- no "X/Y done" fraction.
    assert "0 findings" not in s
    assert "skipped" not in s
    assert "error" not in s


def test_default_state_render_method_does_not_crash_unmounted() -> None:
    """Calling _rerender on an unmounted widget must not raise
    (the widget guards the ``self.update`` call)."""
    block = DetectorTraceBlock()
    # No app -> not mounted. The _rerender call is a no-op in
    # that case (we still have the in-memory Text for testing).
    block._rerender()
    # Verify the summary is queryable regardless of mount state.
    assert block._summary_line() is not None


# ---------- 2. event-driven summary updates ----------

def test_done_event_updates_summary() -> None:
    """A done event flips the running count to done."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started",
        {"trace_id": "t1", "detector_count": 2},
    ))
    block.on_event_received(Event(
        "detector.started",
        {"trace_id": "t1", "detector": "metadata"},
    ))
    # After started: 1 running.
    s = _text(block._summary_line())
    assert "1 running" in s
    block.on_event_received(Event(
        "detector.done",
        {
            "trace_id": "t1", "detector": "metadata",
            "duration_ms": 10, "findings_count": 2,
        },
    ))
    # After done: 1 done, 0 running.
    s = _text(block._summary_line())
    assert "1/2 done" in s
    assert "running" not in s
    assert "2 findings" in s


def test_skip_event_appears_in_expanded() -> None:
    """A skip event appears in the expanded view with its reason."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started",
        {"trace_id": "t2", "detector_count": 1},
    ))
    block.on_event_received(Event(
        "detector.skipped",
        {
            "trace_id": "t2", "detector": "image_dup",
            "reason": "no raster images extracted from PDF",
        },
    ))
    # Collapsed summary line.
    s = _text(block._summary_line())
    assert "1 skipped" in s
    # Expanded view shows the per-detector row with reason.
    block.set_collapsed(False)
    expanded = _text(block._expanded_block())
    assert "image_dup" in expanded
    assert "no raster images" in expanded


def test_error_event_in_expanded() -> None:
    """An error event appears with the error message."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "t3", "detector_count": 1},
    ))
    block.on_event_received(Event(
        "detector.error",
        {
            "trace_id": "t3", "detector": "text_patterns",
            "error": "UnicodeDecodeError: bad byte", "duration_ms": 7,
        },
    ))
    s = _text(block._summary_line())
    assert "1 error" in s
    block.set_collapsed(False)
    expanded = _text(block._expanded_block())
    assert "text_patterns" in expanded
    assert "UnicodeDecodeError" in expanded


# ---------- 3. final summary matches spec ----------

def test_final_summary_block_matches_spec() -> None:
    """The collapsed summary matches the user's spec
    ``detectors 38/38 done · 5 findings · 7 skipped · 0 errors``.

    We simulate a 3-detector run (skipped + done + error) and
    assert the final summary line has the right shape.
    """
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "t4", "detector_count": 3},
    ))
    # Detector 1: done with 5 findings
    block.on_event_received(Event(
        "detector.started", {"trace_id": "t4", "detector": "a"},
    ))
    block.on_event_received(Event(
        "detector.done", {
            "trace_id": "t4", "detector": "a",
            "duration_ms": 10, "findings_count": 5,
        },
    ))
    # Detector 2: skipped
    block.on_event_received(Event(
        "detector.skipped", {
            "trace_id": "t4", "detector": "b",
            "reason": "no data",
        },
    ))
    # Detector 3: error
    block.on_event_received(Event(
        "detector.error", {
            "trace_id": "t4", "detector": "c",
            "error": "boom", "duration_ms": 1,
        },
    ))
    block.on_event_received(Event(
        "job.completed", {"trace_id": "t4"},
    ))
    s = _text(block._summary_line())
    assert "1/3 done" in s
    assert "5 findings" in s
    assert "1 skipped" in s
    assert "1 error" in s


# ---------- 4. category grouping ----------

def test_expanded_groups_by_category() -> None:
    """The expanded view groups detectors by category."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "g", "detector_count": 3},
    ))
    # metadata detector -> "PDF / metadata" category
    block.on_event_received(Event(
        "detector.done",
        {
            "trace_id": "g", "detector": "metadata",
            "duration_ms": 5, "findings_count": 0,
        },
    ))
    # image_dup -> "Image forensics"
    block.on_event_received(Event(
        "detector.done",
        {
            "trace_id": "g", "detector": "image_dup",
            "duration_ms": 5, "findings_count": 0,
        },
    ))
    # text_patterns -> "Text / references"
    block.on_event_received(Event(
        "detector.done",
        {
            "trace_id": "g", "detector": "text_patterns",
            "duration_ms": 5, "findings_count": 1,
        },
    ))
    block.set_collapsed(False)
    expanded = _text(block._expanded_block())
    # Group headers are present.
    assert "PDF / metadata" in expanded
    assert "Image forensics" in expanded
    assert "Text / references" in expanded


# ---------- 5. no raw JSON in widget ----------

def test_no_raw_finding_json_in_widget() -> None:
    """The widget never includes raw finding JSON in the chat
    log. We simulate a high-finding detector and assert no
    'raw' / 'evidence' / 'finding' JSON shape leaks through."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "r", "detector_count": 1},
    ))
    block.on_event_received(Event(
        "detector.done", {
            "trace_id": "r", "detector": "image_dup",
            "duration_ms": 10, "findings_count": 50,
        },
    ))
    # Collapsed
    s = _text(block._summary_line())
    # Should mention the count, but not the raw shape.
    assert "50 findings" in s
    assert "{" not in s
    assert "evidence" not in s
    # Expanded
    block.set_collapsed(False)
    expanded = _text(block._expanded_block())
    assert "{" not in expanded
    assert "\"detector\"" not in expanded


# ---------- 6. listener ignores unrelated events ----------

def test_listener_ignores_unrelated_events() -> None:
    """The DetectorTraceBlockListener does not raise on
    non-detector events."""
    block = DetectorTraceBlock()
    listener = DetectorTraceBlockListener(block)
    # Should be silent / no-op.
    listener.on_event(Event(
        "user.message", {"text": "hi"},
    ))
    listener.on_event(Event(
        "tool.call", {"name": "ingest_from_path"},
    ))
    # The widget trace should be untouched.
    assert block.trace.findings_total() == 0


# ---------- 7. widget re-renders are cheap ----------

def test_widget_handles_38_event_rapid_fire() -> None:
    """A 38-detector job (the full detector list) must not
    crash or hang the widget. Smoke test against 38 done
    events."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "f", "detector_count": 38},
    ))
    for i in range(38):
        block.on_event_received(Event(
            "detector.started",
            {"trace_id": "f", "detector": f"d{i}"},
        ))
    for i in range(38):
        block.on_event_received(Event(
            "detector.done",
            {
                "trace_id": "f", "detector": f"d{i}",
                "duration_ms": 1, "findings_count": 0,
            },
        ))
    s = _text(block._summary_line())
    assert "38/38 done" in s
    assert "running" not in s


# ---------- 8. job.started resets the trace ----------

def test_job_started_resets_trace() -> None:
    """A new ``job.started`` event resets the trace so the
    block does not mix two runs together."""
    block = DetectorTraceBlock()
    # Run 1
    block.on_event_received(Event(
        "job.started", {"trace_id": "a", "detector_count": 1},
    ))
    block.on_event_received(Event(
        "detector.done", {
            "trace_id": "a", "detector": "metadata",
            "duration_ms": 1, "findings_count": 5,
        },
    ))
    # Run 2
    block.on_event_received(Event(
        "job.started", {"trace_id": "b", "detector_count": 1},
    ))
    s = _text(block._summary_line())
    # The summary no longer references the previous run.
    assert "5 findings" not in s
    # The records are gone.
    assert len(block.trace.records) == 0
    # But the new header has the new trace id.
    assert block.trace.trace_id == "b"