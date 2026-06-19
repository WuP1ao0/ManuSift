"""R-2026-06-15 (Phase 3 + P3-3):
verify the
``subagent.progress`` event
emission.

The audit flagged that
the TUI had no live
indicator of a running
subagent -- the only
events were
``subagent.started`` (on
``__enter__``) and
``subagent.finished``
(on ``__exit__``), so for
the 10-120s the subagent
was running the TUI had
no updates.  The fix is
a periodic
``subagent.progress``
event (default every 2s)
with the current tool /
detector counters and
the last tool / detector
name.

These tests verify:

  1. The forwarder
     publishes a
     ``subagent.progress``
     event on a 2s tick.
  2. The progress event
     payload contains
     the current
     counters
     (tool_started,
     tool_finished,
     detector_done, ...).
  3. The progress event
     payload contains
     the
     ``subagent_id``
     and
     ``elapsed_seconds``.
  4. The progress event
     stops on
     ``__exit__``.
  5. The
     ``progress_interval_seconds``
     attribute is
     configurable per
     forwarder instance
     (e.g. test mode sets
     it to 0.05s for a
     fast tick).
"""
from __future__ import annotations

import time

import pytest

from manusift.events import (
    Event,
    Listener,
    get_bus,
    reset_bus,
)
from manusift.tools.subagent_forwarder import (
    _SubagentEventForwarder,
)


class _CountingListener(Listener):
    """A listener that
    counts every event by
    type.
    """

    def __init__(self) -> None:
        self.by_type: dict[str, list[Event]] = {}

    def on_event(self, event: Event) -> None:
        self.by_type.setdefault(
            event.type, []
        ).append(event)


def _fresh_bus() -> None:
    """Reset the bus so
    each test starts
    clean.
    """
    reset_bus()


def test_p33_progress_event_published_on_tick() -> None:
    """The forwarder
    publishes a
    ``subagent.progress``
    event on its
    2-second tick (or
    whatever
    ``progress_interval_seconds``
    is set to).
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "test-sub-1", "test-prompt"
    )
    # Use a 50ms tick so
    # the test is fast.
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.20)
    # The timer should
    # have fired at
    # least 2-3 times
    # in 200ms.
    progress_events = listener.by_type.get(
        "subagent.progress", []
    )
    assert len(progress_events) >= 2, (
        f"expected at least 2 "
        f"progress events in 200ms; "
        f"got {len(progress_events)}"
    )
    # The started event
    # is also emitted
    # once on
    # ``__enter__``.
    started_events = listener.by_type.get(
        "subagent.started", []
    )
    assert len(started_events) == 1


def test_p33_progress_payload_has_subagent_id() -> None:
    """The progress event
    payload contains the
    subagent_id (so the
    TUI can correlate
    it with the
    forwarder).
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "sub-id-p33", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.10)
    progress_events = listener.by_type.get(
        "subagent.progress", []
    )
    assert progress_events
    # All progress
    # events have the
    # subagent_id field.
    for ev in progress_events:
        assert ev.payload["subagent_id"] == "sub-id-p33"


def test_p33_progress_payload_has_elapsed_seconds() -> None:
    """The progress event
    payload contains
    ``elapsed_seconds``
    (monotonic time
    since the forwarder
    was entered).
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "sub-id-p33-2", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.15)
    progress_events = listener.by_type.get(
        "subagent.progress", []
    )
    assert progress_events
    last = progress_events[-1]
    assert "elapsed_seconds" in last.payload
    assert last.payload["elapsed_seconds"] >= 0
    assert (
        last.payload["elapsed_seconds"] < 5.0
    )  # the test is fast


def test_p33_progress_payload_has_counters() -> None:
    """The progress event
    payload contains the
    tool / detector
    counters (the TUI
    uses these to
    render a live
    progress bar).
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "sub-id-p33-3", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.10)
    progress_events = listener.by_type.get(
        "subagent.progress", []
    )
    assert progress_events
    p = progress_events[-1].payload
    for key in (
        "tool_started",
        "tool_finished",
        "detector_done",
        "detector_error",
        "detector_skipped",
        "last_tool_name",
        "last_detector_name",
    ):
        assert key in p, (
            f"progress payload missing {key!r}"
        )


def test_p33_progress_stops_on_exit() -> None:
    """The progress
    timer thread stops
    when the forwarder
    exits the ``with``
    block.
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "sub-id-p33-4", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.15)
    # ``__exit__`` is
    # now done; the
    # timer thread
    # should have
    # stopped.
    progress_count_at_exit = len(
        listener.by_type.get(
            "subagent.progress", []
        )
    )
    # Wait a bit and
    # confirm NO new
    # progress events
    # arrive.
    time.sleep(0.20)
    progress_count_after = len(
        listener.by_type.get(
            "subagent.progress", []
        )
    )
    assert progress_count_at_exit == progress_count_after, (
        f"progress events kept firing "
        f"after ``__exit__``: "
        f"{progress_count_at_exit} -> "
        f"{progress_count_after}"
    )


def test_p33_progress_thread_is_daemon() -> None:
    """The progress timer
    thread is a
    ``daemon`` thread
    so it does not
    block process exit
    if ``__exit__`` is
    never called (e.g.
    on a parent crash).
    """
    fwd = _SubagentEventForwarder(
        "sub-id-p33-5", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        th = fwd._progress_thread
        assert th is not None
        assert th.daemon is True


def test_p33_progress_interval_configurable() -> None:
    """The
    ``progress_interval_seconds``
    is configurable
    per instance.
    """
    fwd1 = _SubagentEventForwarder("a", "p")
    fwd1.progress_interval_seconds = 0.5
    fwd2 = _SubagentEventForwarder("b", "p")
    fwd2.progress_interval_seconds = 0.1
    assert (
        fwd1.progress_interval_seconds == 0.5
    )
    assert (
        fwd2.progress_interval_seconds == 0.1
    )


def test_p33_progress_event_is_tagged_with_subagent_id() -> None:
    """The progress event
    payload is
    ``subagent_id``-
    tagged so the TUI
    can route it to
    the right subagent
    row.
    """
    _fresh_bus()
    listener = _CountingListener()
    bus = get_bus()
    bus.subscribe(listener)
    fwd = _SubagentEventForwarder(
        "sub-id-p33-6", "p"
    )
    fwd.progress_interval_seconds = 0.05
    with fwd:
        time.sleep(0.10)
    # Find a progress
    # event.
    progress_events = listener.by_type.get(
        "subagent.progress", []
    )
    assert progress_events
    payload = progress_events[0].payload
    assert payload["subagent_id"] == "sub-id-p33-6"
