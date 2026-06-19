"""Tests for the R-2026-06-14 TUI live-elapsed
tracker + ToolTraceBlock detail rendering.

Covers:

  * ``LiveElapsedTracker`` subscribes
    to the bus and updates its snapshot
    on ``task.started`` /
    ``task.heartbeat`` /
    ``task.finished`` events.
  * ``LiveElapsedSnapshot.is_running``
    is True only when a tool is in
    flight (``ok`` is None).
  * ``render_short()`` produces a
    one-line status-bar string.
  * ``format_entry_detail`` consumes
    the new ``ToolEntry`` fields
    (cwd, stderr, shell_mode,
    returncode) and renders them
    only when non-empty.
"""
from __future__ import annotations

import time

import pytest

from manusift.events import (
    Event,
    EventBus,
    reset_bus,
)
from manusift.tui.live_elapsed import (
    LiveElapsedSnapshot,
    LiveElapsedTracker,
    get_live_elapsed,
    reset_live_elapsed,
)
from manusift.tui.turn_block import (
    TOOL_ERROR,
    TOOL_OK,
    TOOL_SKIPPED,
    ToolEntry,
    format_entry_detail,
)


# --------------------------------------------------------------------
# LiveElapsedSnapshot
# --------------------------------------------------------------------


def test_snapshot_initial_state():
    s = LiveElapsedSnapshot()
    assert s.running is None
    assert s.is_running is False
    assert s.render_short() == ""


def test_snapshot_running():
    s = LiveElapsedSnapshot(
        running="image_dup",
        elapsed_seconds=12.3,
        last_extra={"chunks_done": 5},
    )
    assert s.is_running
    text = s.render_short()
    assert "image_dup" in text
    assert "12.3s" in text
    assert "chunks_done=5" in text


def test_snapshot_running_without_extras():
    s = LiveElapsedSnapshot(
        running="image_dup",
        elapsed_seconds=5.0,
    )
    text = s.render_short()
    assert "image_dup" in text
    assert "5.0s" in text
    # No extras section.
    assert "chunks_done" not in text


def test_snapshot_finished_marks_not_running():
    s = LiveElapsedSnapshot(
        running="image_dup",
        elapsed_seconds=42.0,
        ok=True,
    )
    assert not s.is_running
    assert s.render_short() == ""


def test_snapshot_finished_error():
    s = LiveElapsedSnapshot(
        running="image_dup",
        elapsed_seconds=0.5,
        ok=False,
    )
    assert not s.is_running


# --------------------------------------------------------------------
# LiveElapsedTracker
# --------------------------------------------------------------------


def test_tracker_singleton_lifecycle():
    """``get_live_elapsed`` returns a
    single instance per process and
    ``reset_live_elapsed`` drops it.
    """
    reset_live_elapsed()
    a = get_live_elapsed()
    b = get_live_elapsed()
    assert a is b
    reset_live_elapsed()
    c = get_live_elapsed()
    assert c is not a


def test_tracker_updates_on_started():
    reset_live_elapsed()
    bus = EventBus()
    tracker = LiveElapsedTracker(bus)
    bus.emit(Event(
        "task.started",
        {
            "tool": "image_dup",
            "seq_id": 1,
        },
    ))
    snap = tracker.state
    assert snap.running == "image_dup"
    assert snap.is_running
    tracker.unsubscribe()


def test_tracker_updates_on_heartbeat():
    reset_live_elapsed()
    bus = EventBus()
    tracker = LiveElapsedTracker(bus)
    bus.emit(Event(
        "task.started",
        {"tool": "image_dup"},
    ))
    bus.emit(Event(
        "task.heartbeat",
        {
            "tool": "image_dup",
            "elapsed_seconds": 5.5,
            "ticked": 3,
            "last_extra": {"chunks_done": 2},
        },
    ))
    snap = tracker.state
    assert snap.running == "image_dup"
    assert snap.elapsed_seconds == 5.5
    assert snap.ticked == 3
    assert snap.last_extra == {"chunks_done": 2}
    tracker.unsubscribe()


