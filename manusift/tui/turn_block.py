"""Tool-trace + debug-drawer widgets
(R-audit 2026-06-11).

The user reported that the
TUI's chat log mixed
user / assistant text /
tool calls / tool results
/ system debug into one
flat history, making it
"eye-stabbing" and
impossible to read.

This module implements
the three-layer structure
the user asked for:

  1. **Chat** -- the
     ``#history`` column,
     showing ONLY the
     user's input + the
     assistant's reply
     (Markdown-rendered).
  2. **ToolTrace** -- a
     ``Collapsible`` per
     assistant turn, with
     a one-line summary
     (``tools N calls ...
     ok ... skipped ...``)
     by default, and an
     expanded list of
     one-row-per-tool
     entries when the
     user opens it.
  3. **DebugDrawer** -- a
     hidden ``#debug-drawer``
     column that the user
     opens with ``d``. It
     holds the raw JSON
     of every tool call /
     result / system event
     / final assistant
     text source. Default
     hidden.

## Design

Each turn is a sequence
of:

  * 1 user message
  * N tool calls (0..N)
  * 1 final assistant
    message

The ``ToolTraceBlock`` is
mounted once per turn, right
AFTER the user message
and BEFORE the final
assistant message. As
tools fire during the
turn, the block's summary
is updated. When the
turn ends (assistant
text arrives), the block
is "sealed" -- the
summary is final, the
expanded list is
immutable.

## Repeat-error dedup

The user explicitly asked
for this in the spec:
"multiple ``PDF not
found for trace_id=...```
should be merged into
``14 tools skipped: PDF
not found for trace_id=...``".

We dedupe by
``(tool_name, error)``
key. The summary says
``N tools skipped:
<error>`` (the first
occurrence's error
text), and the count is
the dedup count.

## Long-path shortening

The user explicitly asked
for "long paths shown as
relative path or
basename; hover/expand
to see the full path".
We replace any Windows
or Unix absolute path in
the summary line with
``.../<basename>``. The
full path is preserved
in the DebugDrawer.

The regex:
``re.sub(r\"(?:[A-Za-z]:)?[/\\\\][^\\\\/]+[/\\\\]([^/\\\\]+)$\", ...)``
strips a path down to
``.../<basename>``.

## Markdown rendering

The assistant's final
reply is rendered through
the existing
``render_message``
Markdown pre-processor
(``manusift.tui.rendering``).
The user's spec says
"don't show the raw
``**`` / ``##``". The
existing renderer already
handles ``**bold**``,
``## heading``,
``- bullet``, etc. via
``Content.stylize`` and
CSS classes. We reuse it
verbatim.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

# R-2026-06-14: i18n for user-facing TUI strings.
from .i18n import t as _t

# ============================================================
# R-2026-06-19 (P2-D4,
# ToolCallCard
# markdown render):
# when a tool
# result body
# looks like
# markdown
# (starts with
# `## ` /
# `**bold**` /
# `- item` /
# `1. item` /
# ` ```code``` `),
# the
# ``ToolCallCard``
# renders it via
# Rich's
# ``Markdown``
# parser instead
# of the
# plain-Text
# ``key: value``
# layout.  The
# benefit:
# multi-line
# findings /
# evidence
# blocks from
# detectors like
# ``benford`` /
# ``chart_extract``
# / ``panel_dup``
# are now
# rendered with
# bold / italic
# / list bullets
# preserved
# instead of
# collapsing to
# one long
# undifferentiated
# blob.
# ============================================================

# Heuristic
# threshold:
# the body is
# considered
# "markdown"
# when it has at
# least 2 lines
# AND at least 1
# of the
# following
# signals
# (header / bold
# / list / code
# fence / link).
# We require
# only 1 signal
# (not 2)
# because the
# 40-char +
# multi-line
# guards are
# already a
# strong filter
# (a 40-char
# single-signal
# plain-text
# body is
# extremely
# rare in
# tool output).
# R-2026-06-19
# (P2-D4)
# version
# 2: the
# original
# 2-signal
# threshold was
# too strict --
# detector
# evidence
# blocks like
# "- **severity**:
# high\n- **detector**:
# benford"
# have only the
# bold signal
# + the list
# signal and
# were being
# classified as
# plain text.

# (still 1+)
# (still 1+)

_MD_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Headers:
    # `## foo` or
    # `# foo`.
    re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE),
    # Bold:
    # `**foo**` or
    # `__foo__`.
    re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__"),
    # Italic:
    # `*foo*` or
    # `_foo_` (not
    # at word
    # boundary so
    # it doesn't
    # match `2*3`).
    re.compile(r"(?<!\*)\*[^*\n]+\*(?!\*)|(?<![A-Za-z0-9_])_[^_\n]+_(?![A-Za-z0-9_])"),
    # Unordered
    # list:
    # `- foo`,
    # `* foo`,
    # `+ foo`.
    re.compile(r"^\s{0,3}[-*+]\s+\S", re.MULTILINE),
    # Ordered
    # list:
    # `1. foo`,
    # `2) bar`.
    re.compile(r"^\s{0,3}\d+[.)]\s+\S", re.MULTILINE),
    # Code
    # fence:
    # ```` ``` ````
    # or
    # `~~~`.
    re.compile(r"^\s{0,3}(```|~~~)", re.MULTILINE),
    # Inline
    # code:
    # `` `foo` ``.
    re.compile(r"`[^`\n]{1,80}`"),
    # Link:
    # `[text](url)`.
    re.compile(r"\[[^\]\n]{1,80}\]\([^)\n]{1,200}\)"),
)


def looks_like_markdown(s: str) -> bool:
    """Return True if ``s`` should be rendered as markdown.

    R-2026-06-19 (P2-D4):
    the heuristic
    is intentionally
    conservative --
    the cost of
    *false-positive*
    (rendering
    plain text as
    markdown,
    producing
    garbage output)
    is higher than
    the cost of
    *false-negative*
    (rendering
    markdown as
    plain text,
    losing
    formatting).
    We require:
      1. the string
         is at
         least 30
         chars
         long
         (so short
         tool
         summaries
         like
         ``"ok"`` /
         ``"5 findings"``
         are NOT
         rendered
         as markdown)
      2. has at
         least 2
         lines
         (so
         single-line
         bodies
         like
         ``"trace_id = abc123"``
         are not
         misclassified)
      3. at least 1
         of the
         7 signal
         patterns
         above
         match
         somewhere
         in the
         body.
    """
    if not isinstance(s, str):
        return False
    if len(s) < 30:
        return False
    if s.count("\n") < 1:
        # Need at least 2 lines (one is
        # the implicit "" before the
        # first \n, but for our purposes
        # we need at least 1 explicit
        # \n).
        return False
    hits = sum(
        1 for pat in _MD_SIGNAL_PATTERNS if pat.search(s)
    )
    return hits >= 1


# ============================================================
# 1. Data classes for the tool trace
# ============================================================


# Status enum for one tool entry.
TOOL_OK = "ok"
TOOL_SKIPPED = "skipped"  # error: the tool returned a structured "skipped" / not-found
TOOL_ERROR = "error"  # error: the tool raised / returned a non-2xx
TOOL_RUNNING = "running"


@dataclass(frozen=True)
class ToolEntry:
    """One tool call +
    result within a
    ``ToolTraceBlock``.

    ``status`` is one of
    ``TOOL_OK`` /
    ``TOOL_SKIPPED`` /
    ``TOOL_ERROR``.
    ``duration_ms`` is the
    wall-clock time the
    tool took (None if
    the tool did not
    finish).
    ``summary`` is the
    one-line human-readable
    text shown in the
    expanded view (e.g.
    ``"310ms no high-risk
    duplicate"`` or
    ``"PDF not found for
    trace_id=...``).
    ``raw_input`` /
    ``raw_output`` are the
    raw JSON the user sees
    in the DebugDrawer.
    """

    tool_id: str
    tool_name: str
    status: str = TOOL_OK
    duration_ms: int | None = None
    summary: str = ""
    raw_input: dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    error: str = ""
    # R-2026-06-14: extra BashTool
    # envelope fields. Optional --
    # present only for bash tool
    # calls. The TUI's tool-trace
    # block displays them when
    # they are non-empty.
    cwd: str = ""
    stderr: str = ""
    shell_mode: str = ""
    returncode: int | None = None
    # R-2026-06-19 (P2-B1):
    # sub-agent depth.  ``0`` is
    # the parent agent (default);
    # ``1`` is a sub-agent one
    # level deep; etc.  The
    # ``ToolCallCard`` header
    # renders ``›`` × level as
    # a visual indent so the
    # user can see at a glance
    # which tool calls are
    # nested inside a sub-agent
    # vs. the top-level
    # conversation.  Forwarder
    # wires ``level`` from the
    # ``sub_meta`` field on the
    # event (see
    # ``task_subagent_forwarder.py``).
    # The default ``0`` keeps
    # the old behavior for
    # every existing call site.
    level: int = 0


# ============================================================
# 2. Long-path shortener
# ============================================================


_ABS_PATH_RE = re.compile(
    r"(?:[A-Za-z]:)?[/\\][^\\/]+(?:[/\\][^\\/]+)*[/\\]"
    r"([^\\/]+?)(?=[^\w/.-]|$)"
)


def _shorten_path(text: str) -> str:
    """Replace any
    Windows or Unix
    absolute path in
    ``text`` with
    ``.../<basename>``.

    The match is greedy on
    the path-separator
    classes (``/`` or
    ``\\``) and the
    basename capture is
    the trailing
    non-separator
    segment. ``C:\\Users
    \\alice\\paper.pdf`` ->
    ``.../paper.pdf``.

    The function is pure
    and idempotent: calling
    it twice on the same
    string gives the same
    result. Calls on a
    string that contains
    no absolute paths are
    a no-op.
    """
    return _ABS_PATH_RE.sub(r".../\1", text)


# ============================================================
# 3. ToolTraceBlock widget
# ============================================================


class ToolTraceBlock(Static):
    """A one-block-per-turn
    ``Collapsible`` (we
    use ``Static`` with a
    custom render to
    keep tight control
    over the layout).

    The block holds:
      * a summary line
        ``tools N calls · A ok · B skipped · C error``
      * an expanded list of
        per-tool entries,
        one line each.

    As tools fire during
    the turn the block is
    *updated in place*
    (the Runner calls
    ``update_summary()`` /
    ``add_entry()``). When
    the assistant text
    arrives the block is
    *sealed* (no more
    entries can be
    added).

    The widget's CSS class
    is ``tool-trace``. The
    block is dark-grey by
    default; the entries
    are dimmer and the
    status icons are
    coloured (green for
    ok, amber for
    skipped, red for
    error).
    """

    DEFAULT_CSS: ClassVar[str] = """
    ToolTraceBlock {
        height: auto;
        padding: 0 1 0 3;  /* left indent aligns with body */
        margin: 0 0 1 0;
        background: #181825;
        color: #a6adc8;
    }
    .tool-trace-summary {
        color: #a6adc8;
        text-style: dim;
    }
    .tool-trace-summary-running {
        color: #f9e2af;
        text-style: bold;
    }
    .tool-trace-entry {
        height: 1;
        color: #a6adc8;
    }
    .tool-trace-entry-ok {
        color: #a6e3a1;
    }
    .tool-trace-entry-skipped {
        color: #f9e2af;
    }
    .tool-trace-entry-error {
        color: #f38ba8;
    }
    .tool-trace-entry-icon-ok {
        color: #a6e3a1;
    }
    .tool-trace-entry-icon-skipped {
        color: #f9e2af;
    }
    .tool-trace-entry-icon-error {
        color: #f38ba8;
    }
    """

    def __init__(
        self,
        *children: Any,
        collapsed: bool = True,
        classes: str | None = None,
        **kwargs: Any,
    ) -> None:
        # The
        # block
        # is
        # a
        # plain
        # Static
        # (we
        # own
        # the
        # layout
        # ourselves
        # so
        # we
        # can
        # keep
        # the
        # rendering
        # pipeline
        # simple).
        super().__init__(*children, classes=classes or "tool-trace")
        self._entries: list[ToolEntry] = []
        self._collapsed: bool = collapsed
        self._sealed: bool = False
        # Initial
        # render
        # is
        # the
        # empty
        # summary.
        self._rerender()

    # --- public API ---

    def add_entry(self, entry: ToolEntry) -> None:
        """Append a tool entry
        to the block. If the
        block is already
        sealed (i.e. the
        assistant text
        arrived), the call is
        a no-op (and logs a
        warning)."""
        if self._sealed:
            return
        self._entries.append(entry)
        self._rerender()

    def update_summary(self) -> None:
        """Re-render the
        summary line. Useful
        for the Runner to
        call after each
        ``add_entry()`` so
        the count is
        live."""
        self._rerender()

    def seal(self) -> None:
        """Mark the block as
        final. After seal(),
        ``add_entry()`` is a
        no-op.

        R-2026-06-20 (CDE-UI-EMPTY):
        if the
        turn
        used
        zero
        tools,
        hide
        the
        entire
        block
        (``self.display = False``).
        The
        user
        sees
        a
        clean
        "no
        tools
        were
        called
        this
        turn"
        experience
        (the
        block
        collapses
        to
        zero
        rows
        of
        height)
        instead
        of
        a
        stale
        "tools
        0
        calls"
        stripe
        that
        looks
        like
        an
        error.

        If
        the
        turn
        DID
        use
        tools,
        we
        keep
        the
        block
        visible
        so the
        user
        can
        see
        the
        per-tool
        counts
        (ok /
        skipped
        /
        error).
        """
        if self._sealed:
            return
        self._sealed = True
        # R-2026-06-20 (CDE-UI-EMPTY):
        # hide the block entirely when the turn
        # did not call any tool. ``Static.display``
        # is a textual property that the engine
        # respects at next paint. ``mount`` /
        # ``unmount`` would also work but display
        # is cheaper (no tree surgery).
        if len(self._entries) == 0:
            self.display = False
        # If
        # we
        # were
        # showing
        # "running",
        # collapse
        # to
        # the
        # final
        # summary
        # now.
        self._rerender()

    def set_collapsed(self, collapsed: bool) -> None:
        """Expand or collapse
        the block. The
        default is
        collapsed."""
        self._collapsed = collapsed
        self._rerender()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    @property
    def entries(self) -> list[ToolEntry]:
        return list(self._entries)

    @property
    def is_sealed(self) -> bool:
        return self._sealed

    # --- internal ---

    def _counts(self) -> dict[str, int]:
        out = {
            TOOL_OK: 0,
            TOOL_SKIPPED: 0,
            TOOL_ERROR: 0,
        }
        for e in self._entries:
            out[e.status] = out.get(e.status, 0) + 1
        return out

    def _rerender(self) -> None:
        """Build the
        ``Text`` for the
        block and call
        ``update()`` on the
        parent Static.

        R-audit (2026-06-11):
        ``Static.update()`` requires an active textual app. In
        unit tests that drive the block without an app
        (``tests/test_chat_layering.py`` inspects the
        summary / expanded text via
        ``_summary_line()`` / ``_expanded_block()``
        directly) we don't actually need to call
        ``update()``. We guard with
        ``is_mounted`` and skip the update path if
        the block is not yet attached to a tree. The
        next mount + paint cycle will call
        ``render()`` from scratch and pick up the
        correct text.
        """
        if self._collapsed:
            text = self._summary_line()
        else:
            text = self._expanded_block()
        if not self.is_mounted:
            # Skip
            # the
            # update
            # --
            # the
            # next
            # mount
            # will
            # render
            # from
            # the
            # current
            # state.
            return
        self.update(text)

    def _summary_line(self) -> Text:
        """Build the one-line
        summary shown
        when the
        block is
        collapsed.

        R-2026-06-20 (CDE-UI-EMPTY):
        if the
        turn
        used
        zero
        tools
        AND
        the
        block
        is
        already
        sealed
        (i.e.
        the
        LLM
        answered
        without
        calling
        anything),
        return
        an
        empty
        ``Text``.
        The
        caller
        (``_rerender``)
        still
        calls
        ``self.update(...)``
        so
        the
        widget
        re-paints,
        but
        the
        background
        CSS
        and
        the
        one-line
        height
        of
        the
        block
        still
        produce
        a
        visible
        stripe.
        The
        block
        hides
        itself
        via
        ``self.display = False``
        in
        ``seal()``
        (see
        below)
        so
        the
        stripe
        disappears
        entirely
        for
        tool-less
        turns.
        """
        n = len(self._entries)
        counts = self._counts()
        if n == 0 and self._sealed:
            # Sealed
            # and
            # tool-less:
            # the
            # block
            # was
            # hidden
            # by
            # ``seal()``
            # (display
            # =
            # False).
            # Return
            # an
            # empty
            # ``Text``
            # for
            # safety.
            return Text("")
        if n == 0 and not self._sealed:
            t = Text(_t("tools_thinking"), style="dim")
            t.stylize("yellow")
            return t
        # Compose
        # the summary line. The English layout is
        # "tools N calls · A ok · B skipped · C error";
        # the Chinese layout is "工具 N 次调用 ·
        # 成功 A · 跳过 B · 错误 C". Both are
        # driven by the same i18n keys.
        parts: list[tuple[str, str]] = []
        # R-2026-06-14: the "tools N call{s}" key takes
        # ``n`` and ``s`` (the literal plural marker).
        # English: "s" is "" or "s". Chinese: always ""
        # (Chinese has no plural inflection), so the
        # Chinese template omits the ``s`` slot.
        plural_s = "s" if n != 1 else ""
        parts.append(
            (_t("tools_summary", n=n, s=plural_s), "dim")
        )
        # R-audit (2026-06-14):
        # include the top
        # 3 tool names in
        # the summary line
        # so the user can
        # see at a glance
        # which tools were
        # called, not just
        # a raw "3 ok" count.
        # The names are
        # derived from the
        # entries (already
        # in chronological
        # order) and the
        # counts are
        # collapsed so a
        # tool called 5
        # times shows as
        # "ingest_from_path
        # ×5" instead of
        # duplicating the
        # name 5 times.
        _name_counts: dict[str, int] = {}
        for e in self._entries:
            _name_counts[e.tool_name] = (
                _name_counts.get(e.tool_name, 0) + 1
            )
        # Stable order: first
        # appearance in
        # the entries list.
        _seen_order: list[str] = []
        for e in self._entries:
            if e.tool_name not in _seen_order:
                _seen_order.append(e.tool_name)
        _top = _seen_order[:3]
        if _top:
            _pieces: list[str] = []
            for nm in _top:
                c = _name_counts[nm]
                if c > 1:
                    _pieces.append(f"{nm} ×{c}")
                else:
                    _pieces.append(nm)
            parts.append(("  " + ", ".join(_pieces), "dim"))
        if counts[TOOL_OK]:
            parts.append(
                (_t("tools_ok", n=counts[TOOL_OK]), "green")
            )
        if counts[TOOL_SKIPPED]:
            parts.append(
                (
                    _t("tools_skipped", n=counts[TOOL_SKIPPED]),
                    "yellow",
                )
            )
        if counts[TOOL_ERROR]:
            parts.append(
                (
                    _t("tools_error", n=counts[TOOL_ERROR]),
                    "red",
                )
            )
        if not self._sealed:
            parts.append((_t("tools_running"), "yellow"))
        # If
        # the
        # block
        # was
        # sealed
        # but
        # all
        # tools
        # are
        # "ok",
        # drop
        # the
        # "ok"
        # count
        # noise
        # --
        # show
        # "tools
        # 31
        # calls
        # ·
        # 0
        # skipped
        # ·
        # 0
        # error"
        # (the
        # user's
        # exact
        # spec
        # example).
        line = Text()
        for s, style in parts:
            line.append(s, style=style)
        return line

    def _expanded_block(self) -> Text:
        out = Text()
        # First
        # line
        # is
        # the
        # summary.
        out.append_text(self._summary_line())
        out.append("\n")
        # Then
        # one
        # row
        # per
        # tool.
        for e in self._entries:
            out.append_text(self._format_entry(e))
            out.append("\n")
            # R-2026-06-14: when the
            # entry has the
            # BashTool-specific
            # fields (cwd, stderr,
            # shell_mode, returncode)
            # populated, append
            # the multi-line detail
            # block. The function is
            # a no-op when those
            # fields are empty.
            detail = format_entry_detail(e)
            if detail:
                # Indent the detail
                # block one level so
                # it nests under the
                # entry's summary line.
                indented = "\n".join(
                    "    " + line
                    for line in detail.split("\n")
                )
                out.append_text(
                    Text.from_markup(
                        f"[dim]{indented}[/dim]"
                    )
                )
                out.append("\n")
        return out

    def _format_entry(self, e: ToolEntry) -> Text:
        # "✓ image_dup 310ms no high-risk duplicate"
        # "⚠ pdf_metadata skipped: PDF not found"
        # "✖ web_search 2400ms timeout"
        out = Text("    ")
        if e.status == TOOL_OK:
            icon, color = "✓ ", "green"
        elif e.status == TOOL_SKIPPED:
            icon, color = "⚠ ", "yellow"
        else:
            icon, color = "✖ ", "red"
        out.append(icon, style=color)
        out.append(e.tool_name, style="bold " + color)
        if e.duration_ms is not None:
            out.append(f" {e.duration_ms}ms", style="dim")
        if e.summary:
            # Shorten
            # any
            # path
            # in
            # the
            # summary.
            short = _shorten_path(e.summary)
            out.append(f"  {short}", style="dim")
        return out


# ============================================================
# 3a. ToolCallCard (Claude-Code-like action block)
# ============================================================
#
# R-2026-06-16 (Phase 4 +
# tool-call-card):
# the user spec says
# the
# ``ToolTraceBlock``
# (one block per
# turn, collapsed
# by default) is
# invisible for
# power users: they
# cannot see the
# call-by-call
# transcript of
# what the agent
# did. We add a
# per-call
# ``ToolCallCard``
# that is mounted
# directly in
# ``#history`` (NOT
# inside the
# per-turn trace
# block) so every
# call is its own
# permanent,
# auto-expanded
# card in the
# chat scrollback.
#
# Render (Claude
# Code style):
#
#     ● read_file [16:22:40]  ✓ ok  (45ms)
#         path: C:\...\Table_S1.xlsx
#         → 5 rows, 8 columns
#
#     ● image_dup [16:22:46]  ✓ ok  (310ms)
#         → no high-risk duplicate
#
#     ● bash [16:22:50]  ✖ error  (2.4s)
#         command: python --version
#         error: exit 1


class ToolCallCard(Static):
    """A persistent,
    always-expanded
    card for a single
    tool call.

    R-2026-06-16
    (Phase 4 +
    tool-call-card):
    unlike the
    per-turn
    ``ToolTraceBlock``
    (which is
    collapsed after
    5+ turns to
    save screen
    real-estate),
    this widget is
    mounted
    directly in the
    chat scrollback
    so the call is
    visible forever.
    The card never
    auto-collapses.
    """

    DEFAULT_CSS: ClassVar[str] = """
    ToolCallCard {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1 0 1;
        background: #181825;
        color: #cdd6f4;
        border-left: thick #313244;
    }
    ToolCallCard.tool-call-card-running {
        border-left: thick #f9e2af;
    }
    ToolCallCard.tool-call-card-ok {
        border-left: thick #a6e3a1;
    }
    ToolCallCard.tool-call-card-skipped {
        border-left: thick #f9e2af;
    }
    ToolCallCard.tool-call-card-error {
        border-left: thick #f38ba8;
    }
    .tool-call-card-header {
        text-style: bold;
    }
    .tool-call-card-key {
        color: #a6adc8;
    }
    .tool-call-card-value {
        color: #cdd6f4;
    }
    .tool-call-card-arrow {
        color: #89b4fa;
    }
    .tool-call-card-error-msg {
        color: #f38ba8;
    }
    """

    def __init__(
        self,
        entry: "ToolEntry",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._entry: ToolEntry = entry
        self._update_css_for_status()
        self._rerender()

    def set_entry(self, entry: "ToolEntry") -> None:
        """Replace the
        displayed entry
        and re-render.

        Used when a
        call is first
        inserted with
        ``status=running``
        and then
        upgraded to
        ``ok`` /
        ``skipped`` /
        ``error`` once
        the result
        comes back. The
        card stays in
        place (no
        scroll jump)
        because the
        same widget is
        being updated.
        """
        self._entry = entry
        self._update_css_for_status()
        self._rerender()

    def _update_css_for_status(self) -> None:
        # Add a
        # status-
        # based CSS
        # class so
        # the
        # left
        # border
        # color
        # changes
        # from
        # amber
        # (running)
        # to
        # green
        # (ok) /
        # amber
        # (skipped)
        # / red
        # (error).
        st = self._entry.status
        for cls in (
            "tool-call-card-running",
            "tool-call-card-ok",
            "tool-call-card-skipped",
            "tool-call-card-error",
        ):
            try:
                self.remove_class(cls)
            except Exception:  # noqa: BLE001
                pass
        if st == "ok":
            self.add_class("tool-call-card-ok")
        elif st == "skipped":
            self.add_class("tool-call-card-skipped")
        elif st == "error":
            self.add_class("tool-call-card-error")
        else:
            self.add_class("tool-call-card-running")

    def _rerender(self) -> None:
        # We do
        # not
        # care
        # about
        # the
        # is_mounted
        # guard
        # here
        # because
        # the
        # card
        # is
        # always
        # mounted
        # in
        # ``#history``
        # before
        # the
        # first
        # render.
        # We
        # still
        # check
        # just
        # in
        # case
        # the
        # card
        # is
        # being
        # used
        # in
        # a
        # test
        # harness
        # without
        # an
        # app.
        text = self._build()
        if self.is_mounted:
            self.update(text)

    def _build(self) -> Text:
        e = self._entry
        out = Text()
        # ----
        # Header
        # line:
        # ●
        # tool
        # name
        # [HH:MM:SS]
        # status
        # icon
        # status
        # label
        # (duration)
        # ----
        if e.status == "ok":
            icon, icon_color = "✓", "green"
        elif e.status == "skipped":
            icon, icon_color = "⚠", "yellow"
        elif e.status == "error":
            icon, icon_color = "✖", "red"
        else:
            icon, icon_color = "•", "yellow"
        # R-2026-06-19 (P2-B1):
        # sub-agent indent.
        # When the entry's
        # ``level > 0``
        # (a sub-agent
        # tool call), render
        # ``›`` × level as
        # a visual indent
        # BEFORE the bullet.
        # ``level=0`` (parent)
        # is unchanged so
        # the existing
        # chat scrollback
        # looks the same.
        if e.level > 0:
            indent = "› " * e.level
            out.append(
                indent,
                style="dim #89b4fa",
            )
        out.append("● ", style="bold")
        out.append(
            e.tool_name,
            style="bold",
        )
        # Time
        # stamp
        # (HH:MM:SS
        # from
        # ``tool_id``).
        # The
        # Runner
        # populates
        # ``tool_id``
        # with a
        # deterministic
        # hex; if
        # that's
        # not
        # available
        # we fall
        # back
        # to
        # ``datetime.now()``.
        time_str = self._format_time()
        if time_str:
            out.append(
                " [" + time_str + "]",
                style="dim",
            )
        out.append("  ")
        out.append(icon, style=icon_color)
        out.append(" ")
        out.append(
            self._status_label(e.status),
            style=icon_color,
        )
        if e.duration_ms is not None:
            out.append(
                "  (" + _fmt_duration(e.duration_ms) + ")",
                style="dim",
            )
        out.append("\n")
        # ----
        # Body
        # lines:
        # key:
        # value
        # ----
        body = self._build_body(e)
        for line in body:
            out.append("    ")
            out.append_text(line)
            out.append("\n")
        return out

    def _format_time(self) -> str:
        """Extract
        ``HH:MM:SS``
        from the entry
        timestamp.

        R-2026-06-16
        (Phase 4 +
        tool-call-card):
        ``ToolEntry`` does
        NOT have a
        timestamp
        field (the
        older
        ``ToolTraceBlock``
        only cared
        about
        duration).
        We accept
        the timestamp
        in two ways:
          * via
            ``raw_input['_started_at']``
            (Unix
            seconds)
          * via
            ``tool_id``
            (if
            formatted
            ``HH-MM-SS-<hex>``)

        If neither is
        present we
        fall back to
        ``--:--:--``
        so the header
        layout stays
        consistent.
        """
        import datetime as _dt
        # Path
        # 1:
        # ``raw_input['_started_at']``
        ts = (
            (e_raw.get("_started_at") if (e_raw := self._entry.raw_input) else None)
        )
        if ts is None:
            return ""
        try:
            return _dt.datetime.fromtimestamp(
                float(ts)
            ).strftime("%H:%M:%S")
        except Exception:  # noqa: BLE001
            return ""

    def _status_label(self, status: str) -> str:
        """Human-readable
        status word."""
        if status == "ok":
            return "ok"
        if status == "skipped":
            return "skipped"
        if status == "error":
            return "error"
        return "running"

    def _build_body(
        self, e: "ToolEntry"
    ) -> list[Text]:
        """Compose the
        ``key: value``
        body lines.

        The body shows
        the *user-visible*
        inputs and
        outputs of the
        call:
          * input
            args
            (one
            line
            per
            arg,
            value
            shorted
            if
            it
            is
            a
            long
            path)
          * the
            first
            non-empty
            artifact
            path
            /
            trace_id
            /
            current_pdf
            from
            the
            parsed
            output
          * a
            short
            ``summary``
            line
          * the
            error
            message
            on
            skipped
            /
            error
        """
        lines: list[Text] = []
        # Input
        # args.
        raw_in = dict(e.raw_input or {})
        # Strip
        # the
        # private
        # ``_started_at``
        # key
        # from
        # the
        # body
        # (it
        # is
        # rendered
        # in
        # the
        # header
        # instead).
        raw_in.pop("_started_at", None)
        if raw_in:
            for k, v in raw_in.items():
                # R-2026-06-19 (P2-D4):
                # if the value
                # is a multi-line
                # markdown
                # body, render
                # it as a
                # separate
                # indented
                # block
                # (with a
                # `key:` label
                # on the first
                # line) instead
                # of collapsing
                # to a single
                # line.  See
                # ``looks_like_markdown``
                # for the
                # detection
                # heuristic.
                lines.extend(
                    self._format_kv_or_markdown(
                        k, v, arrow=False
                    )
                )
        # Output
        # fields.
        # The
        # parser
        # is
        # best-effort
        # -- a
        # non-JSON
        # raw_output
        # just
        # shows
        # as
        # ``output:
        # <text>``.
        fields = self._extract_output_fields(e)
        for k, v in fields.items():
            # R-2026-06-19 (P2-D4):
            # markdown
            # output values
            # are common
            # here because
            # detector
            # summaries /
            # evidence
            # blocks are
            # often
            # formatted as
            # markdown by
            # the agent.
            lines.extend(
                self._format_kv_or_markdown(
                    k, v, arrow=True
                )
            )
        # Summary
        # + error.
        if e.summary:
            lines.append(
                self._format_kv(
                    "result",
                    _shorten_path(e.summary),
                )
            )
        if e.error and e.status in ("skipped", "error"):
            # Use
            # a
            # red
            # color
            # for
            # the
            # value
            # so
            # the
            # message
            # is
            # visually
            # distinct
            # from
            # a
            # normal
            # ``key:
            # value``
            # line.
            t = Text()
            t.append("    ", style="dim")
            t.append("error: ", style="dim #a6adc8")
            t.append(
                _truncate(e.error, 200),
                style="bold #f38ba8",
            )
            lines.append(t)
        return lines

    def _format_kv(
        self,
        key: str,
        value: Any,
        arrow: bool = False,
    ) -> Text:
        t = Text()
        t.append("    ", style="dim")
        t.append(
            f"{key}: ",
            style="dim #a6adc8",
        )
        if arrow:
            t.append("→ ", style="bold #89b4fa")
        t.append(
            _render_value(value),
            style="#cdd6f4",
        )
        return t

    def _format_kv_or_markdown(
        self,
        key: str,
        value: Any,
        arrow: bool = False,
        *,
        width: int = 80,
    ) -> list[Text]:
        """Like ``_format_kv`` but for multi-line markdown values.

        R-2026-06-19 (P2-D4):
        returns a list
        of ``Text``
        lines instead
        of a single
        line.  For
        plain values
        (numbers /
        short strings
        / non-markdown
        text) the
        list has
        exactly 1
        element which
        is what
        ``_format_kv``
        would have
        produced.  For
        multi-line
        markdown
        values, the
        list has
        ``N`` lines:
        the first is
        ``key: →
        <markdown
        line 1>``
        (where the
        rest of the
        markdown is
        rendered on
        subsequent
        indented
        lines).

        The caller
        does
        ``lines.extend(...)``
        so the rest
        of the card
        layout is
        unchanged.
        """
        # Non-string
        # values never
        # get the
        # markdown path.
        if not isinstance(value, str):
            return [self._format_kv(key, value, arrow=arrow)]
        # Plain
        # values
        # (no
        # markdown
        # markers)
        # use
        # the
        # old
        # single-line
        # path.
        if not looks_like_markdown(value):
            return [self._format_kv(key, value, arrow=arrow)]
        # Markdown
        # path:
        # first
        # line
        # is
        # the
        # ``key: →
        # <first
        # markdown
        # line>``
        # header,
        # then
        # the
        # rest
        # of
        # the
        # markdown
        # is
        # rendered
        # as
        # an
        # indented
        # block.
        header = Text()
        header.append("    ", style="dim")
        header.append(
            f"{key}: ",
            style="dim #a6adc8",
        )
        if arrow:
            header.append("→ ", style="bold #89b4fa")
        header.append("(markdown)", style="dim italic")
        rendered = _render_markdown_block(
            value, width=width, indent=4
        )
        return [header, *rendered]

    def _extract_output_fields(
        self, e: "ToolEntry"
    ) -> dict[str, Any]:
        """Parse
        ``e.raw_output``
        (JSON) and pull
        the *narrative*
        fields the user
        cares about.

        R-2026-06-16
        (Phase 4 +
        tool-call-card):
        we only show
        fields that are
        *informative* to
        a human reading
        the chat
        scrollback
        (trace_id,
        report paths,
        copyed PDF
        paths, etc.).
        Generic
        ``ok`` /
        ``latency_ms``
        are *not*
        shown (they
        are already
        in the header).

        R-2026-06-16 (Phase 4
        + tool-call-card,
        dedup): a field
        already shown
        in the
        ``raw_input``
        body (e.g.
        ``path`` for
        ``read_file``)
        is *not*
        re-shown as an
        output field
        with an arrow
        -- the user
        already saw it
        in the input
        section.  We
        skip those
        keys by
        ``key in
        raw_input``.
        """
        if not e.raw_output:
            return {}
        try:
            parsed = json.loads(e.raw_output)
        except (TypeError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        # Build
        # the
        # set
        # of
        # keys
        # the
        # user
        # *already
        # saw*
        # in
        # the
        # raw_input
        # body
        # (minus
        # the
        # private
        # ``_started_at``).
        _seen_in_input = set(
            (e.raw_input or {}).keys()
        ) - {"_started_at"}
        # R-2026-06-16 (Phase 4 +
        # tool-call-card):
        # PRIORITY is
        # now a
        # *boost*
        # list, not
        # an
        # *allowlist*.
        # Keys
        # in
        # PRIORITY
        # appear
        # first
        # (in
        # this
        # order)
        # so the
        # user
        # sees
        # the
        # *most
        # informative*
        # output
        # fields
        # at the
        # top of
        # the
        # card
        # (e.g.
        # ``trace_id``
        # then
        # ``report_path``).
        # Every
        # other
        # non-empty
        # output
        # key
        # (e.g.
        # ``row_count``,
        # ``column_count``,
        # ``n_findings``)
        # is
        # *also*
        # shown,
        # in
        # insertion
        # order
        # (so
        # newer
        # / less-
        # common
        # keys
        # still
        # surface).
        # The
        # earlier
        # design
        # was
        # a
        # strict
        # allowlist
        # which
        # silently
        # dropped
        # useful
        # output
        # fields.
        PRIORITY = (
            "trace_id",
            "report_path",
            "report_html",
            "html",
            "output_path",
            "script_path",
            "n_findings",
            "image_count",
            "table_count",
            "page_count",
            "filename",
            "current_pdf",
            "elapsed_seconds",
        )
        out: dict[str, Any] = {}
        # Phase 1:
        # priority
        # fields
        # in
        # the
        # order
        # defined
        # above.
        for k in PRIORITY:
            if k in _seen_in_input:
                continue
            v = parsed.get(k)
            if v is not None and v != "":
                out[k] = v
        # Phase 2:
        # every
        # other
        # non-empty,
        # non-
        # duplicate
        # key
        # in
        # the
        # output
        # (preserves
        # the
        # order
        # in
        # which
        # they
        # appear
        # in the
        # JSON).
        for k, v in parsed.items():
            if k in _seen_in_input:
                continue
            if k in out:
                continue
            if v is None or v == "":
                continue
            # Skip
            # fields
            # the
            # user
            # already
            # sees
            # in
            # the
            # header
            # / status
            # /
            # summary
            # (they
            # are
            # shown
            # elsewhere
            # so
            # showing
            # them
            # again
            # is
            # noise).
            if k in (
                "ok",
                "latency_ms",
                "error_kind",
                # ``error``
                # is
                # shown
                # in
                # the
                # dedicated
                # red
                # error
                # line
                # below
                # the
                # body
                # (and
                # also
                # in
                # ``result``
                # summary).
                # Showing
                # it
                # again
                # as
                # a
                # generic
                # ``error:
                # →
                # X``
                # line
                # would
                # duplicate
                # the
                # text.
                "error",
            ):
                continue
            out[k] = v
        # ``data_sources``:
        # show the
        # *count*,
        # not the
        # full list
        # (the list
        # can be
        # 100s of
        # items).
        ds = parsed.get("data_sources")
        if isinstance(ds, list) and ds and "data_sources" not in _seen_in_input:
            out["data_sources"] = (
                f"{len(ds)} source(s)"
            )
        return out


# ----- helpers shared by the card -----


def _fmt_duration(ms: int) -> str:
    """Render a
    millisecond
    duration in a
    human-readable
    form.

    R-2026-06-16
    (Phase 4 +
    tool-call-card):
    we follow
    Claude Code's
    convention --
    ``45ms`` for
    sub-second,
    ``2.4s`` for
    multi-second.
    """
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _render_value(v: Any) -> str:
    """Format a single
    value for the
    ``key: value``
    line.

    R-2026-06-16
    (Phase 4 +
    tool-call-card):
    we keep this
    simple --
    strings are
    truncated,
    paths are
    shortened via
    the existing
    ``_shorten_path``
    helper, numbers
    / booleans pass
    through.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # If it
    # looks
    # like a
    # path
    # (Windows
    # or
    # POSIX),
    # shorten
    # it.
    if (
        ("\\" in s and ":" in s[:3])
        or s.startswith(("/", "~/", "./", "../"))
    ):
        return _shorten_path(s)
    return _truncate(s, 200)


