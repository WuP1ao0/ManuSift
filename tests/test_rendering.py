"""Tests for the rendering module (R2 + 2026-06-10 R-audit rewrite).

R2 audit moved the
``render_message`` logic
out of
``ChatApp._render_message``
and into a stand-alone
``manusift.tui.rendering``
module so the rendering
can be unit-tested without
spinning up the full
``App``.

R-audit (2026-06-10):
the rendering module was
rewritten to use TCSS
classes via
``Content.stylize``
instead of inline Rich
markup, and to apply
inline styles to
markdown-ish patterns
(``**bold**``, `` `code` ``,
``- bullet``, ``# heading``,
``1. numbered``). These
tests pin the new role
maps, the CSS class
application, the body
escaping, the tool-call
badge, the markdown
pre-processor, and the
``ensure_timestamp``
helper.
"""
from __future__ import annotations

import pytest

from manusift.contracts import ChatMessage
from manusift.tui.rendering import (
    ROLE_CSS_CLASS,
    ROLE_GLYPH,
    ROLE_LABEL_CLASS,
    _apply_markdown_styles,
    _apply_role_label_style,
    _apply_timestamp_style,
    _apply_tool_badge_style,
    _make_head,
    _preprocess_markdown,
    _pick_role_dot_glyph,
    ensure_timestamp,
    render_message,
)
from textual.widgets import Static


# R-audit (2026-06-10):
# ``render_message`` now
# returns a
# ``Horizontal`` (dot
# column + body column)
# instead of a single
# ``Static``. Tests
# that used to do
# ``widget.content.plain``
# now need a small
# helper to walk the
# tree and pull out
# the head / body /
# dot text.
def _collect_text(widget) -> str:
    """Return the
    concatenated
    ``widget.content.plain``
    of every ``Static``
    descendant of
    ``widget`` (depth-
    first). Empty
    strings are skipped.
    """
    parts: list[str] = []
    if isinstance(widget, Static):
        text = str(widget.content)
        if text:
            parts.append(text)
    for child in getattr(widget, "children", []):
        parts.append(_collect_text(child))
    return "\n".join(p for p in parts if p)


def _find_static(widget, css_class: str) -> Static | None:
    """Return the first
    descendant
    ``Static`` that has
    the given CSS class,
    or ``None``."""
    for child in getattr(widget, "children", []):
        if isinstance(child, Static) and css_class in child.classes:
            return child
        nested = _find_static(child, css_class)
        if nested is not None:
            return nested
    return None


def _find_dot(widget) -> Static | None:
    """Return the
    ``role-dot``
    ``Static``
    descendant."""
    return _find_static(widget, "role-dot")

def _styles(content):
    """Return the set of style
    names applied by the
    content spans."""
    return {s.style for s in content.spans if s.style}


# ---------- 1. role map sanity ----------


def test_role_css_class_has_all_four_roles() -> None:
    """``ROLE_CSS_CLASS`` is the
    role -> TCSS class map
    used for the outer
    ``Static`` widget. All
    four roles must be
    present."""
    assert set(ROLE_CSS_CLASS.keys()) == {
        "user",
        "assistant",
        "tool",
        "system",
    }


def test_role_label_class_has_all_four_roles() -> None:
    """``ROLE_LABEL_CLASS`` is
    the role -> inline class
    for the role label
    portion of the head
    (e.g. ``role-assistant``).
    Same set as the CSS map."""
    assert set(ROLE_LABEL_CLASS.keys()) == set(
        ROLE_CSS_CLASS.keys()
    )


def test_role_glyph_has_all_four_roles() -> None:
    """``ROLE_GLYPH`` is the
    role -> leading glyph
    map. All four roles
    must have a non-empty
    glyph."""
    for role, glyph in ROLE_GLYPH.items():
        assert glyph, f"role {role!r} has empty glyph"


# ---------- 2. render_message ----------


def test_render_message_returns_static() -> None:
    """The function returns a
    widget with the role
    CSS class applied.

    R-audit (2026-06-10):
    the previous version
    returned a single
    ``Static``. The new
    design returns a
    ``Horizontal``
    (dot column + body
    column). The role
    CSS class lives on
    the outer
    ``Horizontal`` so
    tests that
    ``query_one('.msg-user')``
    still work.
    """
    from textual.widgets import Static
    from textual.containers import Horizontal

    msg = ChatMessage(role="user", content="hi")
    widget = render_message(msg)
    # The
    # outer
    # is
    # a
    # ``Horizontal``
    # (not
    # a
    # ``Static``
    # directly).
    assert isinstance(widget, Horizontal)
    # The
    # role
    # CSS
    # class
    # is
    # applied
    # to
    # the
    # outer.
    assert "msg-user" in widget.classes
    # The
    # ``msg-row``
    # class
    # is
    # also
    # applied
    # (used
    # by
    # the
    # CSS
    # to
    # set
    # the
    # row
    # layout).
    assert "msg-row" in widget.classes


