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
async def test_banner_is_9_rows_with_compact_splash() -> None:
    """``#banner``
    must
    occupy
    exactly
    9
    rows
    on
    a
    default
    80x24
    terminal
    (the
    original
    design).

    R-2026-06-20 (CDE-UI-P0.1 full revert):
    the user
    explicitly
    asked to
    restore the
    9-row
    ``render_compact_splash``.
    The mini-splash
    experiment was
    rejected because
    it looked
    invisible on
    narrow terminals.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        banner = app.query_one("#banner")
        height = banner.region.height
        assert height == 9, (
            f"banner occupies {height} rows (expected exactly 9); "
            f"P0.1 full revert should restore the compact splash"
        )


@pytest.mark.asyncio
async def test_banner_uses_compact_splash_with_brand_mark() -> None:
    """``#banner`` content must be from
    ``render_compact_splash``
    (the 6-row MANUSIFT
    wordmark + tagline --
    the original brand
    mark).

    R-2026-06-20 (CDE-UI-P0.1 full revert):
    the user
    explicitly
    asked to
    restore the
    compact
    splash. The
    test compares
    against the
    same width-
    adaptive
    output so it
    is robust to
    terminal size.
    """
    from manusift.splash import render_compact_splash
    from textual.widgets import Static

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        banner = app.query_one("#banner")
        assert isinstance(banner, Static)
        text = banner.content or ""
        # The compact splash is 7 rows
        # (6-row wordmark + tagline).
        # Anything else means we are
        # using the wrong renderer.
        assert len(text.splitlines()) >= 6, (
            f"banner has only {len(text.splitlines())} lines; "
            f"expected >= 6 (the 6-row MANUSIFT wordmark); "
            f"got: {text!r}"
        )
        # And it
        # matches
        # the
        # compact
        # splash
        # output
        # at the
        # same
        # width.
        width = min(max(app.size.width - 4, 60), 80)
        expected = render_compact_splash(
            use_color=False, width=width
        )
        assert text.strip() == expected.strip(), (
            f"banner content does not match render_compact_splash "
            f"at width={width}; got {text!r}, expected {expected!r}"
        )