def _render_markdown_block(
    md: str, *, width: int = 80, indent: int = 4
) -> list[Text]:
    """Render a markdown string as a list of ``Text`` lines,
    each pre-indented by ``indent`` spaces.

    R-2026-06-19 (P2-D4):
    the
    ``ToolCallCard``
    body uses a
    ``key: value``
    layout that
    collapses
    multi-line
    evidence to a
    single line.
    When a value
    is multi-line
    markdown
    (headers /
    lists / code
    fences /
    bold / italic)
    the card now
    detects this
    and renders
    the value as
    a separate
    indented
    block,
    preserving
    the
    formatting.

    Implementation:
    Rich's
    ``Markdown``
    is renderable
    to a
    ``Console``
    with
    ``record=True``;
    we use
    ``export_text``
    to get the
    plain-text
    projection
    (the
    Textual
    ``Static``
    widget that
    backs
    ``ToolCallCard``
    only
    accepts
    ``Text``,
    not a
    Rich
    ``Markdown``
    renderable,
    so we
    project
    the
    markdown
    to
    text
    and
    re-style
    as
    a
    ``Text``
    with
    the
    same
    width
    as
    the
    card).

    Returns a
    list of
    ``Text``
    lines (one
    per visual
    line) so
    the caller
    can append
    them in
    place of a
    single
    ``_format_kv``
    result.
    """
    from rich.console import Console
    from rich.markdown import Markdown as RichMarkdown

    indented: list[Text] = []
    prefix = " " * indent
    try:
        console = Console(
            record=True,
            width=max(20, width - indent),
            force_terminal=False,
        )
        console.print(RichMarkdown(md))
        rendered = console.export_text(styles=False)
    except Exception:  # noqa: BLE001
        # ``Rich.Markdown`` can raise
        # on bad input.  Fall
        # back to plain text
        # so the card still
        # shows *something*.
        rendered = md

    for line in rendered.splitlines() or [rendered]:
        t = Text(prefix)
        t.append(line)
        indented.append(t)
    return indented


