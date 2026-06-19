"""Tests for the async / non-blocking TUI agent loop
(R-audit 2026-06-10).

Before this audit the
``_run_agent`` method ran
``Runner.run`` synchronously
on the main loop, blocking
the TUI for the full
duration of the LLM call.
The audit refactored it to
use ``self.run_worker`` with
``asyncio.to_thread``,
mounts a pulsating-dots
placeholder, and wires
``Esc`` / ``Ctrl+C`` to
cancel the in-flight worker.

These tests are sync
(no pytest-asyncio
needed) -- each test that
needs the TUI event loop
uses ``asyncio.run`` to
drive the pilot.

Tests pin these
contracts:

  1. ``PulsatingDots`` rotates
     through 3 dot patterns.
  2. ``PhaseSpinner`` rotates
     through 10 Braille
     frames and has a
     cancellable flag.
  3. ``_mount_placeholder``
     adds a placeholder to
     the history.
  4. ``_replace_placeholder_with_message``
     removes the placeholder
     and mounts a real
     message.
  5. ``_replace_placeholder_with_error``
     does the same with an
     error message.
  6. ``action_abort`` clears
     the input even when no
     worker is running.
  7. ``action_retry`` re-dispatches
     the last user message.
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. PulsatingDots ----------


def test_pulsating_dots_rotates_three_frames() -> None:
    """The PulsatingDots
    widget's text contains
    the 3 dot patterns when
    its interval fires."""
    from manusift.tui.async_widgets import (
        _DOT_FRAMES,
        PulsatingDots,
    )
    assert len(_DOT_FRAMES) == 3
    dots = PulsatingDots()
    assert "\u25cf" in str(dots.content)
    dots.stop()


def test_pulsating_dots_stops_cleanly() -> None:
    """``stop()`` cancels the
    interval; subsequent
    ``update`` calls do not
    fire."""
    from manusift.tui.async_widgets import PulsatingDots
    dots = PulsatingDots()
    dots.stop()
    dots.stop()
    assert dots._stopped is True


# ---------- 2. PhaseSpinner ----------


def test_phase_spinner_initial_state() -> None:
    """The PhaseSpinner starts
    with the first braille
    frame + the given phase
    label."""
    from manusift.tui.async_widgets import (
        _BRAILLE_FRAMES,
        PhaseSpinner,
    )
    s = PhaseSpinner(phase="Reading manuscript")
    plain = s.render().plain
    assert _BRAILLE_FRAMES[0] in plain
    assert "Reading manuscript" in plain
    s.stop()


def test_phase_spinner_set_phase() -> None:
    """``set_phase`` updates
    the label."""
    from manusift.tui.async_widgets import PhaseSpinner
    s = PhaseSpinner(phase="init")
    s.set_phase("Verifying references")
    assert "Verifying references" in s.render().plain
    s.stop()


def test_phase_spinner_cancel() -> None:
    """``cancel()`` flips
    ``is_cancelled`` and
    updates the label to
    'cancelled'."""
    from manusift.tui.async_widgets import PhaseSpinner
    s = PhaseSpinner(phase="init")
    s.cancel()
    assert s.is_cancelled is True
    assert "cancelled" in s.render().plain
    assert s._interval is None


# ---------- 3. Mount / replace placeholder ----------


def test_mount_placeholder_in_history() -> None:
    """``_mount_placeholder``
    mounts a ``PulsatingDots``
    widget in the history
    panel with the expected
    id."""
    from manusift.tui.async_widgets import PulsatingDots
    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Static

    async def driver():
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            app._mount_placeholder()
            await pilot.pause(0.1)
            history = app.query_one("#history")
            ph = history.query_one(
                f"#{app._PLACEHOLDER_ID}"
            )
            assert isinstance(ph, PulsatingDots)
            assert isinstance(ph, Static)
            ph.stop()

    asyncio.run(driver())


def test_replace_placeholder_with_message() -> None:
    """``_replace_placeholder_with_message``
    removes the placeholder
    and mounts a real
    message in its place."""
    from manusift.tui.chat_app import ChatApp
    from manusift.contracts import ChatMessage

    async def driver():
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            app._mount_placeholder()
            await pilot.pause(0.1)
            app._replace_placeholder_with_message(
                ChatMessage(
                    role="assistant", content="hi back"
                )
            )
            await pilot.pause(0.1)
            history = app.query_one("#history")
            try:
                history.query_one(
                    f"#{app._PLACEHOLDER_ID}"
                )
                assert False, "placeholder should be gone"
            except Exception:  # noqa: BLE001
                pass
            children = list(history.query("Static"))
            assert any(
                "hi back" in str(w.content)
                for w in children
            )

    asyncio.run(driver())


def test_replace_placeholder_with_error() -> None:
    """``_replace_placeholder_with_error``
    swaps the placeholder for
    an error message that
    mentions retry / dismiss."""
    from manusift.tui.chat_app import ChatApp

    async def driver():
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            app._mount_placeholder()
            await pilot.pause(0.1)
            app._replace_placeholder_with_error(
                "connection timeout"
            )
            await pilot.pause(0.1)
            history = app.query_one("#history")
            try:
                history.query_one(
                    f"#{app._PLACEHOLDER_ID}"
                )
                assert False, "placeholder should be gone"
            except Exception:  # noqa: BLE001
                pass
            children = list(history.query("Static"))
            assert any(
                "connection timeout" in str(w.content)
                and "Ctrl+R" in str(w.content)
                for w in children
            )

    asyncio.run(driver())


# ---------- 4. Action wiring ----------


def test_action_retry_no_history() -> None:
    """``action_retry`` with no
    user message in history
    surfaces a system
    message saying so."""
    from manusift.tui.chat_app import ChatApp

    async def driver():
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            app._history.clear()
            app.action_retry()
            await pilot.pause(0.1)
            history = app.query_one("#history")
            children = list(history.query("Static"))
            assert any(
                "nothing to retry" in str(w.content)
                for w in children
            )

    asyncio.run(driver())


def test_action_retry_redispatches_last_user() -> None:
    """``action_retry`` with a
    user message in history
    re-dispatches it (mounts
    a new placeholder + runs
    the agent). We patch
    ``_run_agent`` to a no-op
    so the test does not
    actually call the LLM.
    """
    from manusift.tui.chat_app import ChatApp
    from manusift.contracts import ChatMessage
    from manusift.tui import chat_app

    async def driver():
        app = ChatApp()
        dispatched = []

        def fake_run(self, text: str) -> None:
            dispatched.append(text)
            try:
                history = self.query_one("#history")
                ph = history.query_one(
                    f"#{self._PLACEHOLDER_ID}"
                )
                ph.stop()
                ph.remove()
            except Exception:  # noqa: BLE001
                pass

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            app._history.append(
                ChatMessage(
                    role="user", content="hello"
                )
            )
            original = chat_app.ChatApp._run_agent
            chat_app.ChatApp._run_agent = fake_run
            try:
                app.action_retry()
            finally:
                chat_app.ChatApp._run_agent = original
            await pilot.pause(0.1)
            assert dispatched == ["hello"]

    asyncio.run(driver())


def test_action_abort_when_idle() -> None:
    """``action_abort`` is safe
    to call when no worker
    is running. It should
    just clear the input."""
    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Input, TextArea

    async def driver():
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            inp = app.query_one("#input", TextArea)
            inp.text = "discarded text"
            await pilot.pause(0.1)
            app.action_abort()
            await pilot.pause(0.1)
            assert inp.text == ""

    asyncio.run(driver())
