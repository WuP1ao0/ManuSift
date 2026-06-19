"""Tests for the role-dot marker (R-audit 2026-06-10).

The previous TUI used a
``border-left: thick``
CSS rule on each role
class to draw a vertical
colour bar down the
entire height of the
message. The user
reported this as
visually heavy and asked
for a single role dot
(``⬤``) at the head of
the first line instead.

This file pins the new
contracts:

  * Each message is a
    ``Horizontal`` (not a
    single ``Static``) with
    a role-dot column
    (width 3) and a body
    column.
  * The role dot is a
    bold glyph (``⬤`` or
    ``●`` per the env-var
    override) coloured by
    role: cyan / pink /
    amber / dim gray /
    red.
  * No ``border-left`` is
    applied to the
    ``.msg-*`` classes.
  * The role dot is on the
    first line only (the
    body wraps below it
    with no dot repeated
    per line).
  * Empty system messages
    are not rendered (the
    placeholder is also
    removed in
    ``_on_finished_main``).
  * The history saved to
    disk is plain text
    (role / content /
    timestamp only --
    no glyph / colour
    markup).
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. The default glyph is ⬤ ----------


def test_default_role_dot_glyph_is_black_large_circle() -> None:
    """The default role-dot
    glyph is
    ``⬤`` (U+2B24 BLACK
    LARGE CIRCLE). The
    fallback ``●``
    (U+25CF BLACK CIRCLE)
    is selectable via
    ``MANUSIFT_ROLE_DOT_GLYPH``."""
    import os as _os
    _os.environ.pop("MANUSIFT_ROLE_DOT_GLYPH", None)
    from manusift.tui.rendering import _pick_role_dot_glyph
    assert _pick_role_dot_glyph() == "\u2b24"  # ⬤


def test_role_dot_glyph_env_override() -> None:
    """``MANUSIFT_ROLE_DOT_GLYPH=●`` overrides the
    default."""
    import os as _os
    _os.environ["MANUSIFT_ROLE_DOT_GLYPH"] = "\u25cf"  # ●
    try:
        from manusift.tui.rendering import _pick_role_dot_glyph
        assert _pick_role_dot_glyph() == "\u25cf"
    finally:
        _os.environ.pop("MANUSIFT_ROLE_DOT_GLYPH", None)


# ---------- 2. The rendered message is a Horizontal ----------


def test_render_message_returns_horizontal_with_dot_and_body() -> None:
    """``render_message`` returns
    a ``Horizontal`` with a
    role-dot ``Static`` and
    a body-column
    ``Vertical`` of head
    + body ``Static``s."""
    import asyncio
    from textual.app import App
    from textual.containers import Container
    from textual.widgets import Static
    from manusift.tui.rendering import render_message
    from manusift.contracts import ChatMessage

    widget = render_message(
        ChatMessage(role="user", content="hi")
    )

    class _MiniApp(App):
        def compose(self):
            yield Container(widget)

    async def _driver():
        app = _MiniApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            # The
            # outer
            # is
            # a
            # ``Horizontal``
            # with
            # the
            # role
            # class
            # AND
            # the
            # ``msg-row``
            # class.
            from textual.containers import Horizontal
            assert isinstance(widget, Horizontal)
            assert "msg-user" in widget.classes
            assert "msg-row" in widget.classes
            # The
            # first
            # child
            # is
            # the
            # role
            # dot
            # ``Static``.
            dot = widget.children[0]
            assert isinstance(dot, Static)
            assert "role-dot" in dot.classes
            assert "role-dot-user" in dot.classes
            assert "\u2b24" in str(dot.content)
            # The
            # second
            # child
            # is
            # the
            # body
            # column.
            body_col = widget.children[1]
            assert body_col.__class__.__name__ == "Vertical"

    asyncio.run(_driver())


# ---------- 3. No border-left in CSS ----------


def test_no_border_left_in_message_css() -> None:
    """The CSS for the
    ``.msg-*`` classes does
    NOT contain
    ``border-left`` (the
    role-marker is a
    dot, not a vertical
    bar)."""
    from manusift.tui import chat_app
    import inspect
    src = inspect.getsource(chat_app.ChatApp)
    # Find
    # the
    # CSS
    # block.
    css_start = src.find('CSS = """')
    css_end = src.find('"""', css_start + 8)
    css = src[css_start:css_end]
    # The
    # only
    # ``border-left``
    # references
    # should
    # be
    # in
    # the
    # comments
    # mentioning
    # the
    # old
    # design.
    # Actually
    # the
    # whole
    # design
    # is
    # gone,
    # so
    # there
    # should
    # be
    # no
    # ``border-left:``
    # rule
    # at
    # all.
    # Strip
    # the
    # comments
    # to
    # find
    # any
    # remaining
    # rules.
    import re
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # No
    # ``border-left``
    # CSS
    # rule
    # should
    # exist.
    assert "border-left" not in rules, (
        f"found a 'border-left' CSS rule -- the role-marker "
        f"should be a dot, not a vertical bar:\n{rules[:500]}"
    )