# ============================================================
# 4. DebugDrawer widget
# ============================================================


class DebugDrawer(VerticalScroll):
    """The hidden
    ``#debug-drawer``
    column. Default
    ``display: none``.

    Toggle with the
    ``d`` keybinding in
    the ChatApp.

    Holds raw
    tool-call JSON, raw
    tool-result JSON, raw
    assistant markdown
    source. Default
    hidden -- the user
    sees it only when
    they explicitly open
    it (e.g. when a tool
    behaves unexpectedly
    and the user wants to
    see the raw input).

    The drawer's content
    is a list of
    ``Static`` widgets
    (one per event) with
    monospace styling and
    a section heading per
    turn.
    """

    DEFAULT_CSS: ClassVar[str] = """
    DebugDrawer {
        display: none;  /* hidden by default */
        background: #11111b;  /* #11111b */
        color: #6c7086;  /* #a6adc8 */
        padding: 0 1 0 1;
        height: 1fr;
    }
    DebugDrawer.visible {
        display: block;
    }
    .debug-drawer-heading {
        color: #cba6f7;
        text-style: bold;
        margin: 1 0 0 0;
    }
    .debug-drawer-section {
        color: #6c7086;
        text-style: dim;
    }
    .debug-drawer-json {
        color: #cdd6f4;
        background: #181825;
        padding: 0 1 0 1;
    }
    .debug-drawer-toggle {
        dock: top;
        height: 1;
        background: #313244;
        color: #cdd6f4;
    }
    """

    def __init__(
        self,
        *children: Any,
        classes: str | None = None,
        **kwargs: Any,
    ) -> None:
        # R-audit (2026-06-11):
        # pass
        # ``**kwargs``
        # through
        # to
        # ``super().__init__``
        # so
        # ``id=``
        # and
        # other
        # ``Widget``
        # kwargs
        # are
        # honored.
        super().__init__(
            *children, classes=classes or "debug-drawer",
            **kwargs,
        )
        self._turn_counter = 0
        self._last_section: Static | None = None

    def show(self) -> None:
        """Make the drawer
        visible."""
        self.add_class("visible")

    def hide(self) -> None:
        """Hide the drawer."""
        self.remove_class("visible")

    def toggle(self) -> None:
        if self.has_class("visible"):
            self.hide()
        else:
            self.show()

    @property
    def is_visible(self) -> bool:
        return self.has_class("visible")

    # --- appenders ---

    def new_turn(self) -> None:
        """Start a new turn
        section."""
        self._turn_counter += 1
        heading = Static(
            f"── Turn {self._turn_counter} ──",
            classes="debug-drawer-heading",
        )
        self.mount(heading)
        self._last_section = heading

    def log_tool_call(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> None:
        """Append a tool-call
        entry to the
        drawer."""
        # Truncate
        # the
        # input
        # JSON
        # to
        # a
        # reasonable
        # size
        # for
        # the
        # drawer
        # (the
        # full
        # input
        # is
        # in
        # the
        # runner's
        # audit
        # log
        # -- this
        # is
        # just
        # for
        # visual
        # inspection).
        raw = json.dumps(tool_input, ensure_ascii=False, default=str)
        if len(raw) > 2000:
            raw = raw[:1997] + "..."
        section = Static(
            f"[tool call] {tool_name}",
            classes="debug-drawer-section",
        )
        json_block = Static(
            _shorten_path(raw),
            classes="debug-drawer-json",
        )
        self.mount(section)
        self.mount(json_block)
        self._last_section = section

    def log_tool_result(
        self, tool_name: str, output: str, is_error: bool
    ) -> None:
        """Append a
        tool-result entry."""
        marker = "[tool error]" if is_error else "[tool result]"
        section = Static(
            f"{marker} {tool_name}",
            classes="debug-drawer-section",
        )
        short = output
        if len(short) > 2000:
            short = short[:1997] + "..."
        json_block = Static(
            _shorten_path(short),
            classes="debug-drawer-json",
        )
        self.mount(section)
        self.mount(json_block)
        self._last_section = section

    def log_assistant_text(self, text: str) -> None:
        """Append the
        assistant's raw
        markdown source."""
        section = Static(
            "[assistant final]",
            classes="debug-drawer-section",
        )
        short = text
        if len(short) > 4000:
            short = short[:3997] + "..."
        body = Static(
            _shorten_path(short),
            classes="debug-drawer-json",
        )
        self.mount(section)
        self.mount(body)
        self._last_section = section

    def log_system_event(self, text: str) -> None:
        """Append a system
        event (max_steps,
        cancelled, etc.)."""
        section = Static(
            "[system event]",
            classes="debug-drawer-section",
        )
        body = Static(
            _shorten_path(text),
            classes="debug-drawer-json",
        )
        self.mount(section)
        self.mount(body)
        self._last_section = section

    def clear(self) -> None:
        """Remove all
        children (used when
        the user starts a
        new session)."""
        for child in list(self.children):
            child.remove()
        self._turn_counter = 0
        self._last_section = None


# ============================================================
# 5. Repeat-error dedup helper
# ============================================================


def dedup_tool_errors(
    entries: list[ToolEntry],
) -> dict[str, int]:
    """Group tool entries
    that have the same
    (tool_name, error)
    key, returning a map
    ``{ "tool_name:
    first_error_text" :
    N }``.

    The user's spec:
    "多个 ``PDF not
    found for
    trace_id=...```
    合并成 ``14 tools
    skipped: PDF not
    found for
    trace_id=...``".

    ``N`` is the number of
    deduped entries. The
    caller composes the
    user-facing summary
    line from this map.
    """
    out: dict[str, int] = {}
    for e in entries:
        if e.status not in (TOOL_SKIPPED, TOOL_ERROR):
            continue
        if not e.error:
            continue
        # The
        # key
        # is
        # the
        # first
        # occurrence's
        # error
        # text.
        # We
        # dedupe
        # by
        # (tool_name,
        # error).
        key = f"{e.tool_name}:{e.error[:120]}"
        out[key] = out.get(key, 0) + 1
    return out


# ============================================================
# 6. Helper: build the per-entry summary line
# ============================================================


def build_entry_summary(
    tool_name: str,
    status: str,
    error: str = "",
    output: str = "",
) -> str:
    """Build a one-line
    summary for a tool
    entry.

    The summary is the
    text shown in the
    expanded
    ``ToolTraceBlock`` (one
    row per tool). The
    user spec gives the
    exact format:
    ``"✓ image_dup 310ms
    no high-risk
    duplicate"`` or
    ``"⚠ pdf_metadata
    skipped: PDF not
    found"``.

    We compose the summary
    from the tool's
    structured output:
      * OK: the first 80
        chars of the
        output
      * SKIPPED: ``"skipped:
        " + first 80 chars
        of error``
      * ERROR: ``"error: "
        + first 80 chars of
        error``
    """
    if status == TOOL_SKIPPED:
        msg = error or output
        return _t("tool_status_skipped", msg=_truncate(msg, 80))
    if status == TOOL_ERROR:
        msg = error or output
        return _t("tool_status_error", msg=_truncate(msg, 80))
    # OK
    return _truncate(output or "ok", 80)


def _truncate(s: str, n: int) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) > n:
        return s[: n - 3] + "..."
    return s


