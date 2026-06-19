"""R-2026-06-20 (CDE-RENDER):
``ChatApp._render_message`` must produce a
``Static`` widget with markup rendering enabled
so the ``<span class='role-XXX'>`` markup is
parsed (not shown literally in the chat log).

User-reported (screenshot): the chat log was
showing ``<span class='role-user'>user</span>``
verbatim. Textual stores the markup flag on
``Static._render_markup`` (private but stable
since textual 0.40).
"""
from __future__ import annotations

import pytest

from manusift.contracts import ChatMessage
from manusift.tui.chat_app import ChatApp


def test_render_message_uses_markup_true() -> None:
    """``_render_message`` must produce a Static
    with ``_render_markup=True`` so the role span
    is parsed (not literal)."""
    chat_app = ChatApp()
    msg = ChatMessage(role="user", content="hello")
    widget = chat_app._render_message(msg)
    assert widget._render_markup is True, (
        f"Static._render_markup must be True so <span> parses; "
        f"got {widget._render_markup!r}"
    )


def test_render_message_escapes_user_content() -> None:
    """User content with ``<script>`` must be
    escaped so it renders as literal text, not as
    a Rich tag injection."""
    from rich.markup import escape

    chat_app = ChatApp()
    msg = ChatMessage(
        role="user", content="<script>alert(1)</script>"
    )
    widget = chat_app._render_message(msg)
    # The escaped form is in the renderable string.
    rendered = str(widget._Static__content)
    assert escape("<script>") in rendered
    # And markup=True so the role span renders.
    assert widget._render_markup is True


@pytest.mark.asyncio
async def test_message_in_history_renders_markup() -> None:
    """In the booted app, ``_render_message`` markup
    is enabled so the role span will parse when
    rendered."""
    from manusift.llm import MockLLM

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        msg = ChatMessage(role="user", content="hi there")
        app._append_message(msg)
        await pilot.pause(0.1)
        # The Static we just mounted is in
        # ``app._history_scroll.children``.
        static_widgets = [
            w for w in app._history_scroll.children
            if w.__class__.__name__ == "Static"
        ]
        assert static_widgets, "no Static widget mounted"
        widget = static_widgets[-1]
        # Markup flag must be True so the role
        # span parses when the widget is rendered.
        assert widget._render_markup is True
        # The content string still contains the
        # raw ``<span>`` markup (Textual parses
        # it on render); we just verify the
        # constructor stored the flag.
        content_str = str(widget._Static__content)
        assert "user" in content_str
        assert "hi there" in content_str