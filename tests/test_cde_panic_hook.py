"""R-2026-06-20 (CDE-UI-P0.3):
regression test for
the TUI panic
hook.

The previous
``chat_app.py``
had ``except
Exception:
pass``
in 25+
places. A real
bug (e.g. agent
crash) would be
silently
swallowed and
the user would
not see it.

After P0.3:
- ``install_panic_hook(workspace_dir)``
  installs a
  ``sys.excepthook``
  that writes the
  full traceback to
  ``<workspace>/crash.log``
  BEFORE
  delegating to
  the previous
  hook.
- ``append_panic_to_chat(app, ...)``
  surfaces the
  crash as a
  ``role="error"``
  ``ChatMessage``
  in the chat
  log so the user
  sees it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp
from manusift.tui.panic_hook import (
    append_panic_to_chat,
    install_panic_hook,
)


def test_install_panic_hook_creates_crash_log(
    tmp_path: Path,
) -> None:
    """``install_panic_hook`` must write
    the traceback of an unhandled
    exception to ``<workspace>/crash.log``.
    """
    install_panic_hook(tmp_path)
    try:
        raise RuntimeError("test crash")
    except RuntimeError as exc:
        import sys
        sys.excepthook(type(exc), exc, exc.__traceback__)
    log = tmp_path / "crash.log"
    assert log.exists(), (
        f"crash.log not created at {log}"
    )
    text = log.read_text(encoding="utf-8")
    assert "test crash" in text
    assert "RuntimeError" in text


def test_append_panic_to_chat_adds_error_message() -> None:
    """``append_panic_to_chat`` must
    append a ``role="error"``
    ``ChatMessage`` to the chat log
    so the user sees the crash in
    the TUI.
    """
    import asyncio

    async def driver() -> None:
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            try:
                raise ValueError("boom")
            except ValueError as exc:
                append_panic_to_chat(app, type(exc), exc)
            await pilot.pause(0.1)
            # Find the error
            # message in
            # _history.
            error_msgs = [
                m for m in app._history
                if getattr(m, "role", None) == "error"
            ]
            assert any(
                "boom" in (m.content or "") for m in error_msgs
            ), (
                "expected error ChatMessage containing 'boom'"
            )

    asyncio.run(driver())


def test_panic_hook_is_idempotent() -> None:
    """Calling ``install_panic_hook``
    twice must not crash (the second
    call replaces the hook).
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        install_panic_hook(ws)
        install_panic_hook(ws)  # second call must not raise
        # The hook is still installed and
        # functional.
        try:
            raise RuntimeError("idempotent test")
        except RuntimeError as exc:
            import sys
            sys.excepthook(type(exc), exc, exc.__traceback__)
        assert (ws / "crash.log").exists()