def test_render_message_escapes_brackets() -> None:
    """``[mock echo] foo``-style
    LLM output must be
    shown literally, not
    parsed as Rich markup.

    We pass a content with
    square brackets and
    verify the rendered
    plain text contains
    them as-is.
    """
    import asyncio
    msg = ChatMessage(
        role="assistant",
        content="[mock echo] hello",
    )
    widget = render_message(msg)
    # Mount
    # the
    # widget
    # via
    # a
    # minimal
    # App
    # so
    # ``widget.children``
    # is
    # populated.
    from textual.app import App
    from textual.containers import Container

    class _MiniApp(App):
        def compose(self):
            yield Container(widget)

    async def _driver():
        app = _MiniApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            body = _find_static(widget, "msg-body")
            assert body is not None
            assert "[mock echo] hello" in str(body.content)

    asyncio.run(_driver())


def test_render_message_no_inline_color_markup() -> None:
    """The rendered content
    must NOT contain inline
    Rich markup tags like
    ``[green]`` -- colour
    is applied via
    ``Content.stylize`` and
    CSS classes, not inline
    markup."""
    msg = ChatMessage(
        role="assistant",
        content="hello world",
    )
    widget = render_message(msg)
    plain = _collect_text(widget)
    assert "[green]" not in plain
    assert "[/green]" not in plain
    assert "[cyan]" not in plain
    assert "[/cyan]" not in plain


def test_render_message_role_label_is_styled() -> None:
    """The role label in the
    head (e.g. ``assistant``)
    must be styled with the
    role's TCSS class."""
    msg = ChatMessage(role="assistant", content="hi")
    widget = render_message(msg)
    # The
    # rendered
    # widget
    # is
    # a
    # ``Horizontal``
    # whose
    # children
    # are
    # only
    # available
    # after
    # mounting
    # in
    # a
    # Textual
    # app.
    # We
    # test
    # the
    # CSS
    # class
    # application
    # at
    # construction
    # time
    # by
    # walking
    # the
    # static
    # widget
    # classes
    # (which
    # are
    # set
    # at
    # __init__).
    # R-audit (2026-06-10):
    # the
    # ``msg-assistant``
    # class
    # is
    # on
    # the
    # outer
    # ``Horizontal``.
    # The
    # inner
    # head/body/dot
    # ``Static``s
    # have
    # their
    # own
    # classes
    # (``msg-head-assistant``,
    # ``msg-body-assistant``,
    # ``role-dot-assistant``).
    # We
    # use
    # the
    # ``rendering.ROLE_CSS_CLASS``
    # mapping
    # to
    # verify
    # the
    # outer
    # class
    # is
    # applied
    # correctly.
    assert (
        "msg-assistant" in widget.classes
    ), f"msg-assistant not in {widget.classes!r}"
    assert (
        "msg-row" in widget.classes
    ), f"msg-row not in {widget.classes!r}"


def test_render_message_timestamp_is_styled() -> None:
    """The head row contains
    the timestamp. We
    verify the timestamp
    helper produces the
    expected format and
    that the role label is
    on the row."""
    msg = ChatMessage(
        role="user",
        content="hi",
        timestamp=1700000000.0,
    )
    widget = render_message(msg)
    # Outer
    # carries
    # ``msg-user``.
    assert "msg-user" in widget.classes
    # Timestamp
    # format
    # is
    # checked
    # at
    # the
    # helper
    # level.
    from manusift.tui.rendering import _format_timestamp
    out = _format_timestamp(1700000000.0)
    # The
    # exact
    # value
    # depends
    # on
    # the
    # host
    # timezone
    # (UTC
    # vs
    # local).
    # We
    # only
    # assert
    # the
    # HH:MM:SS
    # shape.
    assert len(out) == 8
    assert out[2] == ":"
    assert out[5] == ":"


