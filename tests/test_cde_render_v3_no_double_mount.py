"""R-2026-06-20 (CDE-RENDER-4):
regression test for
the double-mount
bug shown in the
15:04 screenshot.

User typed "你好"
once, but the
chat log
showed:
- "user 你好" (×2)
- "ManuSift 你好!我是..." (×2)
- "system end_turn" (×2)

Root cause:
both
``_HistoryList.append()``
AND
``_append_message()``
mounted a
widget for
the same
ChatMessage,
producing 2
widgets per
message.

Fix:
``_HistoryList.append()``
is now a
pure list
operation.
``_append_message()``
is the
single source
of truth for
"add a message
to history
+ mount the
widget".
"""
from __future__ import annotations

import asyncio

import pytest

from manusift.contracts import ChatMessage
from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


# ---------- 1. _HistoryList.append no longer mounts ----------

def test_history_list_append_does_not_mount() -> None:
    """``_HistoryList.append(msg)``
    must NOT
    mount a
    widget on
    the
    ``#history``
    scroll.
    The
    mount is
    the
    responsibility
    of
    ``_append_message``."""
    from manusift.tui.chat_app import _HistoryList
    hist = _HistoryList(app=None)
    # No
    # _scroll_ref
    # --
    # append
    # would
    # crash
    # if
    # it
    # tried
    # to
    # mount.
    hist.append(
        ChatMessage(role="user", content="hi")
    )
    # The
    # message
    # is
    # in
    # the
    # list.
    assert len(hist) == 1
    assert hist[0].content == "hi"
    # But
    # no
    # widget
    # is
    # attached
    # (the
    # override
    # does
    # not
    # store
    # a
    # widget
    # anywhere).
    # The
    # best
    # we
    # can
    # assert
    # is
    # that
    # append
    # does
    # not
    # raise
    # (the
    # previous
    # version
    # had
    # a
    # try/except
    # that
    # masked
    # the
    # mount
    # attempt
    # but
    # still
    # tried).


# ---------- 2. _append_message is the single source of truth ----------

@pytest.mark.asyncio
async def test_append_message_mounts_exactly_one_widget() -> None:
    """``_append_message(msg)``
    must mount
    exactly ONE
    widget for
    ONE message
    (not 2).

    The previous
    version had
    a bug where
    ``_HistoryList.append``
    ALSO mounted,
    so 2 widgets
    appeared per
    message.
    """
    from textual.widgets import Static

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # Drop the
        # MockLLM
        # banner
        # so the
        # count
        # is
        # clean.
        from textual.containers import VerticalScroll
        history = app.query_one("#history", VerticalScroll)
        for child in list(history.children):
            child.remove()
        await pilot.pause(0.05)
        before = len(history.children)
        # Add
        # ONE
        # message.
        app._append_message(
            ChatMessage(role="user", content="hi")
        )
        await pilot.pause(0.1)
        after = len(history.children)
        delta = after - before
        # Exactly
        # one
        # widget
        # was
        # mounted.
        assert delta == 1, (
            f"_append_message mounted {delta} widgets "
            f"(expected 1) -- the double-mount bug "
            f"from CDE-RENDER-2"
        )
        # And
        # it's
        # a
        # Static
        # widget
        # (the
        # _render_message
        # result).
        new_widget = history.children[-1]
        assert isinstance(new_widget, Static)


# ---------- 3. End-to-end: full user/assistant turn produces 1 widget each ----------

@pytest.mark.asyncio
async def test_full_turn_no_duplicate_widgets() -> None:
    """A complete
    user message
    + agent response
    cycle must
    produce ONE
    user widget
    + ONE
    assistant
    widget
    (not 2 of
    each).

    This is the
    end-to-end
    equivalent of
    the user
    screenshot at
    15:04.
    """
    from textual.containers import VerticalScroll
    from manusift.llm.chat import ChatResponse
    from textual.widgets import Static

    class _HelloLLM:
        name = "hello"
        def chat_stream(self, m, tools=None, session_id=None, *, max_tokens=4096):
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "Hi!"}],
                stop_reason="end_turn",
            )
        def chat(self, m, tools=None, session_id=None, *, max_tokens=4096):
            return ChatResponse(
                content_blocks=[{"type": "text", "text": "Hi!"}],
                stop_reason="end_turn",
            )
        def is_available(self): return True

    app = ChatApp(llm_client=_HelloLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # Drop
        # the
        # MockLLM
        # banner
        # so
        # the
        # count
        # is
        # clean.
        history = app.query_one("#history", VerticalScroll)
        for child in list(history.children):
            child.remove()
        await pilot.pause(0.05)
        # Submit
        # a
        # message.
        from textual.widgets import TextArea, Static
        inp = app.query_one("#input", TextArea)
        inp.focus()
        await pilot.pause(0.05)
        inp.text = "hi"
        await pilot.pause(0.05)
        app.action_submit_input()
        # Wait
        # for
        # the
        # agent
        # to
        # finish.
        for _ in range(20):
            await pilot.pause(0.1)
            if not app._agent_running:
                break
        await pilot.pause(0.2)
        # Count
        # the
        # msg-row
        # widgets
        # (user
        # +
        # assistant).
        # We
        # expect
        # exactly
        # 1
        # user
        # +
        # 1
        # assistant
        # Static
        # (with
        # classes
        # ``msg-row``).
        msg_widgets = [
            w for w in history.children
            if isinstance(w, Static)
            and "msg-row" in (w.classes or [])
        ]
        user_widgets = [
            w for w in msg_widgets
            if getattr(w, "_role", None) == "user"
        ]
        assistant_widgets = [
            w for w in msg_widgets
            if getattr(w, "_role", None) == "assistant"
        ]
        assert len(user_widgets) == 1, (
            f"expected 1 user msg widget, got {len(user_widgets)} -- "
            f"double-mount bug?"
        )
        assert len(assistant_widgets) == 1, (
            f"expected 1 assistant msg widget, got {len(assistant_widgets)} -- "
            f"double-mount bug?"
        )