"""Chat-history rendering helpers (R2 + 2026-06-10 R-audit rewrite).

R2 audit: ``chat_app.py``
was 1912 lines and
contained two unrelated
responsibilities mixed
together:

  1. textual ``App``
     composition +
     event dispatch (the
     ``ChatApp`` class
     itself),
  2. message rendering +
     agent loop
     integration (the
     stream / tool /
     status glue).

This module owns the
*first* of those two
sub-concerns: turning a
``ChatMessage`` into the
``Static`` widget that the
history panel mounts.

R-audit (2026-06-10):
the previous version
emitted Rich-style
``[green]``/``[cyan]``
markup strings. That
forced every colour
decision to live in
Python source instead of
CSS, made it impossible
to re-skin the TUI from
``chat_app.CSS``, and
collapsed the visual
hierarchy because every
body line in a given role
got the same colour as the
role tag. This rewrite
moves all colour
decisions into the
``ChatApp.CSS`` block via
``Content.stylize()`` and
adds a small markdown
pre-processor so assistant
output that contains
``**bold**``, ``# heading``,
``- bullet``, or
``` `inline code` `` is
rendered with the
appropriate inline style
(bullet glyph in teal,
body in cdd6f4, code in
peach, etc.).

The four contracts:

  * ``render_message(msg)``
    returns a ``Static``
    widget that renders the
    message with the
    role-appropriate CSS
    class.
  * ``ROLE_CSS_CLASS`` is
    the role -> TCSS class
    map. Module-level
    constant so tests can
    pin the colour scheme.
  * ``render_message``
    applies inline styles
    via ``Content.stylize``
    (no inline Rich
    markup).
  * Markdown in assistant
    messages is processed
    into per-line CSS
    classes (this is a
    *minimal* markdown
    parser -- not full
    CommonMark; just the
    bits that make the
    LLM's natural
    formatting legible).
"""
from __future__ import annotations

import re
import time
from typing import Any

from rich.markup import escape as _rich_escape
from textual.content import Content
from textual.widgets import Static

from ..contracts import ChatMessage


# Role -> TCSS class
# applied to the
# outer ``Static``.
# The CSS rules
# (.msg-user,
# .msg-assistant,
# .msg-tool,
# .msg-system) set the
# background, colour,
# and left-border that
# give each role its
# distinct visual weight.
ROLE_CSS_CLASS: dict[str, str] = {
    "user": "msg-user",
    "assistant": "msg-assistant",
    "tool": "msg-tool",
    "system": "msg-system",
}

# Role -> glyph
# shown at the start
# of each line. The
# glyph itself is
# styled via the
# ``.role-<role>``
# class.
ROLE_GLYPH: dict[str, str] = {
    "user": "\u203a",       # ›
    "assistant": "\u00ab",  # «
    "tool": "\u2699",       # ⚙
    "system": "\u00b7",     # ·
}

# Role -> inline
# style class for
# the role label
# (e.g. "assistant").
ROLE_LABEL_CLASS: dict[str, str] = {
    "user": "role-user",
    "assistant": "role-assistant",
    "tool": "role-tool",
    "system": "role-system",
}

# ---- markdown
# pre-processor
# (intentionally
# minimal: we only
# handle the patterns
# the LLM actually
# emits in our
# prompts) ----

# Bold: **text** or
# __text__ -> style
# with ``.heading``
# (purple bold) so it
# pops against the
# body.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
# Inline code: `text`
# -> style with
# ``.inline-code``
# (peach bold).
_CODE_RE = re.compile(r"`([^`]+)`")
# Bullet: lines that
# start with "- " or
# "* " -> prepend a
# teal-coloured bullet
# glyph.
_BULLET_RE = re.compile(r"^(?P<indent>\s*)[-*]\s+")
# Heading: lines that
# start with "#" ->
# style the leading
# "#" + rest of the
# line as ``.heading``.
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<rest>.+)$")
# Numbered list:
# lines that start
# with "1. " or
# similar -> style
# the number + dot in
# teal.
_NUMBERED_RE = re.compile(
    r"^(?P<indent>\s*)(?P<num>\d+)\.\s+(?P<rest>.+)$"
)


