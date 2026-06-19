"""Tests for the R-2026-06-15 (Phase 0.2)
subagent-trace TUI widget.

The contract:

  * ``SubagentBlock`` consumes
    ``subagent.started`` /
    ``subagent.finished`` /
    ``subagent.tool_forward`` /
    ``subagent.cancelled`` events
    from the bus.
  * A subagent row tracks:
    - goal (string),
    - last_tool (string),
    - last_duration_ms (int),
    - last_extra (dict),
    - tool_count (int),
    - status (started / running /
      done / cancelled).
  * The summary line shows the
    most recently updated row's
    last tool call.
  * The expanded block shows one
    row per subagent (most
    recent first).
  * ``SubagentBlockListener`` is
    a thin bridge from the bus
    to the block.

Pattern follows the agent-infra-
iteration-engineer skill rule
I.4: every block has a pure
helper that tests can pin
without spinning up a textual
App.
"""
from __future__ import annotations

import time

import pytest

from manusift.events import Event, get_bus, reset_bus
from manusift.tui.subagent_block import (
    SubagentBlock,
    SubagentBlockListener,
    install_default_listener,
)


@pytest.fixture
def fresh_bus():
    """Reset the bus before each
    test so listeners from a
    previous test do not leak
    in.
    """
    reset_bus()
    yield
    reset_bus()


# --------------------------------------------------------------------
# SubagentBlock lifecycle
# --------------------------------------------------------------------


def test_empty_block_summary_is_subagents_dim():
    """A fresh block renders
    ``◌ subagents`` in dim
    style.
    """
    block = SubagentBlock()
    text = block._summary_line()
    assert "subagents" in text.plain
    assert "running" not in text.plain


def test_subagent_started_adds_a_row():
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {
                "subagent_id": "sub:abc1",
                "goal": "screen Figure 5B",
            },
        )
    )
    assert "sub:abc1" in block.rows
    row = block.rows["sub:abc1"]
    assert row.goal == "screen Figure 5B"
    assert row.status == "started"
    assert row.tool_count == 0


def test_subagent_tool_forward_updates_last_tool():
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {
                "subagent_id": "sub:abc1",
                "goal": "screen",
            },
        )
    )
    block.on_event_received(
        Event(
            "subagent.tool_forward",
            {
                "subagent_id": "sub:abc1",
                "tool_name": "image_dup",
                "duration_ms": 1200,
                "extra": {
                    "panels": 156,
                },
            },
        )
    )
    row = block.rows["sub:abc1"]
    assert row.last_tool == "image_dup"
    assert row.last_duration_ms == 1200
    assert row.last_extra == {
        "panels": 156,
    }
    assert row.tool_count == 1
    assert row.status == "running"


def test_subagent_finished_marks_done():
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:abc1", "goal": "x"},
        )
    )
    block.on_event_received(
        Event(
            "subagent.finished",
            {
                "subagent_id": "sub:abc1",
                "duration_ms": 5000,
            },
        )
    )
    assert block.rows["sub:abc1"].status == "done"


def test_subagent_cancelled_marks_cancelled():
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:abc1", "goal": "x"},
        )
    )
    block.on_event_received(
        Event(
            "subagent.cancelled",
            {
                "subagent_id": "sub:abc1",
                "reason": "parent /stop",
            },
        )
    )
    assert (
        block.rows["sub:abc1"].status
        == "cancelled"
    )


# --------------------------------------------------------------------
# Summary line + expanded block
# --------------------------------------------------------------------


def test_summary_shows_most_recent_row_tool():
    """The summary line surfaces
    the most recent subagent's
    last tool call.
    """
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:abc1", "goal": "x"},
        )
    )
    block.on_event_received(
        Event(
            "subagent.tool_forward",
            {
                "subagent_id": "sub:abc1",
                "tool_name": "stat_grim",
                "duration_ms": 320,
            },
        )
    )
    text = block._summary_line()
    plain = text.plain
    assert "stat_grim" in plain
    assert "320ms" in plain
    assert "sub:abc1" in plain


def test_summary_counts_running_and_done():
    block = SubagentBlock()
    # Two started, one finished.
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:a", "goal": "x"},
        )
    )
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:b", "goal": "y"},
        )
    )
    block.on_event_received(
        Event(
            "subagent.finished",
            {"subagent_id": "sub:a"},
        )
    )
    text = block._summary_line()
    plain = text.plain
    assert "1 running" in plain
    assert "1 done" in plain


def test_expanded_block_shows_one_row_per_subagent():
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {
                "subagent_id": "sub:a",
                "goal": "first",
            },
        )
    )
    block.on_event_received(
        Event(
            "subagent.started",
            {
                "subagent_id": "sub:b",
                "goal": "second",
            },
        )
    )
    text = block._expanded_block()
    plain = text.plain
    # Both subagent ids are
    # rendered.
    assert "sub:a" in plain
    assert "sub:b" in plain
    # Both goals are rendered
    # (truncated to 60 chars
    # if longer).
    assert "first" in plain
    assert "second" in plain


def test_expanded_block_shows_most_recent_first():
    """The order list is updated
    on every event so the most
    recently updated row is at
    the top of the expanded
    view.
    """
    block = SubagentBlock()
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:a", "goal": "x"},
        )
    )
    time.sleep(0.01)
    block.on_event_received(
        Event(
            "subagent.started",
            {"subagent_id": "sub:b", "goal": "y"},
        )
    )
    assert block._order[0] == "sub:b"
    assert block._order[1] == "sub:a"


# --------------------------------------------------------------------
# Bus listener bridge
# --------------------------------------------------------------------


def test_listener_ignores_non_subagent_events():
    """The listener only routes
    ``subagent.*`` events; any
    other event type is a no-op.
    """
    block = SubagentBlock()
    listener = SubagentBlockListener(block)
    listener.on_event(
        Event("tool.started", {"tool": "x"})
    )
    listener.on_event(
        Event("detector.done", {"detector": "x"})
    )
    assert block.rows == {}


def test_listener_routes_subagent_started():
    block = SubagentBlock()
    listener = SubagentBlockListener(block)
    listener.on_event(
        Event(
            "subagent.started",
            {"subagent_id": "sub:x", "goal": "x"},
        )
    )
    assert "sub:x" in block.rows


def test_install_default_listener_subscribes_to_bus(
    fresh_bus,
):
    """``install_default_listener``
    adds a listener to the
    global bus so any future
    ``subagent.*`` event
    reaches the block.
    """
    block = SubagentBlock()
    listener = install_default_listener(block)
    try:
        # Emit a subagent event
        # on the bus.
        get_bus().emit(
            Event(
                "subagent.started",
                {
                    "subagent_id": "sub:bus",
                    "goal": "from bus",
                },
            )
        )
        assert "sub:bus" in block.rows
    finally:
        # Clean up: unsubscribe
        # so the listener does
        # not leak into the next
        # test.
        get_bus().unsubscribe(listener)
