"""R-2026-06-20 (CDE-UI-P0.5):
regression test for
the Esc binding
that pointed at
a non-existent
``action_cancel``.

The previous
``BINDINGS`` list
included
``Binding("escape",
"Cancel", ...)``
but no
``action_cancel``
method existed
in the class.
Textual silently
ignored the
unbound action
(the app kept
running), but
the BINDINGS
list was
misleading:
advertising a
hotkey that did
nothing.

After P0.5, the
binding is
deleted and the
only hotkey
documented in
``BINDINGS``
does what it
says.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


def test_no_dangling_escape_binding() -> None:
    """``ChatApp.BINDINGS`` must not
    contain ``Binding("escape", ...)``
    if there is no matching
    ``action_cancel`` method (the
    bug was: binding advertised but
    did nothing).
    """
    from manusift.tui.chat_app import ChatApp
    bindings = ChatApp.BINDINGS
    for b in bindings:
        # ``Binding`` is a NamedTuple; ``key``
        # is the first field.
        key = b[0] if hasattr(b, "__getitem__") else getattr(b, "key", None)
        if key == "escape":
            pytest.fail(
                f"ChatApp.BINDINGS still has 'escape' binding; "
                f"P0.5 removed it because no action_cancel handler "
                f"existed. If you want Esc to do something, "
                f"add a real handler."
            )


@pytest.mark.asyncio
async def test_esc_does_not_quit_app() -> None:
    """Pressing Esc on the main screen
    must NOT quit the TUI (no
    ``action_cancel`` = no quit).
    Before P0.5 the binding existed
    but had no handler -- Textual
    silently ignored it. After P0.5,
    no binding exists, but Esc
    behavior is unchanged (Textual's
    IME / popover handlers are
    unaffected).
    """
    from textual.widgets import TextArea
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # Type some text first.
        ta = app.query_one("#input", TextArea)
        ta.text = "hello"
        await pilot.pause(0.05)
        # Press Esc -- app must still be running.
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert app.is_running, (
            "Pressing Esc must not quit the app"
        )