def test_tracker_marks_finished():
    reset_live_elapsed()
    bus = EventBus()
    tracker = LiveElapsedTracker(bus)
    bus.emit(Event(
        "task.started",
        {"tool": "image_dup"},
    ))
    bus.emit(Event(
        "task.heartbeat",
        {
            "tool": "image_dup",
            "elapsed_seconds": 3.0,
        },
    ))
    bus.emit(Event(
        "task.finished",
        {
            "tool": "image_dup",
            "elapsed_seconds": 5.0,
            "ok": True,
        },
    ))
    snap = tracker.state
    assert not snap.is_running
    assert snap.ok is True
    assert snap.elapsed_seconds == 5.0
    tracker.unsubscribe()


def test_tracker_records_failed_run():
    """A ``task.finished`` with
    ``ok=False`` still marks the
    run as finished (the user
    needs to see the failure
    in the status bar).
    """
    reset_live_elapsed()
    bus = EventBus()
    tracker = LiveElapsedTracker(bus)
    bus.emit(Event(
        "task.started", {"tool": "x"}
    ))
    bus.emit(Event(
        "task.finished",
        {"tool": "x", "elapsed_seconds": 1.0, "ok": False},
    ))
    snap = tracker.state
    assert not snap.is_running
    assert snap.ok is False
    tracker.unsubscribe()


# --------------------------------------------------------------------
# format_entry_detail
# --------------------------------------------------------------------


def test_format_entry_detail_minimal():
    e = ToolEntry(tool_id="i", tool_name="bash")
    text = format_entry_detail(e)
    assert "bash" in text
    assert "[TOOL_OK]" in text or "[ok]" in text
    # No bash-specific fields yet.
    assert "shell_mode" not in text
    assert "cwd" not in text


def test_format_entry_detail_with_all_fields():
    e = ToolEntry(
        tool_id="i",
        tool_name="bash",
        status=TOOL_OK,
        duration_ms=42,
        summary="ran ok",
        cwd="C:/Users/me",
        stderr="some warning",
        shell_mode="cmd",
        returncode=0,
    )
    text = format_entry_detail(e)
    assert "bash" in text
    assert "42ms" in text
    assert "ran ok" in text
    assert "shell_mode: cmd" in text
    assert "cwd: C:/Users/me" in text
    assert "stderr: some warning" in text
    assert "returncode: 0" in text


def test_format_entry_detail_omits_empty_fields():
    """The function does not print
    ``shell_mode: `` with an empty
    value -- the BashTool envelope
    always sets it, so an empty
    string here is a "this was not
    a bash call" signal.
    """
    e = ToolEntry(
        tool_id="i",
        tool_name="image_dup",
        status=TOOL_OK,
    )
    text = format_entry_detail(e)
    assert "shell_mode:" not in text
    assert "cwd:" not in text
    assert "returncode:" not in text


def test_format_entry_detail_error_status():
    e = ToolEntry(
        tool_id="i",
        tool_name="bash",
        status=TOOL_ERROR,
        error="permission denied: rm -rf /",
        duration_ms=5,
    )
    text = format_entry_detail(e)
    assert "bash" in text
    assert "permission denied" in text


def test_format_entry_detail_stderr_truncated():
    e = ToolEntry(
        tool_id="i",
        tool_name="bash",
        stderr="x" * 5000,
    )
    text = format_entry_detail(e)
    # The truncation appends "..."
    assert "..." in text
    # And the line is much shorter than
    # the original 5000-char string.
    assert len(text) < 2000


def test_format_entry_detail_skipped_status():
    e = ToolEntry(
        tool_id="i",
        tool_name="image_dup",
        status=TOOL_SKIPPED,
    )
    text = format_entry_detail(e)
    # The status string appears in the
    # first line.
    assert "image_dup" in text
    assert "TOOL_SKIPPED" in text or "skipped" in text.lower()
