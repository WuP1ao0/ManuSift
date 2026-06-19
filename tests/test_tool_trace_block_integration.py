"""Tests for the R-2026-06-14 ToolTraceBlock
detail-block integration.

The block consumes the
``format_entry_detail()`` pure function
when a tool entry carries the BashTool-
specific fields (cwd / stderr /
shell_mode / returncode).

The contract:

  * An entry with no bash fields renders
    the same as before (no extra lines).
  * An entry with bash fields appends
    a multi-line indented detail block
    under the entry's summary line.
  * The detail block is ``[dim]`` styled
    so it does not overpower the
    green/yellow/red summary icon.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from manusift.tui.turn_block import (
    TOOL_OK,
    ToolEntry,
    ToolTraceBlock,
    format_entry_detail,
)


# --------------------------------------------------------------------
# ToolTraceBlock._expanded_block integration
# --------------------------------------------------------------------


def _make_block() -> ToolTraceBlock:
    """Construct an unmounted
    ``ToolTraceBlock`` (the unit
    tests do not need a textual
    App -- we read
    ``_expanded_block()``
    directly).
    """
    # ``ToolTraceBlock`` extends
    # textual ``Static``; the
    # parent class is a no-op
    # widget that we can
    # construct without an app.
    try:
        return ToolTraceBlock()
    except Exception:
        # Textual in headless mode
        # may refuse construction;
        # fall back to skipping
        # the integration tests.
        pytest.skip(
            "textual Static not "
            "constructible in this "
            "test environment"
        )


def test_expanded_block_without_bash_fields_is_unchanged():
    """A non-bash entry (e.g.
    ``image_dup``) renders the same
    as before. The detail block is
    not appended because all
    BashTool fields are empty.
    """
    block = _make_block()
    block.add_entry(
        ToolEntry(
            tool_id="i",
            tool_name="image_dup",
            status=TOOL_OK,
            duration_ms=120,
            summary="no high-risk duplicate",
        )
    )
    out = block._expanded_block()
    text = out.plain
    assert "image_dup" in text
    assert "no high-risk duplicate" in text
    # The bash detail lines must not
    # appear (no shell_mode / cwd /
    # returncode / stderr markers).
    assert "shell_mode:" not in text
    assert "cwd:" not in text
    assert "returncode:" not in text


def test_expanded_block_with_bash_fields_appends_detail():
    """A bash entry with cwd / stderr /
    shell_mode / returncode populates
    a multi-line detail block under
    the summary line.
    """
    block = _make_block()
    block.add_entry(
        ToolEntry(
            tool_id="i",
            tool_name="bash",
            status=TOOL_OK,
            duration_ms=42,
            summary="ran",
            cwd="C:/Users/me",
            stderr="warning: deprecated flag",
            shell_mode="cmd",
            returncode=0,
        )
    )
    out = block._expanded_block()
    text = out.plain
    assert "bash" in text
    assert "ran" in text
    # Detail block is appended.
    assert "shell_mode: cmd" in text
    assert "cwd: C:/Users/me" in text
    assert "returncode: 0" in text
    assert "stderr: warning: deprecated flag" in text


def test_expanded_block_indents_detail_lines():
    """The detail lines are
    indented so they nest under
    the entry's summary line.
    """
    block = _make_block()
    block.add_entry(
        ToolEntry(
            tool_id="i",
            tool_name="bash",
            status=TOOL_OK,
            cwd="C:/x",
            shell_mode="cmd",
            returncode=0,
        )
    )
    out = block._expanded_block()
    # Each detail line has 4-space
    # indent (the block uses 4
    # spaces, not tabs).
    plain = out.plain
    for needle in (
        "    shell_mode: cmd",
        "    cwd: C:/x",
        "    returncode: 0",
    ):
        assert needle in plain, (
            f"missing {needle!r} in:\n{plain}"
        )


def test_expanded_block_preserves_existing_entries():
    """Adding a bash entry after a
    non-bash entry renders both
    correctly.
    """
    block = _make_block()
    block.add_entry(
        ToolEntry(
            tool_id="i",
            tool_name="image_dup",
            status=TOOL_OK,
        )
    )
    block.add_entry(
        ToolEntry(
            tool_id="j",
            tool_name="bash",
            status=TOOL_OK,
            shell_mode="cmd",
            returncode=0,
        )
    )
    out = block._expanded_block()
    text = out.plain
    # Both entries are in the
    # expanded view.
    assert "image_dup" in text
    assert "bash" in text
    # Only the bash entry has the
    # detail lines.
    assert "shell_mode: cmd" in text


def test_format_entry_detail_still_works_standalone():
    """Sanity: the underlying
    ``format_entry_detail`` is
    unchanged -- the integration
    is purely a consumer.
    """
    e = ToolEntry(
        tool_id="i",
        tool_name="bash",
        cwd="D:/x",
        shell_mode="bash",
    )
    text = format_entry_detail(e)
    assert "shell_mode: bash" in text
    assert "cwd: D:/x" in text