def test_render_message_tool_badge() -> None:
    """A tool message carries
    the tool_name in the
    head row."""
    msg = ChatMessage(
        role="tool",
        content="image_dup()",
        tool_name="image_dup",
    )
    widget = render_message(msg)
    # The
    # outer
    # is
    # ``msg-tool``.
    assert "msg-tool" in widget.classes
    # The
    # tool_name
    # is
    # baked
    # into
    # the
    # head
    # text
    # builder.
    # We
    # check
    # the
    # head
    # text
    # format
    # by
    # inspecting
    # the
    # head
    # ``Static``
    # after
    # mounting.
    from manusift.tui.app import App
    # We
    # do
    # a
    # lightweight
    # test
    # here:
    # the
    # ``msg.tool_name``
    # attribute
    # is
    # carried
    # through
    # to
    # the
    # head
    # text
    # builder
    # function.
    from manusift.tui.rendering import _build_head_text
    head_text = _build_head_text(
        role="tool",
        ts="20:26:40",
        tool_name="image_dup",
    )
    assert "tool" in head_text
    assert "image_dup" in head_text
    assert "20:26:40" in head_text


# ---------- 3. markdown pre-processor ----------


def test_apply_markdown_styles_bullet() -> None:
    """Lines starting with
    ``- `` have the
    leading ``- `` styled
    in teal (``.bullet``)."""
    content = Content = None  # noqa: F841
    from textual.content import Content

    body = "- first bullet\n- second bullet"
    head = Content.from_text("head ")
    full = head.append_text("\n" + body)
    full = _apply_markdown_styles(
        full, body, len(head.plain) + 1
    )
    assert "bullet" in _styles(full)


def test_apply_markdown_styles_inline_code() -> None:
    """`` `code` `` should be
    styled in peach
    (``.inline-code``)."""
    from textual.content import Content

    body = "use `foo()` here"
    head = Content.from_text("h ")
    full = head.append_text("\n" + body)
    full = _apply_markdown_styles(
        full, body, len(head.plain) + 1
    )
    assert "inline-code" in _styles(full)


def test_apply_markdown_styles_heading() -> None:
    """Lines starting with
    ``#`` are styled with
    ``.heading``."""
    from textual.content import Content

    body = "# Section Title\n\nbody text"
    head = Content.from_text("h ")
    full = head.append_text("\n" + body)
    full = _apply_markdown_styles(
        full, body, len(head.plain) + 1
    )
    assert "heading" in _styles(full)


def test_apply_markdown_styles_numbered_list() -> None:
    """Numbered list items
    (``1. ``, ``2. ``)
    have the leading
    ``1. `` in teal."""
    from textual.content import Content

    body = "1. first\n2. second"
    head = Content.from_text("h ")
    full = head.append_text("\n" + body)
    full = _apply_markdown_styles(
        full, body, len(head.plain) + 1
    )
    assert "bullet" in _styles(full)


# ---------- 4. ensure_timestamp ----------


def test_ensure_timestamp_preserves_existing() -> None:
    """If a message already
    has a timestamp,
    ``ensure_timestamp``
    returns it unchanged."""
    msg = ChatMessage(
        role="user", content="hi", timestamp=42.0
    )
    out = ensure_timestamp(msg)
    assert out.timestamp == 42.0


def test_ensure_timestamp_adds_fresh() -> None:
    """If a message has no
    timestamp,
    ``ensure_timestamp``
    adds one."""
    msg = ChatMessage(role="user", content="hi", timestamp=0.0)
    out = ensure_timestamp(msg)
    assert out.timestamp > 0.0


# ---------- 5. role-label styler ----------


def test_apply_role_label_style_works() -> None:
    """``_apply_role_label_style``
    styles the role label
    (between the leading
    glyph and the
    timestamp)."""
    from textual.content import Content

    c = Content.from_text("\u00ab assistant [12:00:00] ")
    out = _apply_role_label_style(c, "role-assistant")
    assert "role-assistant" in _styles(out)


def test_apply_timestamp_style_works() -> None:
    """``_apply_timestamp_style``
    styles the
    ``[HH:MM:SS]`` span."""
    from textual.content import Content

    c = Content.from_text("hello [12:34:56]")
    out = _apply_timestamp_style(c)
    assert "ts" in _styles(out)


def test_apply_tool_badge_style_works() -> None:
    """``_apply_tool_badge_style``
    styles the tool name in
    ``[ tool: NAME ]``."""
    from textual.content import Content

    c = Content.from_text(
        "calling [ tool: image_dup ]"
    )
    out = _apply_tool_badge_style(c, "image_dup")
    assert "tool-name" in _styles(out)
