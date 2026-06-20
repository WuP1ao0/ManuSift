"""R-2026-06-20 (CDE-RENDER-2):
regression tests for
the user-visible
rendering bugs
shown in the
TUI screenshot
at 14:36 (June 20,
2026).

The three bugs:

  1. ``<span class='role-user'>user</span>``
     appeared as
     literal text
     in the chat
     log instead
     of being
     rendered as
     ``user`` in
     a teal color.
     Root cause:
     Textual does
     NOT parse
     HTML ``<span>``
     markup --
     it only
     parses Rich
     ``[red]text[/red]``
     markup.

  2. ``assistant``
     label was
     shown instead
     of the
     user-facing
     identity
     ``ManuSift``.

  3. Each user /
     assistant
     turn was
     appended to
     the chat log
     2-3 times.
     Root cause:
     ``_on_assistant_text``
     AND
     ``_on_finished_runner``
     both called
     ``_replace_placeholder_with_message``
     which in
     turn called
     ``_append_message``
     -- so the
     message was
     appended
     twice.
"""
from __future__ import annotations

import asyncio

import pytest

from manusift.contracts import ChatMessage
from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp, _role_display_name


# ---------- Bug #1: role label uses Rich markup, not HTML <span> ----------

@pytest.mark.asyncio
async def test_render_message_uses_rich_markup_not_html_span() -> None:
    """``_render_message``
    must produce
    a Rich-markup
    string (NOT
    HTML ``<span>``).
    Textual only
    parses Rich
    markup, so
    HTML ``<span>``
    would be
    shown literally."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # A
        # user
        # message
        # should
        # be
        # rendered
        # with
        # a
        # Rich
        # ``[b]user[/b]``
        # marker
        # (no
        # ``<span>``).
        widget = app._render_message(
            ChatMessage(role="user", content="hello")
        )
        # ``Static.content`` is
        # the
        # original
        # text
        # (the
        # markup
        # is
        # parsed
        # at
        # render
        # time).
        text = widget.content
        assert "[b]user[/b]" in text
        assert "<span" not in text
        # The
        # markup
        # must
        # be
        # enabled
        # on
        # the
        # widget
        # (default
        # for
        # Static
        # is
        # True
        # but
        # we
        # make
        # it
        # explicit).
        assert widget._render_markup is True


# ---------- Bug #2: assistant label is "ManuSift" ----------

def test_role_display_name_maps_assistant_to_manusift() -> None:
    """``_role_display_name("assistant")``
    returns
    ``"ManuSift"``
    (the
    user-facing
    identity),
    not
    ``"assistant"``."""
    assert _role_display_name("assistant") == "ManuSift"
    # Other
    # roles
    # are
    # unchanged.
    assert _role_display_name("user") == "user"
    assert _role_display_name("system") == "system"
    assert _role_display_name("tool") == "tool"
    assert _role_display_name("error") == "error"


# ---------- Bug #3: message duplication fix ----------

@pytest.mark.asyncio
async def test_assistant_text_not_duplicated() -> None:
    """``_on_assistant_text``
    must NOT
    call
    ``_append_message``
    twice for
    the same
    text.

    The bug:
    the
    P1
    wiring
    called
    ``_append_message``
    AND
    ``_replace_placeholder_with_message``
    (which
    also
    calls
    ``_append_message``).
    The
    fix
    routes
    through
    ``_replace_placeholder_with_message``
    only,
    with
    a
    fallback
    ``_append_message``
    for
    the
    case
    where
    ``_history is None``
    (test
    setup
    with
    ``__new__``).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # Mount
        # a
        # trace
        # block
        # so
        # seal
        # doesn't
        # crash.
        app._mount_trace_block_if_needed()
        await pilot.pause(0.05)
        # Drop
        # the
        # placeholder
        # so
        # the
        # replace
        # path
        # succeeds.
        from manusift.tui.async_widgets import PulsatingDots
        from textual.containers import VerticalScroll
        scroll = app.query_one("#history", VerticalScroll)
        try:
            placeholder = app.query_one(
                f"#{app._PLACEHOLDER_ID}"
            )
        except Exception:  # noqa: BLE001
            placeholder = PulsatingDots(id=app._PLACEHOLDER_ID)
            scroll.mount(placeholder)
        await pilot.pause(0.05)
        before = len(app._history)
        # Drive
        # the
        # callback
        # once.
        app._on_assistant_text("hello world")
        await pilot.pause(0.05)
        # Exactly
        # ONE
        # assistant
        # message
        # should
        # be
        # appended
        # (not 2).
        after = len(app._history)
        delta = after - before
        assert delta == 1, (
            f"assistant text was appended {delta} times "
            f"(expected 1)"
        )
        # And
        # the
        # content
        # is
        # correct.
        msg = app._history[-1]
        assert msg.role == "assistant"
        assert "hello world" in msg.content