# --------------------------------------------------------------------
# ToolEntry detail rendering (R-2026-06-14)
# --------------------------------------------------------------------
# The BashTool envelope carries
# cwd / stderr / shell_mode /
# returncode in addition to the
# raw stdout. The TUI's tool-trace
# block previously did not
# consume them; this helper turns
# the entry into a multi-line
# text the widget can render.
# The function is pure so it is
# unit-testable without a
# Textual App.


def format_entry_detail(entry: ToolEntry) -> str:
    """Render a ``ToolEntry`` as a
    multi-line text suitable for
    the TUI's tool-trace block.

    The first line is the existing
    ``summary`` (one-line). The
    following lines are the
    BashTool-specific fields,
    indented, only when they are
    non-empty.
    """
    lines: list[str] = []
    # First line: status + tool name
    # + duration.
    duration = ""
    if entry.duration_ms is not None:
        duration = f" {entry.duration_ms}ms"
    lines.append(
        f"{entry.tool_name} "
        f"[{entry.status}]{duration}"
    )
    if entry.summary:
        lines.append(f"  {entry.summary}")
    if entry.error:
        lines.append(f"  error: {entry.error}")
    # BashTool envelope fields.
    if entry.shell_mode:
        lines.append(
            f"  shell_mode: {entry.shell_mode}"
        )
    if entry.cwd:
        lines.append(f"  cwd: {entry.cwd}")
    if entry.returncode is not None:
        lines.append(
            f"  returncode: {entry.returncode}"
        )
    if entry.stderr:
        # Cap stderr so a noisy
        # command does not blow
        # up the trace block.
        stderr_preview = _truncate(
            entry.stderr, 200
        )
        lines.append(
            f"  stderr: {stderr_preview}"
        )
    return "\n".join(lines)