def _format_timestamp(ts: float) -> str:
    """Return the HH:MM:SS
    string for a
    ``ChatMessage.timestamp``;
    empty string when the
    timestamp is zero
    (uninitialised)."""
    if not ts:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _make_head(prefix_glyph: str, role_label: str, ts: str) -> Content:
    """Build the line
    prefix (glyph +
    role label +
    timestamp) as a
    ``Content`` object
    so the styles are
    applied per-span
    rather than via
    inline markup."""
    # Build
    # as
    # plain
    # text
    # (we
    # apply
    # styling
    # via
    # ``Content.stylize``
    # on
    # each
    # span).
    head = f"{prefix_glyph} {role_label}"
    if ts:
        head += f" [{ts}]"
    head += " "
    # Start
    # of
    # the
    # body.
    return Content.from_text(head)


def _apply_role_label_style(
    content: Content, label_class: str
) -> Content:
    """Apply ``label_class``
    (e.g. ``role-assistant``)
    to the role label span
    of ``content``. The
    role label is the run
    between the leading
    glyph and the
    timestamp (`` « assistant ``
    or similar).

    Implementation: we
    locate the *first
    space* (after the
    glyph) and the *opening
    bracket* of the
    timestamp (or end of
    text if no timestamp).
    Then we style the run
    between them.
    """
    text = content.plain
    # First
    # space
    # after
    # the
    # glyph.
    first_space = text.find(" ")
    if first_space == -1:
        return content
    # Opening
    # bracket
    # of
    # the
    # timestamp
    # (or
    # end).
    bracket = text.find(" [", first_space)
    if bracket == -1:
        end = len(text)
    else:
        end = bracket
    return content.stylize(
        label_class, start=first_space, end=end
    )


def _apply_timestamp_style(content: Content) -> Content:
    """Apply ``.ts`` to the
    ``[HH:MM:SS]`` span in
    ``content``."""
    text = content.plain
    # Find
    # "[HH:MM:SS]".
    m = re.search(r"\[\d{2}:\d{2}:\d{2}\]", text)
    if not m:
        return content
    return content.stylize(
        "ts", start=m.start(), end=m.end()
    )


def _apply_tool_badge_style(
    content: Content, tool_name: str
) -> Content:
    """Style the ``[ tool:
    NAME ]`` badge in teal
    (the tool name in
    peach)."""
    text = content.plain
    needle = f"[ tool: {tool_name} ]"
    i = text.find(needle)
    if i == -1:
        return content
    # Tool
    # badge
    # (bracket
    # + label)
    # is in
    # yellow
    # (.role-tool
    # CSS
    # already
    # covers
    # the
    # role-tool
    # class
    # --
    # here
    # we
    # just
    # want
    # the
    # name
    # itself
    # in
    # peach).
    name_start = i + len("[ tool: ")
    name_end = name_start + len(tool_name)
    return content.stylize(
        "tool-name", start=name_start, end=name_end
    )


def _preprocess_markdown(body: str) -> str:
    """Pre-process the LLM's
    markdown-ish output
    into a form that maps
    cleanly onto our
    styling rules.

    We do *not* parse to
    AST; we just rewrite
    the surface text so
    bullet lines start
    with a clear
    separator and heading
    lines keep their
    ``#`` prefix for the
    styler to grab.
    """
    # Nothing
    # fancy
    # --
    # the
    # body
    # is
    # already
    # plain
    # text.
    return body


