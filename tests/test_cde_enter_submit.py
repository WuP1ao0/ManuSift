"""R-2026-06-20 (CDE-ENTER):
``_SubmitOnEnterTextArea`` must intercept plain
``Enter`` (not just ``Ctrl+J``) and call
``app.action_submit_input()``.

User-reported: "input is swallowed, page
freezes" -- pressing Enter in the input box
just inserted a newline because
``_SubmitOnEnterTextArea``'s class body was
empty (the docstring described Enter
interception but the actual ``_on_key`` /
``_on_character`` / ``_on_paste`` handler was
never written).
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp
from manusift.tui.chat_app import _SubmitOnEnterTextArea


@pytest.mark.asyncio
async def test_enter_submits_input() -> None:
    """Pressing plain Enter on the input must
    submit the message, not insert a newline."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        from textual.widgets import TextArea

        inp = app.query_one("#input", TextArea)
        assert isinstance(inp, _SubmitOnEnterTextArea)
        inp.focus()
        await pilot.pause(0.1)
        inp.text = "hello world"
        await pilot.pause(0.1)
        # Press Enter. If the
        # ``_on_key`` override
        # works, the input is
        # cleared and a user
        # message is mounted to
        # history.
        await pilot.press("enter")
        await pilot.pause(0.2)
        # Input should be cleared
        assert inp.text == "", (
            f"input not cleared after Enter; "
            f"got {inp.text!r} (the message was "
            f"swallowed)"
        )
        # A user message should be in the history
        from manusift.contracts import ChatMessage

        # The user message must be in
        # ``_history`` (which is a
        # ``_HistoryList``).
        msgs = list(app._history)
        user_msgs = [
            m for m in msgs
            if isinstance(m, ChatMessage) and m.role == "user"
        ]
        assert user_msgs, (
            f"no user message mounted to history "
            f"after Enter; history={msgs!r}"
        )
        assert user_msgs[0].content == "hello world"


@pytest.mark.asyncio
async def test_ctrl_j_still_works() -> None:
    """Ctrl+J is the explicit multi-line submit
    alias; pressing it must also submit (the
    existing App-level Binding handles this)."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        from textual.widgets import TextArea

        inp = app.query_one("#input", TextArea)
        inp.focus()
        await pilot.pause(0.1)
        inp.text = "via ctrl+j"
        await pilot.pause(0.1)
        await pilot.press("ctrl+j")
        await pilot.pause(0.2)
        assert inp.text == "", (
            f"input not cleared after Ctrl+J; "
            f"got {inp.text!r}"
        )


@pytest.mark.asyncio
async def test_enter_in_middle_of_text_does_not_split_line() -> None:
    """R-2026-06-20 (CDE-ENTER):
    Even mid-line Enter should
    submit (not insert a
    newline in the middle of
    the buffer)."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        from textual.widgets import TextArea

        inp = app.query_one("#input", TextArea)
        inp.focus()
        await pilot.pause(0.1)
        inp.text = "single line message"
        await pilot.pause(0.1)
        await pilot.press("enter")
        await pilot.pause(0.2)
        # The buffer should be cleared (not
        # contain a newline at the end of
        # the original text).
        assert inp.text == ""
        assert "\n" not in inp.text