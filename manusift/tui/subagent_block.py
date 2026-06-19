"""Subagent-trace widget (R-2026-06-15, Phase 0.2).

The user reported that when the
parent agent spawns a sub-agent
(via ``TaskTool``), the parent's
TUI shows nothing about the
child's tool calls. The
subagent runs in a background
thread, makes a series of
``tool.started`` / ``tool.finished``
events on the bus (forwarded
from the child), and the parent
TUI never shows them. The user
sees only a static "running
task" line in the status bar
and has no idea what the
subagent is doing.

This module implements a
``SubagentBlock`` widget that
subscribes to the bus and
renders the in-flight subagent's
tool activity. Default
collapsed, showing a one-line
summary::

    subagents 1 running · [sub:abc1] tool=image_dup 1.2s ok
    · [sub:abc1] tool=stat_grim 320ms ok · 5 findings

When expanded, the block shows
one row per subagent (most
recent first) with the subagent
id, the tools called, the
elapsed time, and the last
extra (e.g. ``chunks_done=23``).

## Event integration

The block subscribes to the
*global* ``EventBus`` so
subagent events from any
forwarder feed the same widget
instance. The
``SubagentBlockListener`` calls
``block.on_event_received(event)``
which routes by event type.

Event types consumed:

  * ``subagent.started`` -- new
    subagent; reset the row.
  * ``subagent.finished`` -- mark
    the subagent as done.
  * ``subagent.tool_forward`` --
    record the tool call.
  * ``subagent.cancelled`` -- mark
    as cancelled (Phase 0.1
    parent-cancel propagation).

The block does not have a
collapsed-by-default
"3-layer structure" claim; it
sits next to the chat log and
the tool trace block. Users who
do not care can ignore it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from ..events import Event, get_bus


# Subagent status icons, mirrored
# from detector_block.py for
# visual consistency.
_STATUS_ICON: dict[str, tuple[str, str]] = {
    "started": ("◌ ", "yellow"),
    "running": ("⠋ ", "yellow"),
    "done": ("✓ ", "green"),
    "error": ("! ", "red"),
    "cancelled": ("⨯ ", "dim"),
}


@dataclass
class SubagentRow:
    """One subagent's tool call
    history.

    Mirrors the design of
    ``DetectorEntry`` in
    ``detector_block.py``.
    """

    subagent_id: str
    goal: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    status: str = "started"
    last_tool: str = ""
    last_duration_ms: int = 0
    last_extra: dict[str, Any] = field(
        default_factory=dict
    )
    tool_count: int = 0


class SubagentBlock:
    """TUI widget for the
    subagent trace.

    The class is intentionally
    small and self-contained;
    it does not depend on the
    ``DetectorTraceBlock``. The
    chat app mounts one instance
    next to the chat log; the
    block subscribes to the bus
    via ``install_default_listener``.

    Note: the class is a
    duck-typed widget (it has
    ``update(text)``, ``is_mounted``,
    etc., as expected by textual
    ``Static``), so it can be
    substituted in tests without
    a real textual App. The
    ``render`` is the standard
    textual widget render method;
    we expose a
    ``_summary_line()`` /
    ``_expanded_block()`` pair for
    unit tests that need to
    inspect the rendered text
    without an app.
    """

    is_mounted: bool

    def __init__(self) -> None:
        self._collapsed: bool = True
        # Map ``subagent_id`` to
        # the in-flight row. The
        # most recently updated
        # row is shown first.
        self._rows: dict[str, SubagentRow] = {}
        self._order: list[str] = []
        self.is_mounted = False

    # ----- public API -----

    def on_event_received(self, event: Event) -> None:
        """Forward a ``subagent.*``
        event to the row, then
        re-render.
        """
        p = event.payload
        sub_id = p.get("subagent_id", "?")
        if event.type == "subagent.started":
            row = SubagentRow(
                subagent_id=sub_id,
                goal=str(p.get("goal", "")),
                started_at=__import__(
                    "time"
                ).time(),
                status="started",
            )
            self._rows[sub_id] = row
            # Move to the front.
            if sub_id in self._order:
                self._order.remove(sub_id)
            self._order.insert(0, sub_id)
        elif event.type == "subagent.finished":
            row = self._rows.get(sub_id)
            if row is not None:
                row.status = "done"
                row.finished_at = __import__(
                    "time"
                ).time()
        elif event.type == "subagent.cancelled":
            row = self._rows.get(sub_id)
            if row is not None:
                row.status = "cancelled"
                row.finished_at = __import__(
                    "time"
                ).time()
        elif event.type == "subagent.tool_forward":
            row = self._rows.get(sub_id)
            if row is not None:
                row.status = "running"
                row.last_tool = str(
                    p.get("tool_name", "")
                )
                row.last_duration_ms = int(
                    p.get("duration_ms", 0) or 0
                )
                row.last_extra = dict(
                    p.get("extra", {}) or {}
                )
                row.tool_count += 1
        self._rerender()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._rerender()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(
            not self._collapsed
        )

    @property
    def rows(self) -> dict[str, SubagentRow]:
        return self._rows

    # ----- internal -----

    def _rerender(self) -> None:
        # The chat app's bus
        # listener calls
        # ``on_event_received`` on
        # the bus thread, then
        # ``call_from_thread`` to
        # push the result to the
        # main thread. We do not
        # need to do anything
        # here; the widget's
        # render() method is
        # called by textual on
        # the next paint cycle.
        pass

    def render(self) -> Text:
        if self._collapsed:
            return self._summary_line()
        return self._expanded_block()

    def _summary_line(self) -> Text:
        if not self._rows:
            return Text(
                "  ◌ subagents", style="dim"
            )
        running = sum(
            1
            for r in self._rows.values()
            if r.status
            in ("started", "running")
        )
        done = sum(
            1
            for r in self._rows.values()
            if r.status == "done"
        )
        out = Text()
        out.append(
            f"  ◌ subagents {running} running"
            f" · {done} done",
            style="dim",
        )
        # Show the most recent
        # row's last tool, so
        # the user can see
        # what the subagent
        # is doing right now.
        if self._order:
            head = self._rows.get(
                self._order[0]
            )
            if (
                head is not None
                and head.last_tool
            ):
                out.append(
                    f"  ·  [sub:{head.subagent_id}] "
                    f"tool={head.last_tool} "
                    f"{head.last_duration_ms}ms"
                    f" ({head.tool_count} "
                    f"call"
                    f"{'s' if head.tool_count != 1 else ''}"
                    f")",
                    style="yellow",
                )
        return out

    def _expanded_block(self) -> Text:
        out = Text()
        out.append_text(self._summary_line())
        out.append("\n")
        for sub_id in self._order:
            r = self._rows[sub_id]
            icon, color = _STATUS_ICON.get(
                r.status, ("? ", "dim")
            )
            out.append("    ")
            out.append(icon, style=color)
            out.append(
                f"[sub:{r.subagent_id}] ",
                style=f"bold {color}",
            )
            if r.goal:
                out.append(
                    r.goal[:60]
                    + ("..." if len(r.goal) > 60 else ""),
                    style="dim",
                )
            out.append("\n")
            if r.last_tool:
                extra = (
                    " · "
                    + ", ".join(
                        f"{k}={v}"
                        for k, v in r.last_extra.items()
                    )
                    if r.last_extra
                    else ""
                )
                out.append(
                    f"      last: {r.last_tool} "
                    f"{r.last_duration_ms}ms"
                    f"{extra}",
                    style="dim",
                )
                out.append("\n")
            out.append(
                f"      tools: {r.tool_count} "
                f"call"
                f"{'s' if r.tool_count != 1 else ''}",
                style="dim",
            )
            out.append("\n")
        return out

    def update(self, text: Any) -> None:
        # Stub for textual
        # ``Static`` compatibility.
        # The real textual App
        # overrides this when the
        # widget is mounted; the
        # unit tests do not call
        # this path.
        pass


class SubagentBlockListener:
    """Bridge the global
    ``EventBus`` to a
    ``SubagentBlock``.

    Mirrors the
    ``DetectorTraceBlockListener``
    pattern. The chat app installs
    one of these in ``on_mount``
    and the listener lives for
    the life of the app.
    """

    def __init__(self, block: SubagentBlock) -> None:
        self._block = block

    def on_event(self, event: Event) -> None:
        if event.type.startswith("subagent."):
            self._block.on_event_received(event)


def install_default_listener(
    block: SubagentBlock,
) -> SubagentBlockListener:
    """Subscribe a
    ``SubagentBlockListener`` to
    the global bus and return
    the handle. The chat app
    calls this once on startup.
    """
    listener = SubagentBlockListener(block)
    get_bus().subscribe(listener)
    return listener