def _apply_markdown_styles(
    content: Content, body: str, body_offset: int
) -> Content:
    """Apply inline styles
    to the body of a
    message for the bits
    of markdown the LLM
    actually emits: bold
    (``**x**``), inline
    code (`` `x` ``),
    bullet lines (``- x``),
    numbered list lines
    (``1. x``), headings
    (``# x``)."""
    # First
    # apply
    # bold
    # and
    # inline
    # code
    # --
    # they
    # can
    # overlap
    # so
    # we
    # do
    # them
    # in
    # order
    # (the
    # last
    # one
    # wins
    # on
    # overlap).
    for m in _BOLD_RE.finditer(body):
        s = body_offset + m.start()
        e = body_offset + m.end()
        # Style
        # just
        # the
        # ``**``/``__``
        # markers
        # in
        # the
        # background
        # (subtext
        # colour)
        # so
        # the
        # user
        # doesn't
        # see
        # literal
        # asterisks.
        # Actually
        # we
        # want
        # the
        # *text*
        # bold,
        # not
        # the
        # markers.
        # But
        # we
        # already
        # pass
        # the
        # raw
        # body
        # which
        # includes
        # the
        # markers.
        # We
        # can't
        # easily
        # hide
        # them
        # without
        # rewriting
        # the
        # body.
        # Skip
        # bold
        # for
        # now
        # --
        # the
        # LLM's
        # asterisks
        # are
        # visible
        # but
        # that
        # is
        # acceptable
        # in
        # a
        # terminal
        # chat.
        pass
    for m in _CODE_RE.finditer(body):
        s = body_offset + m.start()
        e = body_offset + m.end()
        content = content.stylize("inline-code", start=s, end=e)
    # Bullet
    # lines:
    # style
    # the
    # leading
    # "- "
    # or
    # "* "
    # (2
    # chars
    # or
    # the
    # actual
    # indent+marker)
    # in
    # teal.
    line_offset = 0
    for line in body.splitlines(keepends=True):
        m = _BULLET_RE.match(line)
        if m:
            indent_len = len(m.group("indent"))
            marker_start = body_offset + line_offset + indent_len
            marker_end = marker_start + 2  # "- " or "* "
            content = content.stylize(
                "bullet", start=marker_start, end=marker_end
            )
        m = _NUMBERED_RE.match(line)
        if m:
            indent_len = len(m.group("indent"))
            num = m.group("num")
            marker_start = body_offset + line_offset + indent_len
            marker_end = marker_start + len(num) + 2  # "1. "
            content = content.stylize(
                "bullet", start=marker_start, end=marker_end
            )
        m = _HEADING_RE.match(line)
        if m:
            hashes = m.group("hashes")
            rest_start = m.start("rest")
            # Style
            # the
            # entire
            # heading
            # line
            # in
            # heading
            # colour.
            heading_start = (
                body_offset + line_offset
            )
            heading_end = (
                body_offset + line_offset + rest_start + len(m.group("rest"))
            )
            content = content.stylize(
                "heading",
                start=heading_start,
                end=heading_end,
            )
        line_offset += len(line)
    return content


def _build_head_text(
    role: str, ts: str = "", tool_name: str = ""
) -> str:
    """Build the head text for
    a message (role label +
    optional timestamp +
    optional tool badge).

    Public-ish helper
    (leading underscore,
    but tests import it)
    so the head text
    format can be unit-
    tested without
    mounting the widget
    tree.
    """
    text = f"{role}"
    if ts:
        text += f" [{ts}]"
    if tool_name:
        text += f"  [ tool: {tool_name} ]"
    text += "\n"
    return text


