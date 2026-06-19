"""Live-elapsed tracker for the TUI status bar
(R-2026-06-14, issue 11 follow-up).

Subscribes to the EventBus and tracks the
latest ``task.heartbeat`` / ``task.started`` /
``task.finished`` events so a status-bar
widget can render a one-line
``running image_dup · 45.2s · 156 panels``
without re-implementing the heartbeat
thread.

Contract:

  * The tracker exposes ``state`` (a
    ``LiveElapsedSnapshot`` dataclass)
    that the status-bar render path
    reads.
  * ``state.running`` is the name of
    the current long-running tool,
    or ``None`` when no tool is
    running.
  * ``state.elapsed_seconds`` is the
    last-reported elapsed time.
  * ``state.last_extra`` is the
    ``hb.tick(extra=...)`` payload
    (e.g. ``{"chunks_done": 5}``).
  * The tracker is auto-instantiated
    per process; tests use
    ``reset_live_elapsed()`` to drop
    the singleton.

Pattern follows claw-code's
``HookProgressTracker`` in
``rust/crates/runtime/src/hooks.rs``.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..events import Event, EventBus, get_bus


@dataclass
class LiveElapsedSnapshot:
    """The latest live-elapsed state
    from the EventBus.
    """
    running: str | None = None
    elapsed_seconds: float = 0.0
    last_extra: dict[str, Any] = field(
        default_factory=dict
    )
    started_at: float | None = None
    ticked: int = 0
    # ``ok`` is the result of the most
    # recent ``task.finished`` event
    # for the current run. ``None``
    # while a tool is still running.
    ok: bool | None = None

    @property
    def is_running(self) -> bool:
        return self.running is not None and self.ok is None

    def render_short(self) -> str:
        """One-line rendering for a
        status bar.
        """
        if not self.is_running:
            return ""
        extras = ""
        if self.last_extra:
            extras = (
                " · "
                + ", ".join(
                    f"{k}={v}"
                    for k, v in self.last_extra.items()
                )
            )
        return (
            f"running {self.running} · "
            f"{self.elapsed_seconds:.1f}s"
            f"{extras}"
        )


class LiveElapsedTracker:
    """A small listener that subscribes
    to the bus and keeps a
    ``LiveElapsedSnapshot`` up to
    date.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or get_bus()
        self._lock = threading.Lock()
        self._state = LiveElapsedSnapshot()
        self._listener = self._make_listener()
        self._bus.subscribe(self._listener)

    def _make_listener(self) -> Any:
        outer = self

        class _L:
            name = "live-elapsed-tracker"

            def on_event(self, event: Event) -> None:
                outer._on_event(event)

        return _L()

    def _on_event(self, event: Event) -> None:
        if event.type == "task.started":
            with self._lock:
                self._state = LiveElapsedSnapshot(
                    running=event.payload.get("tool"),
                    elapsed_seconds=0.0,
                    started_at=event.ts,
                    ok=None,
                )
        elif event.type == "task.heartbeat":
            with self._lock:
                self._state.running = event.payload.get(
                    "tool"
                )
                self._state.elapsed_seconds = float(
                    event.payload.get("elapsed_seconds", 0.0)
                )
                self._state.last_extra = dict(
                    event.payload.get("last_extra") or {}
                )
                self._state.ticked = int(
                    event.payload.get("ticked", 0)
                )
        elif event.type == "task.finished":
            with self._lock:
                self._state.running = event.payload.get(
                    "tool"
                )
                self._state.elapsed_seconds = float(
                    event.payload.get("elapsed_seconds", 0.0)
                )
                self._state.last_extra = dict(
                    event.payload.get("last_extra") or {}
                )
                self._state.ticked = int(
                    event.payload.get("ticked", 0)
                )
                self._state.ok = bool(
                    event.payload.get("ok", True)
                )

    @property
    def state(self) -> LiveElapsedSnapshot:
        with self._lock:
            # Return a copy so the
            # caller cannot mutate the
            # internal state.
            return LiveElapsedSnapshot(
                running=self._state.running,
                elapsed_seconds=self._state.elapsed_seconds,
                last_extra=dict(self._state.last_extra),
                started_at=self._state.started_at,
                ticked=self._state.ticked,
                ok=self._state.ok,
            )

    def unsubscribe(self) -> None:
        self._bus.unsubscribe(self._listener)


_LOCK = threading.Lock()
_TRACKER: LiveElapsedTracker | None = None


def get_live_elapsed() -> LiveElapsedTracker:
    """Return the process-global
    ``LiveElapsedTracker``. Created
    on first call. Tests use
    ``reset_live_elapsed()`` to
    drop the singleton.
    """
    global _TRACKER
    with _LOCK:
        if _TRACKER is None:
            _TRACKER = LiveElapsedTracker()
        return _TRACKER


def reset_live_elapsed() -> None:
    """Test hook. Drop the singleton.
    Production code should not
    call this.
    """
    global _TRACKER
    with _LOCK:
        if _TRACKER is not None:
            _TRACKER.unsubscribe()
        _TRACKER = None
