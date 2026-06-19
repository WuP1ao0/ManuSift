"""R-2026-06-19 (P2-D6):
``/resume``
virtual
scrolling.

The
``/resume``
listing
returns
one
line
per
saved
session.
With
50+
sessions
the
output
is
too
long
to
fit
in
the
TUI
status
area
and
forces
the
user
to
scroll
back
through
hundreds
of
lines.

P2-D6 adds
paged
output:

  * The
    listing
    renders
    at
    most
    ``page_size``
    (default
    20)
    lines
    per
    call.
  * When
    there
    are
    more
    than
    ``page_size``
    sessions
    the
    output
    has
    a
    "page X of Y"
    header
    + a
    footer
    hint
    to
    "use /resume next".
  * Page
    0
    is
    the
    first
    page;
    page
    1
    is
    the
    second;
    etc.

Tests:

  * Empty
    listings
    return
    the
    same
    text
    as
    before
    (backward
    compat).
  * A
    small
    list
    (3
    sessions)
    fits
    on
    one
    page
    and
    does
    NOT
    show
    the
    "page X
    of Y"
    header.
  * A
    large
    list
    (50
    sessions)
    shows
    only
    the
    first
    ``page_size``
    entries
    by
    default.
  * A
    large
    list
    with
    ``page=1``
    shows
    the
    next
    ``page_size``
    entries.
  * The
    footer
    hints
    at
    the
    navigation
    commands
    ("more", "end of list").
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui.resume import render_resume_listing  # noqa: E402


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


@dataclass
class _FakeListing:
    """A minimal
    stand-in for
    ``SessionListing``
    (the real
    one lives
    in
    ``resume.py``
    and has
    more
    fields; we
    only need
    the four
    the
    renderer
    uses)."""

    session_id: str
    message_count: int
    last_user_preview: str
    model: str = "claude-sonnet-4"


def _make_listings(n: int) -> list[_FakeListing]:
    out: list[_FakeListing] = []
    for i in range(n):
        out.append(
            _FakeListing(
                session_id=f"abc{i:04x}",
                message_count=10 + i,
                last_user_preview=f"session {i} preview",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenderResumeListing:
    def test_empty_listings(self):
        text = render_resume_listing([])
        assert "no saved sessions" in text

    def test_small_list_no_pagination(self):
        """3 sessions <
        page_size (20)
        so the
        listing
        fits on
        one page."""
        text = render_resume_listing(_make_listings(3))
        assert "Past chat sessions" in text
        # No
        # "page
        # X
        # of
        # Y"
        # header.
        assert "page" not in text
        # All 3
        # sessions
        # appear.
        for i in range(3):
            assert f"abc{i:04x}" in text

    def test_large_list_paginates_by_default(
        self,
    ):
        """50 sessions >
        page_size (20)
        so the
        listing
        shows
        only the
        first 20."""
        text = render_resume_listing(_make_listings(50))
        # Page
        # header
        # appears.
        assert "page 1 of 3" in text
        # First
        # page
        # shows
        # sessions
        # 0-19
        # (abc0000
        # to
        # abc0013).
        assert "abc0000" in text
        # Session
        # 25 is
        # NOT on
        # the
        # first
        # page.
        assert "abc0025" not in text
        # Footer
        # says
        # "more".
        assert "more" in text

    def test_large_list_page_2(self):
        """``page=1``
        shows
        the
        second
        page."""
        text = render_resume_listing(
            _make_listings(50), page=1
        )
        assert "page 2 of 3" in text
        # Page
        # 2
        # has
        # sessions
        # 20-39
        # (abc0014
        # to
        # abc0027).
        assert "abc0014" in text
        assert "abc0027" in text
        # Session
        # 5
        # is on
        # page
        # 1,
        # NOT
        # page
        # 2.
        assert "abc0005" not in text

    def test_last_page_footer(self):
        """The last
        page
        shows
        'end of
        list'."""
        # 25
        # sessions
        # =
        # 2
        # pages
        # (20 +
        # 5).
        text = render_resume_listing(
            _make_listings(25), page=1
        )
        assert "page 2 of 2" in text
        assert "end of list" in text
        # Last
        # page
        # has
        # 5
        # entries.
        for i in range(20, 25):
            assert f"abc{i:04x}" in text

    def test_custom_page_size(self):
        """A small
        ``page_size=5``
        paginates
        10
        sessions
        into
        2
        pages."""
        text = render_resume_listing(
            _make_listings(10), page_size=5
        )
        assert "page 1 of 2" in text
        # First
        # page
        # has
        # 5
        # entries.
        for i in range(5):
            assert f"abc{i:04x}" in text
        # Second
        # page
        # has
        # 5
        # more.
        text2 = render_resume_listing(
            _make_listings(10),
            page_size=5,
            page=1,
        )
        for i in range(5, 10):
            assert f"abc{i:04x}" in text2

    def test_out_of_range_page_clamped(self):
        """A ``page``
        > last
        page is
        clamped
        to the
        last
        page.
        With
        50
        sessions
        +
        page=99,
        the
        clamped
        page is
        the
        last
        (3
        of 3)."""
        text = render_resume_listing(
            _make_listings(50), page=99
        )
        # Clamped
        # to the
        # last
        # page.
        assert "page 3 of 3" in text
        # The
        # last
        # page
        # footer
        # is
        # shown.
        assert "end of list" in text
        # The
        # last
        # few
        # sessions
        # are
        # in the
        # output.
        for i in range(45, 50):
            assert f"abc{i:04x}" in text
