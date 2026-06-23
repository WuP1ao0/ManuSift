"""R-2026-06-21 (CDE-UI-P1.1):
regression test for
the RightRail
panel.

P1.1 added:
* ``manusift/tui/right_rail.py``
  (RightRail TabbedContent
  with 4 tabs: PDF /
  Finds / Tools /
  Cost).
* ``ChatApp.compose`` now
  yields
  ``Horizontal(Vertical(main-column), RightRail)``.
* Ctrl+] /
  Ctrl+[ toggle
  show / hide.
* ``_tick_live_elapsed``
  (1 Hz) updates
  the Cost /
  Finds / Tools
  tabs.

This test asserts
each of those.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


def _new_app() -> ChatApp:
    return ChatApp(llm_client=MockLLM())


@pytest.mark.asyncio
async def test_compose_yields_main_row_with_right_rail() -> None:
    """``ChatApp.compose`` now produces a
    ``#main-row`` Horizontal containing
    ``#main-column`` (3 children:
    history / input-row / status-line)
    AND ``#right-rail``.
    """
    app = _new_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        main_row = app.query_one("#main-row")
        # Must contain exactly 2 children: the
        # main column and the right rail.
        assert len(main_row.children) == 2, (
            f"#main-row must have 2 children (column + rail); "
            f"got {len(main_row.children)}: "
            f"{[type(c).__name__ for c in main_row.children]}"
        )
        # The right rail must be the second
        # child (so the column takes the
        # main-column flex space).
        assert main_row.children[1].id == "right-rail", (
            f"second child of #main-row must be #right-rail; "
            f"got id={main_row.children[1].id!r}"
        )


@pytest.mark.asyncio
async def test_right_rail_has_four_tabs() -> None:
    """``RightRail`` is a TabbedContent
    with 4 tabs: PDF / Finds / Tools /
    Cost.
    """
    from textual.widgets import TabbedContent, TabPane

    app = _new_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        rail = app.query_one("#right-rail")
        assert isinstance(rail, TabbedContent), (
            f"#right-rail must be a TabbedContent; "
            f"got {type(rail).__name__}"
        )
        # 4 TabPane children, one per tab.
        tab_panes = rail.query_children(TabPane)
        assert len(tab_panes) == 4, (
            f"expected 4 TabPane tabs; got {len(tab_panes)}"
        )
        # Each tab has a unique ID we set
        # in ``RightRail.compose``:
        # rail-tab-pdf / rail-tab-finds /
        # rail-tab-tools / rail-tab-cost.
        tab_ids = sorted(p.id for p in tab_panes)
        assert tab_ids == [
            "rail-tab-cost",
            "rail-tab-finds",
            "rail-tab-pdf",
            "rail-tab-tools",
        ], f"expected 4 tab IDs; got {tab_ids}"


@pytest.mark.asyncio
async def test_right_rail_visible_by_default() -> None:
    """The right rail is mounted and
    visible by default; Ctrl+[
    toggles it off, Ctrl+]
    toggles it back on.
    """
    app = _new_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        rail = app.query_one("#right-rail")
        assert rail.display is not False, (
            f"right rail must be visible by default; "
            f"display={rail.display!r}"
        )

        # Ctrl+[ hides.
        app.action_hide_right_rail()
        await pilot.pause(0.1)
        assert rail.display is False, (
            f"action_hide_right_rail must hide the rail; "
            f"display={rail.display!r}"
        )

        # Ctrl+] shows.
        app.action_show_right_rail()
        await pilot.pause(0.1)
        assert rail.display is not False, (
            f"action_show_right_rail must show the rail; "
            f"display={rail.display!r}"
        )


@pytest.mark.asyncio
async def test_right_rail_pdf_tab_shows_no_pdf_loaded() -> None:
    """The PDF tab shows ``no pdf loaded``
    when no PDF has been uploaded.
    """
    app = _new_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # Trigger a tick so the rail updates.
        app._tick_live_elapsed()
        await pilot.pause(0.1)
        pdf_content = app.query_one("#rail-pdf-content")
        text = pdf_content.content or ""
        assert "no pdf loaded" in str(text), (
            f"PDF tab must show 'no pdf loaded'; got {text!r}"
        )


@pytest.mark.asyncio
async def test_right_rail_cost_tab_shows_tokens() -> None:
    """The Cost tab shows tokens in /
    out and USD spent. The values
    are taken from
    ``self._tokens_in`` /
    ``self._tokens_out`` /
    ``self._cost_usd``.
    """
    app = _new_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # Set some cost values so the
        # output is non-trivial.
        app._tokens_in = 1234
        app._tokens_out = 5678
        app._cost_usd = 0.042
        app._tick_live_elapsed()
        await pilot.pause(0.1)
        cost_content = app.query_one("#rail-cost-content")
        text = str(cost_content.content or "")
        # Tokens are divided by 1000 and
        # shown as "1.2k" / "5.7k".
        assert "1.2k" in text, (
            f"Cost tab must show tokens_in as 1.2k; got {text!r}"
        )
        assert "5.7k" in text, (
            f"Cost tab must show tokens_out as 5.7k; got {text!r}"
        )
        assert "0.042" in text, (
            f"Cost tab must show $0.042 spent; got {text!r}"
        )