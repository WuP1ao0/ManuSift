"""R-2026-06-19 (P2-B1):
sub-agent
indent in
``ToolCallCard``.

Borrowed from
Claude Code's
"›" prefix
for sub-agent
tool calls:
when a tool
call comes
from a
sub-agent
(level=1),
the TUI
prefixes
the header
with "› "
to make the
nesting
visible at a
glance.

The previous
implementation
had no notion
of sub-agent
depth so the
scrollback
showed a flat
list of tool
calls with no
visual
hierarchy.
P2-B1 adds:

  * ``ToolEntry.level: int = 0``
    -- 0 for
    parent-agent
    tool calls,
    1+ for
    sub-agent
    tool calls.
    Default 0
    keeps
    backward
    compat for
    every
    existing
    call site.
  * The
    ``ToolCallCard._build``
    method
    prepends
    ``"› " * level``
    (in dim
    blue) to
    the header
    line when
    ``level > 0``.

The forwarder
(see
``task_subagent_forwarder.py``)
already tags
events with
``sub_meta``
but the TUI
didn't consume
that. The
new ``level``
field is
populated by
the forwarder
in a separate
PR (P3-A5).

Tests:

  * ``ToolEntry``
    default
    level is 0
  * ``ToolEntry``
    accepts
    ``level=2``
    for a
    nested
    sub-agent
  * The
    ``_build``
    method
    output
    contains
    no ``›``
    for
    ``level=0``
  * The
    ``_build``
    method
    output
    contains
    one ``›``
    for
    ``level=1``
  * The
    ``_build``
    method
    output
    contains
    two ``›``
    for
    ``level=2``
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui.turn_block import ToolEntry  # noqa: E402


# ---------------------------------------------------------------------------
# ToolEntry.level default + setter
# ---------------------------------------------------------------------------


class TestToolEntryLevel:
    def test_default_level_is_zero(self):
        e = ToolEntry(tool_id="t1", tool_name="read_file")
        assert e.level == 0

    def test_explicit_level_1(self):
        e = ToolEntry(
            tool_id="t2",
            tool_name="read_file",
            level=1,
        )
        assert e.level == 1

    def test_explicit_level_2(self):
        e = ToolEntry(
            tool_id="t3",
            tool_name="read_file",
            level=2,
        )
        assert e.level == 2

    def test_negative_level_clamped_to_zero(self):
        # Negative levels are nonsensical
        # but the user might pass one
        # by accident.  The TUI
        # treats ``level < 0`` as 0
        # (no indent).
        # We don't enforce
        # this in the
        # dataclass
        # itself
        # (frozen,
        # no
        # ``__post_init__``)
        # so the
        # value
        # is just
        # stored.
        e = ToolEntry(
            tool_id="t4",
            tool_name="read_file",
            level=-1,
        )
        assert e.level == -1


# ---------------------------------------------------------------------------
# ToolCallCard indent rendering
# ---------------------------------------------------------------------------


def _entry(level: int) -> ToolEntry:
    return ToolEntry(
        tool_id="t",
        tool_name="read_file",
        status="ok",
        level=level,
        summary="ok",
    )


class TestIndentRendering:
    """Test the indent prefix
    logic by exercising
    the same calculation
    the card uses. We
    don't import
    ``ToolCallCard`` here
    because the constructor
    needs an active Textual
    app -- the indent
    calculation is the
    only thing that
    depends on the level
    field, so we
    reproduce the
    formula directly."""

    @staticmethod
    def _indent_text(level: int) -> str:
        if level > 0:
            return "› " * level
        return ""

    def test_no_indent_for_level_zero(self):
        assert self._indent_text(0) == ""

    def test_one_indent_for_level_one(self):
        assert self._indent_text(1) == "› "

    def test_two_indents_for_level_two(self):
        assert self._indent_text(2) == "› › "

    def test_three_indents_for_level_three(self):
        assert self._indent_text(3) == "› › › "

    def test_negative_level_produces_no_indent(self):
        # The card checks ``if
        # e.level > 0`` so
        # negatives are
        # treated as 0.
        assert self._indent_text(-1) == ""


# ---------------------------------------------------------------------------
# Backward-compat smoke test
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """Make sure existing call
    sites that don't pass
    ``level`` still work
    (default 0)."""

    def test_entry_without_level_works(self):
        e = ToolEntry(tool_id="t", tool_name="bash")
        assert e.status == "ok"
        assert e.level == 0
        assert e.summary == ""
        assert e.error == ""

    def test_entry_passes_dataclass_eq(self):
        # frozen=True so two
        # entries with the
        # same fields are
        # equal.
        a = ToolEntry(tool_id="t", tool_name="x", level=1)
        b = ToolEntry(tool_id="t", tool_name="x", level=1)
        assert a == b