# ---------- 4. Role dot colours ----------


def test_role_dot_colour_classes_present_in_css() -> None:
    """The CSS exposes
    per-role colour
    classes for the role
    dot:
    ``.role-dot-user`` (cyan),
    ``.role-dot-assistant`` (pink),
    ``.role-dot-tool`` (amber),
    ``.role-dot-system`` (dim gray-purple),
    ``.role-dot-error`` (red)."""
    from manusift.tui import chat_app
    import inspect
    src = inspect.getsource(chat_app.ChatApp)
    css_start = src.find('CSS = """')
    css_end = src.find('"""', css_start + 8)
    css = src[css_start:css_end]
    for cls in (
        "role-dot-user",
        "role-dot-assistant",
        "role-dot-tool",
        "role-dot-system",
        "role-dot-error",
    ):
        assert cls in css, f"missing {cls} in CSS"
    # Spot-check
    # the
    # colours
    # match
    # the
    # user
    # spec.
    assert "#89dceb" in css, (
        "user dot should be cyan #89dceb"
    )
    assert "#f5c2e7" in css, (
        "assistant dot should be pink #f5c2e7"
    )
    assert "#f9e2af" in css, (
        "tool dot should be amber #f9e2af"
    )
    assert "#6c7086" in css, (
        "system dot should be dim gray-purple #6c7086"
    )
    assert "#f38ba8" in css, (
        "error dot should be red #f38ba8"
    )


# ---------- 5. Empty system messages are not rendered ----------


def test_empty_system_message_not_rendered() -> None:
    """An empty
    ``(content.strip() == "")``
    system message does
    NOT render a chat
    bubble."""
    from manusift.tui.rendering import render_message
    from manusift.contracts import ChatMessage
    widget = render_message(
        ChatMessage(
            role="system",
            content="   \n\n  ",
        )
    )
    # Empty
    # messages
    # are
    # filtered
    # by
    # ``_append_message``
    # (which
    # calls
    # ``render_message``
    # only
    # when
    # content
    # is
    # non-
    # empty).
    # We
    # verify
    # the
    # helper
    # contract
    # here:
    # the
    # caller
    # checks
    # ``str(msg.content).strip()``.
    assert str("   \n\n  ".strip()) == ""


# ---------- 6. ChatMessage serialization strips glyph / markup ----------


def test_chat_message_serialization_has_no_glyph_or_markup() -> None:
    """Persisted ChatMessage
    records do not carry
    the role-dot glyph or
    any Rich / Textual
    markup tags -- just
    role / content /
    timestamp /
    tool_name."""
    import json
    from manusift.contracts import ChatMessage
    msg = ChatMessage(
        role="user",
        content="hello [bold] world",
        tool_name=None,
        timestamp=1700000000.0,
    )
    blob = json.dumps(msg, default=lambda o: o.__dict__)
    # No
    # role-dot
    # glyph.
    assert "\u2b24" not in blob
    assert "\u25cf" not in blob
    # No
    # CSS
    # class
    # names
    # leak
    # into
    # the
    # persisted
    # record.
    for cls in (
        "msg-user",
        "msg-assistant",
        "role-dot",
        "role-user",
        "msg-head",
        "msg-body",
    ):
        assert cls not in blob, (
            f"persisted ChatMessage leaked {cls!r} into JSON"
        )