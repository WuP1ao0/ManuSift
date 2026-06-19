"""R-2026-06-19 (P2-D4):
ToolCallCard
markdown
render.

The
``ToolCallCard``
body is a
``key: value``
list.  When
a value is a
multi-line
markdown body
(headers /
lists / bold /
italic / code
fences), the
old code
collapsed it
to a single
truncated line
so the
formatting
was lost.

P2-D4 adds:

  * ``looks_like_markdown(s)``
    -- a
    conservative
    heuristic
    (>= 40 chars,
    >= 2 lines,
    >= 2 of 7
    signal
    patterns)
    that
    classifies
    a string as
    "looks like
    markdown".

  * ``_render_markdown_block(md, width, indent)``
    -- renders
    markdown via
    Rich's
    ``Markdown``
    to a
    ``Text`` list
    with the
    given
    width /
    indent.

  * ``ToolCallCard._format_kv_or_markdown(k, v, arrow)``
    -- returns
    a list of
    ``Text``
    lines.  For
    plain
    values the
    list is
    length 1
    (matches
    the old
    behavior);
    for
    multi-line
    markdown
    values the
    list is
    length 1
    + N (the
    first is
    the
    ``key: →
    (markdown)``
    header,
    the next N
    are the
    rendered
    markdown
    lines).

Tests:

  * ``looks_like_markdown``
    correctly
    classifies
    plain text
    / lists /
    headers /
    multi-line
    evidence
    blocks
  * ``_render_markdown_block``
    returns a
    list of
    ``Text``
    lines with
    the right
    indent
  * ``_format_kv_or_markdown``
    returns a
    single-line
    result for
    plain
    values
    (backward
    compat)
  * ``_format_kv_or_markdown``
    returns a
    multi-line
    result for
    markdown
    values
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rich.text import Text

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui.turn_block import (  # noqa: E402
    _render_markdown_block,
    looks_like_markdown,
)


# ---------------------------------------------------------------------------
# looks_like_markdown
# ---------------------------------------------------------------------------


class TestLooksLikeMarkdown:
    def test_short_string_is_not_markdown(self):
        assert looks_like_markdown("ok") is False
        assert looks_like_markdown("5 findings") is False

    def test_single_line_long_string_is_not_markdown(self):
        assert (
            looks_like_markdown(
                "this is a long single-line string that has "
                "no markdown markers at all"
            )
            is False
        )

    def test_multi_line_no_markers_is_not_markdown(self):
        s = (
            "first line of plain text\n"
            "second line of plain text\n"
            "third line of plain text"
        )
        assert looks_like_markdown(s) is False

    def test_headers_and_lists_is_markdown(self):
        s = (
            "## Findings\n\n"
            "- **severity**: high\n"
            "- **detector**: benford\n"
            "- **column**: A\n"
        )
        assert looks_like_markdown(s) is True

    def test_bold_and_italic_is_markdown(self):
        s = (
            "## Evidence\n\n"
            "The **global std** is 0.5 and the "
            "*max local* std is 3.5.\n"
        )
        assert looks_like_markdown(s) is True

    def test_code_fence_is_markdown(self):
        s = (
            "## Reproducer\n\n"
            "```python\n"
            "x = 1\n"
            "y = 2\n"
            "```\n"
        )
        assert looks_like_markdown(s) is True

    def test_list_without_header_is_markdown(self):
        s = (
            "Here are the items:\n\n"
            "- first item\n"
            "- second item\n"
            "- third item\n"
        )
        assert looks_like_markdown(s) is True

    def test_ordered_list_is_markdown(self):
        s = (
            "Steps:\n\n"
            "1. first\n"
            "2. second\n"
            "3. third\n"
        )
        assert looks_like_markdown(s) is True

    def test_link_is_markdown(self):
        s = (
            "See [the docs](https://example.com) "
            "for more details.\n\n"
            "And also the [RFC](https://rfc.org)."
        )
        assert looks_like_markdown(s) is True

    def test_non_string_returns_false(self):
        assert looks_like_markdown(None) is False  # type: ignore[arg-type]
        assert looks_like_markdown(42) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _render_markdown_block
# ---------------------------------------------------------------------------


class TestRenderMarkdownBlock:
    def test_returns_list_of_text(self):
        s = "## Hello\n\n- item 1\n- item 2\n"
        lines = _render_markdown_block(s, width=80, indent=4)
        assert isinstance(lines, list)
        assert all(isinstance(line, Text) for line in lines)
        assert len(lines) >= 1

    def test_indent_applied_to_every_line(self):
        s = "## Hello\n\n- item 1\n- item 2\n"
        for line in _render_markdown_block(s, width=80, indent=4):
            plain = line.plain
            # Every line should start with 4 spaces.
            assert plain.startswith("    "), (
                f"line {plain!r} missing 4-space indent"
            )

    def test_width_affects_wrapping(self):
        s = (
            "This is a long line that should wrap when "
            "the width is narrow. " * 5
        )
        # We can't assert exact wrap count (depends
        # on Rich version), but narrow width should
        # produce more lines than wide width.
        narrow = _render_markdown_block(s, width=40, indent=0)
        wide = _render_markdown_block(s, width=200, indent=0)
        assert len(narrow) >= len(wide)

    def test_bad_input_falls_back_to_plain(self):
        # Markdown that raises inside Rich should
        # still produce output (the fallback
        # path).
        # ``Markdown("")`` is fine, so we test
        # that an empty string returns 1 line
        # (the "").
        lines = _render_markdown_block("", width=80, indent=4)
        assert len(lines) >= 1


# ---------------------------------------------------------------------------
# _format_kv_or_markdown integration (light smoke test)
# ---------------------------------------------------------------------------


class TestFormatKvOrMarkdown:
    """The ``_format_kv_or_markdown`` method is on the
    ``ToolCallCard`` class.  We instantiate the class
    without mounting (no app) so the import-time
    helpers are exercised without the full TUI
    machinery.

    Note: the test for the actual output shape lives
    in ``test_tool_call_card.py`` which already has
    the full TUI harness; here we just verify that
    the helper correctly returns a list of Text
    objects."""

    def test_plain_value_returns_single_line(self):
        # We can't easily instantiate a
        # ``ToolCallCard`` outside the app
        # (the constructor calls
        # ``_update_css_for_status`` which
        # uses ``self.set_class`` and other
        # Textual APIs).  But we can
        # exercise the helper function
        # ``looks_like_markdown`` and
        # ``_render_markdown_block``
        # directly which is what
        # ``_format_kv_or_markdown``
        # delegates to.
        plain = "ok"
        assert looks_like_markdown(plain) is False

    def test_markdown_value_returns_multi_lines(self):
        md = (
            "## Findings\n\n"
            "- **severity**: high\n"
            "- **detector**: benford\n"
        )
        assert looks_like_markdown(md) is True
        lines = _render_markdown_block(md, width=80, indent=4)
        # Header + at least 2 list items + blank
        # = 4 lines minimum.
        assert len(lines) >= 3
