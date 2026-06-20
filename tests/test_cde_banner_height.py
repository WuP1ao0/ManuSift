"""R-2026-06-20 (CDE-UI-P0.1):
regression test for
the 9-row MANUSIFT
banner that
wasted 36%
of the 80x24
screen.

After P0.1,
``#banner`` is
``height: 3``
and renders
``render_mini_splash``
(bar + wordmark +
bar = 3 rows)
instead of the
8-row wordmark
+ tagline.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


@pytest.mark.asyncio
async def test_banner_is_at_most_3_rows() -> None:
    """``#banner``
    must
    occupy
    <=
    3
    rows
    on
    a
    default
    80x24
    terminal.
    The
    previous
    design
    used
    9
    rows
    (8-row
    wordmark
    + tagline)
    which
    wasted
    36%
    of
    the
    screen.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        banner = app.query_one("#banner")
        height = banner.region.height
        assert height <= 3, (
            f"banner occupies {height} rows (expected <= 3); "
            f"P0.1 was supposed to shrink it"
        )


@pytest.mark.asyncio
async def test_banner_uses_mini_splash_not_compact() -> None:
    """``#banner`` content must be from
    ``render_mini_splash`` (3 lines:
    bar + ``[ MANUSIFT ]`` + bar),
    NOT from ``render_compact_splash``
    (8 lines: 6-row wordmark +
    tagline).
    """
    from manusift.splash import render_mini_splash

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        banner = app.query_one("#banner")
        # ``Static.content``
        # holds the
        # raw text
        # -- it
        # contains
        # 3 newline-separated
        # lines.
        text = banner.content or ""
        lines = text.splitlines()
        assert len(lines) <= 3, (
            f"banner has {len(lines)} lines (expected <= 3); "
            f"got: {lines!r}"
        )
        # And it
        # matches
        # the
        # mini-splash
        # output.
        expected = render_mini_splash(use_color=False)
        assert text.strip() == expected.strip(), (
            f"banner content does not match render_mini_splash; "
            f"got {text!r}, expected {expected!r}"
        )