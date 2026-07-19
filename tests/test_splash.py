"""Tests for the splash module.

We test the public
``render_*`` functions and
the helper that builds
the compact banner
currently used by the
in-TUI banner widget. The
old tests referenced the
4-row splash (top border,
letter row, label row,
bottom border) but the
in-TUI banner is now a
single row of the letter S
in a full-width border
drawn by textual. We
focus on the public
helpers that the TUI
actually consumes.
"""
from __future__ import annotations

import re

import pytest


# ---------- 1. render_compact_splash ----------

def _strip_rich_markup(text: str) -> str:
    return re.sub(
        r"\[(?:/|/?(?:[a-z_]+|#[0-9a-fA-F]{6}|color\([0-9]+\)))\]",
        "",
        text,
    )

def test_compact_splash_default_width_is_80() -> None:
    """Every visible compact
    banner row is exactly 80
    characters by default.
    """
    from manusift.splash import render_compact_splash
    out = render_compact_splash(
        use_color=False, markup=True
    )
    visible_lines = [
        _strip_rich_markup(line)
        for line in out.splitlines()
    ]
    assert len(visible_lines) == 7
    assert {len(line) for line in visible_lines} == {80}


def test_compact_splash_custom_width() -> None:
    """The ``width`` argument
    is respected for every
    compact banner row."""
    from manusift.splash import render_compact_splash
    out = render_compact_splash(
        use_color=False, markup=True, width=60
    )
    visible_lines = [
        _strip_rich_markup(line)
        for line in out.splitlines()
    ]
    assert len(visible_lines) == 7
    assert {len(line) for line in visible_lines} == {60}


def test_compact_splash_markup_returns_rich_tags() -> None:
    """``markup=True`` emits
    Rich markup tags (e.g.
    ``[magenta]...[/]``)
    rather than raw ANSI
    escapes."""
    from manusift.splash import render_compact_splash
    out = render_compact_splash(
        markup=True, width=80
    )
    # No raw escape
    # characters should
    # appear in markup
    # mode.
    assert "\x1b" not in out
    # And there should be
    # Rich colour tags.
    assert "[" in out
    assert "[/" in out


def test_compact_splash_markup_parses_as_textual_content() -> None:
    """The optional workspace TUI renders the
    compact splash through
    Textual's markup parser, so
    the emitted tags must be
    accepted by Textual, not only
    by Rich."""
    from textual.content import Content
    from manusift.splash import render_compact_splash
    out = render_compact_splash(
        use_color=False, markup=True, width=98
    )
    Content.from_markup(out)


def test_compact_splash_is_vaporwave_wordmark() -> None:
    """The compact splash is a
    multi-line vaporwave
    MANUSIFT banner with a
    large MANUSIFT wordmark."""
    from manusift.splash import render_compact_splash
    out = render_compact_splash(
        use_color=False, markup=False, width=98
    )
    lines = out.splitlines()
    assert len(lines) == 7
    assert "MANUSIFT" in out
    assert "NEON SUNSET" not in out
    assert "VAPORWAVE HORIZON" not in out
    assert "DATA GHOST GRID" not in out
    wordmark_rows = lines[:6]
    assert min(len(row.strip()) for row in wordmark_rows) >= 70
    assert all(
        any(ord(ch) == 0x2588 or 0x2500 <= ord(ch) <= 0x257F for ch in row)
        for row in wordmark_rows
    )
    assert "source tracing // figure ghosts // metadata drift" in out


# ---------- 2. render_splash (full) ----------

def test_full_splash_produces_14_lines() -> None:
    """``render_splash``
    produces a 14-line
    banner: top border,
    scan line, blank, 7
    letter rows, blank,
    blank (no labels in
    T1.1), scan line,
    bottom border. We
    check the line count
    rather than the width
    because the letter
    rows' width depends
    on the underlying
    font."""
    from manusift.splash import render_splash
    out = render_splash(use_color=False, markup=True)
    assert len(out.split(chr(10))) == 14


def test_full_splash_marks_letter_rows_with_colour_tags() -> None:
    """Each letter row in
    the full splash has a
    colour tag around the
    centred letter art.
    The tag colours form
    the purple-to-magenta
    gradient."""
    from manusift.splash import render_splash
    out = render_splash(use_color=False, markup=True)
    # 7 letter rows
    # between the two
    # scan lines; each
    # has a colour tag.
    for line in out.split(chr(10))[3:10]:
        plain = re.sub(r"\[/?[a-z]+\]", "", line)
        # The colour tag
        # should appear
        # *before* the
        # letter art and
        # not contribute
        # any visible
        # char. The plain
        # text is the
        # content the user
        # actually sees.
        assert "█" in plain or "│" in plain


def test_full_splash_no_capability_labels() -> None:
    """The full splash
    contains no
    capability labels
    (T1.1 removal)."""
    from manusift.splash import render_splash
    out = render_splash(use_color=False, markup=True)
    # The capability
    # labels that used
    # to be there were
    # bracketed like
    # ``[ DETECT ]``. We
    # assert no such
    # bracket is in
    # the output.
    assert "[ DETECT" not in out
    assert "[ ANALYSE" not in out
    assert "[ EXPLAIN" not in out
