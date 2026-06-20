"""R-2026-06-20 (CDE-UI-P0.8):
regression test for
the plan-mode
queue visibility.

Before P0.8,
plan mode
queued a
user message
in
``self._pending_input``
but only the
status line
showed "plan
mode: queued
(N pending)"
-- the user
couldn't see
WHAT was
queued. After
P0.8, every
queued message
mounts a
``Static`` with
the
``queue-row``
CSS class into
``#history`` so
the user can
see and audit
the queue.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


def _get_queue_rows(app: ChatApp) -> list[object]:
    return [
        w for w in app._history_scroll.children
        if "queue-row" in (w.classes or [])
    ]


@pytest.mark.asyncio
async def test_plan_mode_queues_message_visible_in_history() -> None:
    """When plan mode is on and the user
    submits a message, a ``queue-row``
    Static must appear in ``#history``
    so the user sees the queued content.
    """
    from textual.widgets import Static

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # Turn plan mode on
        app._cmd_plan("on")
        await pilot.pause(0.05)
        # Submit a message -- it should be queued, not run
        app._submit_user_message("step 1: ingest")
        await pilot.pause(0.05)
        # The agent must NOT have run (plan mode holds it)
        assert app._pending_input == ["step 1: ingest"]
        # And there
        # must be
        # a queue-row
        # Static in
        # history.
        rows = _get_queue_rows(app)
        assert len(rows) == 1, (
            f"expected 1 queue-row Static; got {len(rows)}"
        )
        row = rows[0]
        assert isinstance(row, Static), (
            f"expected Static; got {row.__class__.__name__}"
        )
        assert "step 1: ingest" in (row.content or ""), (
            f"queue-row content must include the queued "
            f"text; got {row.content!r}"
        )


@pytest.mark.asyncio
async def test_plan_mode_queue_preview_truncated() -> None:
    """A long queued message must be
    truncated to 60 chars in the
    preview (the actual queue keeps
    the full text -- only the visual
    preview is truncated).
    """
    long_text = "x" * 200
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        app._cmd_plan("on")
        await pilot.pause(0.05)
        app._submit_user_message(long_text)
        await pilot.pause(0.05)
        rows = _get_queue_rows(app)
        assert len(rows) == 1
        text = rows[0].content or ""
        # The full text must NOT be in the
        # preview (it's 200 chars).
        assert len(text) < 200, (
            f"queue-row preview should be truncated; "
            f"len={len(text)}"
        )
        # But the underlying queue keeps
        # the full text.
        assert app._pending_input == [long_text]


@pytest.mark.asyncio
async def test_plan_mode_off_queues_no_row() -> None:
    """When plan mode is off, submitting
    a message must NOT mount a
    queue-row -- the message is
    dispatched to the agent directly.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # Plan mode is OFF by default.
        app._submit_user_message("hello")
        await pilot.pause(0.05)
        rows = _get_queue_rows(app)
        assert rows == [], (
            f"no queue-row should appear when plan "
            f"mode is off; got {rows!r}"
        )


@pytest.mark.asyncio
async def test_multiple_queue_rows_accumulate() -> None:
    """Submitting multiple messages in
    plan mode must mount multiple
    queue-row Statics (one per queued
    message), in order.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        app._cmd_plan("on")
        await pilot.pause(0.05)
        app._submit_user_message("step 1")
        await pilot.pause(0.05)
        app._submit_user_message("step 2")
        await pilot.pause(0.05)
        app._submit_user_message("step 3")
        await pilot.pause(0.05)
        rows = _get_queue_rows(app)
        assert len(rows) == 3, (
            f"expected 3 queue-rows; got {len(rows)}"
        )
        # In order.
        contents = [r.content for r in rows]
        assert "step 1" in contents[0]
        assert "step 2" in contents[1]
        assert "step 3" in contents[2]