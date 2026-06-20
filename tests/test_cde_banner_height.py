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

    R-2026-06-20 (CDE-UI-P0.1 fix-2):
    the banner is
    now width-adaptive
    -- it gets the
    actual terminal
    width so the
    bar fills the
    banner (otherwise
    the user sees a
    thin dim line in
    an empty area).
    We compare
    against the
    same width-
    adaptive output
    so the test is
    robust to
    terminal size.
    """
    from manusift.splash import render_mini_splash
    from textual.widgets import Static

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        banner = app.query_one("#banner")
        assert isinstance(banner, Static)
        text = banner.content or ""
        lines = text.splitlines()
        assert len(lines) <= 3, (
            f"banner has {len(lines)} lines (expected <= 3); "
            f"got: {lines!r}"
        )
        # Width-adaptive: pass the same width
        # the chat_app chose.
        # The clamp is ``min(max(width-4, 40), 80)``
        # where ``width = app.size.width``.
        # On 120x40 this is min(max(116, 40), 80) = 80.
        width = min(max(app.size.width - 4, 40), 80)
        expected = render_mini_splash(use_color=False, width=width)
        assert text.strip() == expected.strip(), (
            f"banner content does not match render_mini_splash "
            f"at width={width}; got {text!r}, expected {expected!r}"
        )