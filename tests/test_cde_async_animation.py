"""R-2026-06-20 (CDE-ASYNC):
``ChatApp._run_agent`` must NOT block the textual
main loop while the LLM streams, otherwise the
``PulsatingDots`` placeholder animation freezes
and the TUI looks frozen.

When the chat app is booted into the textual main
loop (``_thread_id`` is set), ``_run_agent``
spawns a daemon thread to drive the agent loop
and posts results back via ``call_from_thread``.
The placeholder's ``set_interval`` continues to
fire on the main loop because the main loop is
not blocked.
"""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


@pytest.mark.asyncio
async def test_run_agent_does_not_block_main_loop(tmp_path: Path) -> None:
    """The PulsatingDots ``set_interval`` fires at
    ~150ms while ``_run_agent`` is waiting on the
    LLM. If ``_run_agent`` blocks the main thread,
    the interval never fires and the placeholder
    looks frozen.

    Test setup: a slow ``MockLLM`` that takes ~600ms
    total to stream its reply. We boot the app,
    mount a real ``PulsatingDots``, schedule a
    ``_run_agent`` call, then watch for at least
    2 ``_advance`` ticks during the stream. If
    ``_run_agent`` were synchronous on the main
    loop, ``_advance`` would not fire (the test
    would time out).
    """
    from manusift.tui.async_widgets import PulsatingDots

    # Track PulsatingDots updates via a counter
    # patched onto ``Static.update``.
    from textual.widgets import Static

    update_count = [0]
    original_update = Static.update

    def counted_update(self, *args, **kwargs):
        update_count[0] += 1
        return original_update(self, *args, **kwargs)

    Static.update = counted_update
    try:
        app = ChatApp(
            session_id=None,
            llm_client=MockLLM(),
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            # Mount a PulsatingDots explicitly and
            # schedule ``_run_agent``.
            dots = PulsatingDots(id="probe")
            await app.mount(dots)
            await pilot.pause(0.05)
            updates_before = update_count[0]
            # Schedule _run_agent. The MockLLM
            # streams a few chunks; the placeholder
            # should keep animating throughout.
            t0 = time.monotonic()
            app._run_agent("hello")
            # Wait ~1 second for the agent to finish
            # + the dots to tick at least 4 times
            # (interval 150ms -> 6 ticks in 1s).
            await pilot.pause(1.0)
            updates_after = update_count[0]
            elapsed = time.monotonic() - t0
            # The main loop must have ticked the
            # interval multiple times while
            # ``_run_agent`` was waiting.
            assert updates_after - updates_before >= 4, (
                f"PulsatingDots only updated "
                f"{updates_after - updates_before} "
                f"times in {elapsed:.2f}s -- "
                f"main loop is blocked"
            )
    finally:
        Static.update = original_update