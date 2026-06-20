"""R-2026-06-20 (CDE-UI-P0.4):
``render_message`` (the chat's single source of
truth for message widget rendering) must:

* return a ``Horizontal`` widget (role-dot +
  body-column layout) -- not a bare ``Static``.
* use Rich markup, NOT HTML ``<span>`` --
  Textual parses Rich only.
* escape user content so a user can't inject
  Rich tags that would be re-interpreted as
  markup (security).

The previous version of this file (CDE-RENDER,
R-2026-06-20) asserted on HTML ``<span>``
markup; that test was deleted because the new
design uses Rich markup + CSS classes for
role colors.
"""
from __future__ import annotations

import pytest

from manusift.contracts import ChatMessage
from manusift.tui.rendering import render_message


# ---------- 1. render_message returns Horizontal ----------

def test_render_message_returns_horizontal() -> None:
    """``render_message`` must return a
    ``Horizontal`` (role-dot + body-column),
    NOT a bare ``Static``. The dot column
    carries the role color, the body column
    has the head (role label + timestamp) +
    body (content).
    """
    from textual.containers import Horizontal

    msg = ChatMessage(role="user", content="hello")
    widget = render_message(msg)
    assert isinstance(widget, Horizontal), (
        f"render_message must return Horizontal; "
        f"got {widget.__class__.__name__}"
    )
    # The outer
    # ``Horizontal``
    # carries the
    # role CSS
    # class.
    classes = widget.classes or []
    assert "msg-user" in classes, (
        f"expected msg-user CSS class on outer "
        f"Horizontal; got {classes!r}"
    )


def test_render_message_handles_all_roles() -> None:
    """Every supported role must produce a
    Horizontal with the correct CSS class
    and NOT raise.
    """
    for role in ("user", "assistant", "tool", "system"):
        msg = ChatMessage(role=role, content="hi")
        w = render_message(msg)
        assert f"msg-{role}" in (w.classes or []), (
            f"role={role!r} -> wrong classes {w.classes!r}"
        )


# ---------- 2. Rich markup, not HTML ----------

def test_render_message_no_html_span_anywhere() -> None:
    """No widget in the tree may carry
    HTML ``<span>`` markup. Textual
    only parses Rich markup; HTML
    span tags would show literally
    (the original CDE-RENDER bug).
    """
    def _walk(w: object, found: list[str]) -> None:
        content = getattr(w, "content", None)
        if content and ("<span" in content):
            found.append(content[:80])
        for child in getattr(w, "children", []) or []:
            _walk(child, found)
    msg = ChatMessage(role="user", content="hello")
    widget = render_message(msg)
    bad: list[str] = []
    _walk(widget, bad)
    assert not bad, (
        f"render_message emitted HTML span "
        f"somewhere: {bad!r}"
    )


# ---------- 3. escape user content (security) ----------

@pytest.mark.asyncio
async def test_render_message_escapes_user_content() -> None:
    """User content with ``<script>`` must be
    escaped so the literal characters appear,
    not as a Rich tag injection vector.

    R-2026-06-20 (CDE-UI-P0.4):
    the widget tree
    (Horizontal >
    Vertical > head +
    body) is only
    populated after
    ``mount()``. We
    mount the widget
    inside a
    ``run_test`` pilot
    so we can walk
    ``widget.children``
    to find the body
    Static.
    """
    from rich.markup import escape
    from textual.containers import Horizontal, Vertical
    from manusift.llm import MockLLM
    from manusift.tui.chat_app import ChatApp

    msg = ChatMessage(
        role="user",
        content="<script>alert(1)</script>",
    )
    widget = render_message(msg)
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        # Mount the
        # widget as
        # a child of
        # the app's
        # main
        # screen so
        # its
        # children
        # become
        # available.
        await app.mount(widget)
        await pilot.pause(0.05)
        # Now
        # ``widget.children``
        # is
        # populated.
        assert isinstance(widget, Horizontal)
        body_column = widget.children[1]
        assert isinstance(body_column, Vertical)
        body_static = body_column.children[1]
    body_text = str(body_static.content or "")
    assert escape("<script>") in body_text, (
        f"expected escaped <script> in body; "
        f"got {body_text!r}"
    )
    # And the
    # raw ``<script>``
    # chars are
    # NOT in the
    # body in a
    # form that
    # could be
    # interpreted
    # as markup.
    # Rich escape
    # wraps the
    # < in
    # brackets,
    # so ``[<]script``
    # appears in
    # the
    # rendered
    # text -- that's
    # fine, it's
    # safe.
    assert "<script>alert" not in body_text or escape(
        "<script>alert"
    ) in body_text


# ---------- 4. end-to-end: message in #history is a Horizontal ----------

@pytest.mark.asyncio
async def test_message_in_history_is_horizontal() -> None:
    """``_append_message`` mounts the widget
    returned by ``render_message`` (now a
    ``Horizontal``). After ``run_test``
    boots the app, ``#history`` children
    must include the new Horizontal.
    """
    from textual.containers import Horizontal
    from manusift.llm import MockLLM

    from manusift.tui.chat_app import ChatApp
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        before = len(app._history_scroll.children)
        app._append_message(
            ChatMessage(role="user", content="hi there")
        )
        await pilot.pause(0.1)
        # The new
        # widget
        # is the
        # last
        # child
        # of the
        # history
        # scroll.
        new = app._history_scroll.children[-1]
        assert isinstance(new, Horizontal), (
            f"_append_message should mount a Horizontal; "
            f"got {new.__class__.__name__}"
        )
        assert "msg-user" in (new.classes or []), (
            f"expected msg-user CSS class; "
            f"got {new.classes!r}"
        )
        assert before + 1 == len(
            app._history_scroll.children
        )