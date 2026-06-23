"""R-2026-06-21 (CDE-UI-P1.6):
regression test for
the always-mounted
DetectorTraceBlock.

Before P1.6,
``_mount_detector_block_if_needed``
was called only from
``_run_agent``, which
meant a fresh block
was mounted on every
turn. The user had to
press ``x`` after every
turn to see the block
again.

After P1.6, the block
is mounted once in
``on_mount`` and its
internal state is
reset on each
``job.started`` event
(handled by
``DetectorTraceBlock.on_event_received``)
so the block is always
visible at the top of
the chat log.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp
from manusift.tui.detector_block import DetectorTraceBlock


@pytest.mark.asyncio
async def test_detector_block_is_mounted_on_app_start() -> None:
    """After ``on_mount``, the
    ``DetectorTraceBlock`` is mounted in
    the ``#history`` widget. The user
    sees it immediately, even before
    submitting the first user message.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        assert app._active_detector_block is not None, (
            "DetectorTraceBlock must be mounted in on_mount; "
            "got _active_detector_block = None"
        )
        # The
        # block
        # must
        # be
        # in
        # the
        # ``#history``
        # widget
        # tree.
        history = app.query_one("#history")
        blocks = [
            c for c in history.children
            if isinstance(c, DetectorTraceBlock)
        ]
        assert len(blocks) >= 1, (
            "DetectorTraceBlock must be a child of #history; "
            f"history children: "
            f"{[type(c).__name__ for c in history.children]}"
        )


@pytest.mark.asyncio
async def test_mount_detector_block_is_idempotent() -> None:
    """Calling
    ``_mount_detector_block_if_needed``
    twice must NOT create a second
    block. The second call returns
    early (block is already mounted).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # First call already happened in
        # ``on_mount``. Capture the
        # current block.
        first_block = app._active_detector_block
        assert first_block is not None
        # Now call again (simulates the
        # ``_run_agent`` path).
        app._mount_detector_block_if_needed()
        second_block = app._active_detector_block
        assert second_block is first_block, (
            "Second call to "
            "_mount_detector_block_if_needed must NOT "
            "create a second block; should be "
            "idempotent"
        )
        # And the history widget has
        # exactly one DetectorTraceBlock.
        history = app.query_one("#history")
        blocks = [
            c for c in history.children
            if isinstance(c, DetectorTraceBlock)
        ]
        assert len(blocks) == 1, (
            f"history must contain exactly 1 "
            f"DetectorTraceBlock; got {len(blocks)}"
        )


@pytest.mark.asyncio
async def test_action_toggle_detector_trace_still_works() -> None:
    """The ``x`` action still works
    (toggles the block's display)
    so users can hide / show the
    block manually if needed.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        block = app._active_detector_block
        assert block is not None
        # Visible by default.
        assert block.display is not False, (
            f"DetectorTraceBlock must be visible by default; "
            f"display={block.display!r}"
        )
        # Hide via ``x``.
        app.action_toggle_detector_trace()
        await pilot.pause(0.05)
        assert block.display is False, (
            f"action_toggle_detector_trace must hide the block; "
            f"display={block.display!r}"
        )
        # Show again.
        app.action_toggle_detector_trace()
        await pilot.pause(0.05)
        assert block.display is not False, (
            f"second action_toggle_detector_trace must show; "
            f"display={block.display!r}"
        )


@pytest.mark.asyncio
async def test_source_inspection_no_regression_in_mount_helper() -> None:
    """Static check:
    ``_mount_detector_block_if_needed``
    must early-return when
    ``_active_detector_block`` is
    already set (the idempotency
    guard). Future changes that
    re-introduce the per-turn
    mount will fail this test.
    """
    import inspect
    source = inspect.getsource(ChatApp._mount_detector_block_if_needed)
    # The
    # early-return
    # guard
    # must
    # come
    # before
    # any
    # mount
    # call.
    early_return_idx = source.find("if getattr")
    mount_idx = source.find("scroll.mount")
    assert early_return_idx >= 0, (
        "_mount_detector_block_if_needed must have an "
        "early-return guard checking _active_detector_block"
    )
    assert mount_idx > early_return_idx, (
        "early-return guard must come before the mount call; "
        "otherwise the helper would mount multiple blocks"
    )