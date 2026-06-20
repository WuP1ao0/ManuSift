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
from manusift.tui.chat_app import ChatApp
from manusift.tui.rendering import render_message


# ---------- Bug #1: role label uses Rich markup, not HTML <span> ----------

@pytest.mark.asyncio
async def test_render_message_uses_rich_markup_not_html_span() -> None:
    """``render_message``
    must NOT
    produce HTML
    ``<span>``
    markup.
    Textual only
    parses Rich
    markup, so
    HTML ``<span>``
    would be
    shown literally.

    R-2026-06-20 (CDE-UI-P0.4):
    the previous
    version asserted
    on ``_render_message``
    returning a
    ``Static`` with
    ``[b]user[/b]``
    in its
    ``content``.
    After the
    CDE-UI-P0.4
    cleanup,
    ``_render_message``
    delegates to
    ``rendering.render_message``
    which returns
    a ``Horizontal``
    (dot + body
    column). The
    contract under
    test is now
    "render_message
    does not emit
    HTML span" --
    asserted by
    walking the
    widget tree for
    ``<span`` or
    ``role-`` (the
    CSS class that
    used to be
    embedded in
    HTML markup).
    """
    from textual.containers import Horizontal
    msg = ChatMessage(role="user", content="hello")
    widget = render_message(msg)
    assert isinstance(widget, Horizontal), (
        f"render_message should return Horizontal; "
        f"got {widget.__class__.__name__}"
    )
    # The outer
    # ``Horizontal``
    # carries the
    # role CSS
    # class via
    # ``classes=``,
    # NOT via an
    # HTML <span>
    # embedded in
    # text content.
    classes = widget.classes or []
    assert "msg-user" in classes, (
        f"expected 'msg-user' CSS class on the outer "
        f"Horizontal; got classes={classes!r}"
    )
    # Walk the
    # whole tree
    # and assert no
    # widget text
    # contains the
    # forbidden
    # HTML markup.
    def _walk(w: Any, found: list[str]) -> None:
        # ``Static.content``
        # is the
        # raw markup
        # string --
        # if we
        # see
        # ``<span``
        # there
        # we have
        # a
        # problem.
        content = getattr(w, "content", None)
        if content and ("<span" in content or "role-" in content):
            found.append(content[:80])
        for child in getattr(w, "children", []) or []:
            _walk(child, found)
    bad: list[str] = []
    _walk(widget, bad)
    assert not bad, (
        f"render_message emitted HTML span markup "
        f"somewhere in the tree: {bad!r}"
    )


# ---------- Bug #2: assistant label is "ManuSift" ----------

def test_role_display_name_maps_assistant_to_manusift() -> None:
    """``_build_head_text("assistant")``
    must return a
    head string
    starting with
    ``ManuSift``
    (the
    user-facing
    identity),
    NOT the
    literal
    role
    string
    ``assistant``.

    R-2026-06-20 (CDE-UI-P0.4):
    this test used
    to call
    ``_role_display_name``
    directly (a
    private
    chat-app
    helper).
    After the
    CDE-UI-P0.4
    cleanup,
    that helper
    is gone --
    the role
    label is
    now produced
    inside
    ``rendering._build_head_text``
    via the
    ``ROLE_DISPLAY_NAME``
    dict.
    This test now
    asserts the
    head text
    directly --
    no widget
    mounting
    needed.
    """
    from manusift.tui.rendering import _build_head_text
    head = _build_head_text("assistant")
    assert head.startswith("ManuSift"), (
        f"expected head to start with ManuSift; got {head!r}"
    )
    # Other
    # roles
    # are
    # unchanged
    # (default
    # pass-through).
    for role in ("user", "system", "tool", "error"):
        h = _build_head_text(role)
        assert h.startswith(role), (
            f"expected {role} role to pass through; got {h!r}"
        )


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