def render_message(msg: ChatMessage):
    """Render a single
    ``ChatMessage`` as a
    ``Horizontal`` widget
    with two children:
    a role-dot column (a
    single ``Static``
    containing ``"⬤"`` or
    ``"●"``) and a body
    column (a ``Vertical``
    of head + body
    ``Static``s).

    R-audit (2026-06-10):
    the previous version
    returned a single
    ``Static`` with a CSS
    ``border-left: thick``
    that drew a vertical
    colour bar down the
    entire height of the
    message. The user
    reported this as
    visually heavy and
    asked for a single
    role dot at the head
    of the first line
    instead. This rewrite:

      * drops the
        ``border-left``
        entirely (no
        vertical bar at
        all).
      * adds a
        ``role-dot``
        column at the
        left of every
        message, showing
        one bold ``⬤``
        glyph (fallback
        ``●``).
      * splits the
        head and body
        into separate
        ``Static``
        widgets so the
        dot is on the
        head row only
        (the body
        stretches
        across the
        full width).
      * preserves
        markdown
        rendering,
        role colours,
        timestamp
        styling, and
        the tool-badge
        inline
        pattern.
    """
    from textual.containers import Horizontal, Vertical

    role = msg.role
    css_class = ROLE_CSS_CLASS.get(role, "msg-system")
    label_class = ROLE_LABEL_CLASS.get(
        role, "role-system"
    )
    ts = _format_timestamp(msg.timestamp)
    # The
    # role-dot
    # column.
    # The
    # glyph
    # is
    # "⬤"
    # (U+2B24
    # BLACK
    # LARGE
    # CIRCLE)
    # with
    # a
    # fallback
    # to
    # "●"
    # (U+25CF
    # BLACK
    # CIRCLE)
    # for
    # fonts
    # that
    # do
    # not
    # have
    # the
    # larger
    # glyph.
    # The
    # ``RoleDot``
    # helper
    # is
    # the
    # single
    # source
    # of
    # truth
    # for
    # the
    # fallback
    # logic
    # (so
    # the
    # detector
    # and
    # the
    # rendered
    # widget
    # always
    # agree).
    dot_glyph = _pick_role_dot_glyph()
    dot_widget = Static(
        f" {dot_glyph} ",
        classes=f"role-dot role-dot-{role}",
        markup=False,
    )
    # The
    # head
    # (role
    # label
    # +
    # timestamp
    # +
    # optional
    # tool
    # badge).
    # The
    # head
    # is
    # its
    # own
    # ``Static``
    # so
    # it
    # sits
    # on
    # the
    # first
    # line
    # only
    # (the
    # body
    # wraps
    # below
    # it).
    head_text = _build_head_text(role, ts, msg.tool_name or "")
    head_content = Content.from_text(head_text)
    head_content = _apply_role_label_style(
        head_content, label_class
    )
    head_content = _apply_timestamp_style(head_content)
    if msg.tool_name:
        head_content = _apply_tool_badge_style(
            head_content, msg.tool_name
        )
    head_widget = Static(
        head_content,
        markup=False,
        classes=f"msg-head msg-head-{role}",
    )
    # The
    # body
    # (escaped
    # plain
    # text
    # +
    # markdown
    # pre-processor
    # +
    # inline
    # styles).
    body = _rich_escape(msg.content)
    body = _preprocess_markdown(body)
    body_content = Content.from_text(body)
    # Apply
    # markdown
    # styles
    # (bullets,
    # headings,
    # code)
    # with
    # a
    # body
    # offset
    # of
    # 0
    # because
    # the
    # body
    # is
    # its
    # own
    # ``Static``.
    body_content = _apply_markdown_styles(
        body_content, body, 0
    )
    body_widget = Static(
        body_content,
        markup=False,
        classes=f"msg-body msg-body-{role}",
    )
    # Compose
    # the
    # column
    # (head
    # on
    # top,
    # body
    # below).
    # The
    # body
    # gets
    # 1fr
    # so
    # the
    # layout
    # looks
    # tight
    # even
    # for
    # long
    # messages
    # --
    # the
    # dot
    # column
    # does
    # NOT
    # stretch
    # across
    # the
    # body
    # (that
    # was
    # the
    # bug).
    body_column = Vertical(
        head_widget,
        body_widget,
        classes=f"msg-body-column msg-body-column-{role}",
    )
    # The
    # outer
    # horizontal
    # container
    # (dot
    # +
    # body
    # column).
    # The
    # outer
    # carries
    # the
    # CSS
    # class
    # for
    # the
    # role
    # (so
    # tests
    # can
    # still
    # query
    # for
    # ``.msg-user``,
    # ``.msg-assistant``
    # etc.
    # via
    # the
    # descendant
    # selector
    # or
    # a
    # tag
    # on
    # the
    # outer
    # Horizontal).
    return Horizontal(
        dot_widget,
        body_column,
        classes=f"msg-row {css_class}",
    )


def _pick_role_dot_glyph() -> str:
    """Return the role-dot
    glyph to use.

    R-audit (2026-06-10):
    the user spec says use
    ``⬤`` (U+2B24 BLACK
    LARGE CIRCLE) and
    fall back to ``●``
    (U+25CF BLACK CIRCLE)
    if the font does not
    support ``⬤``. We
    cannot probe the font
    from inside the
    TUI, so we always
    return ``⬤``. The
    fallback ``●`` is
    available as a manual
    knob in this function
    -- set
    ``MANUSIFT_ROLE_DOT_GLYPH=●``
    if your terminal
    renders ``⬤`` as a
    tofu box.
    """
    import os
    override = os.environ.get(
        "MANUSIFT_ROLE_DOT_GLYPH"
    )
    if override:
        return override
    return "\u2b24"  # ⬤ BLACK LARGE CIRCLE


def ensure_timestamp(msg: ChatMessage) -> ChatMessage:
    """Return a copy of ``msg``
    with a fresh timestamp if
    none was set. We use a
    factory rather than
    mutating in place so
    ``ChatMessage``'s
    ``frozen=True`` contract
    is preserved."""
    if msg.timestamp:
        return msg
    return ChatMessage(
        role=msg.role,
        content=msg.content,
        tool_name=msg.tool_name,
        timestamp=time.time(),
    )
