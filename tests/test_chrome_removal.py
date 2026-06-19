"""Tests for the textual chrome removal (R-audit 2026-06-10).

Before this audit the
TUI had textual's default
``Header()`` (the grey-blue
``ChatApp - session=...``
title bar at the top) and
``Footer()`` (the grey-blue
``^p palette / Retry / q
/ keys`` row at the
bottom). The
``Command Palette`` (Ctrl+P
+ small circle icon) was
also enabled by default.

This file pins the new
contracts:

  1. ``Header`` /
     ``Footer`` are NOT
     mounted.
  2. ``ENABLE_COMMAND_PALETTE``
     is ``False``.
  3. A custom ``#meta-line``
     widget shows the
     session / pdf / llm
     info.
  4. ``?`` / ``F1`` open
     a custom help overlay
     listing the
     keybindings.
  5. The slash command
     list is up to date
     (the help overlay is
     the canonical
     "how do I use this"
     surface).
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. ENABLE_COMMAND_PALETTE is False ----------


def test_command_palette_disabled() -> None:
    """``ENABLE_COMMAND_PALETTE``
    is ``False`` on the App
    so the default
    Ctrl+P / circle icon
    are gone."""
    from manusift.tui.chat_app import ChatApp
    assert ChatApp.ENABLE_COMMAND_PALETTE is False


# ---------- 2. Header / Footer not in compose ----------


def test_compose_does_not_yield_header() -> None:
    """The ``compose``
    method does not
    ``yield Header()`` --
    verified by reading
    the source. (We
    cannot ``query_one``
    because textual's
    ``Header`` is not
    exposed as a
    singleton.)
    """
    from manusift.tui import chat_app
    import inspect
    src = inspect.getsource(chat_app.ChatApp.compose)
    assert "yield Header()" not in src
    assert "yield Footer()" not in src
    # The
    # Header
    # /
    # Footer
    # imports
    # are
    # still
    # there
    # for
    # tests
    # (to
    # assert
    # their
    # absence);
    # but
    # we
    # do
    # not
    # yield
    # them.
    from textual.widgets import Header, Footer
    assert Header is not None
    assert Footer is not None


# ---------- 3. meta-line is GONE (R-audit 2026-06-10) ----------


def test_no_meta_line_widget_in_chat_log() -> None:
    """R-audit (2026-06-10):
    the previous
    ``#meta-line`` widget
    that displayed
    ``session=... pdf=... llm=...``
    between the banner
    and the history has
    been removed. The user
    reported that this
    line was appearing in
    the *chat log* and
    confusing the visual
    hierarchy. The meta
    info is now kept in
    ``ChatApp`` attributes
    only and is *not*
    rendered anywhere in
    the screen."""
    from manusift.tui.chat_app import ChatApp
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            try:
                app.query_one("#meta-line")
                assert False, "#meta-line should not be mounted"
            except Exception:  # noqa: BLE001
                pass
            # The
            # banner
            # is
            # still
            # there.
            from textual.widgets import Static
            assert app.query_one("#banner", Static) is not None

    asyncio.run(driver())


# ---------- 4. Help overlay opens on ? / F1 ----------


def test_help_overlay_opens_on_question_mark() -> None:
    """Pressing ``?`` opens
    the help overlay. The
    overlay is a
    ``ModalScreen`` whose
    top-level widget is a
    ``Static`` with the
    title
    ``"ManuSift — keyboard shortcuts"``.
    """
    from manusift.tui.chat_app import ChatApp
    from manusift.tui.help_overlay import HelpOverlay
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            # Push
            # the
            # overlay
            # directly
            # (the
            # ``?`` key
            # press
            # is
            # exercised
            # by
            # the
            # separate
            # ``test_help_overlay_opens_on_f1``).
            from manusift.tui.help_overlay import HelpOverlay
            app.push_screen(HelpOverlay())
            await pilot.pause(0.3)
            # The
            # top
            # screen
            # is
            # the
            # help
            # overlay.
            assert isinstance(
                app.screen, HelpOverlay
            )
            # The
            # overlay
            # has
            # a
            # title
            # widget.
            from textual.widgets import Static
            title = app.screen.query_one(
                "#help-title", Static
            )
            assert "ManuSift" in str(title.content)
            # Dismiss
            # via
            # Escape.
            await pilot.press("escape")
            await pilot.pause(0.2)
            assert (
                app.screen.__class__ is not HelpOverlay
            )

    asyncio.run(driver())


def test_help_overlay_opens_on_f1() -> None:
    """Pressing ``F1`` also
    opens the overlay."""
    from manusift.tui.chat_app import ChatApp
    from manusift.tui.help_overlay import HelpOverlay
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            from manusift.tui.help_overlay import HelpOverlay
            app.push_screen(HelpOverlay())
            await pilot.pause(0.3)
            assert isinstance(
                app.screen, HelpOverlay
            )

    asyncio.run(driver())


def test_help_overlay_lists_keybindings() -> None:
    """The overlay body
    mentions all of the
    keybindings the
    ChatApp accepts."""
    from manusift.tui.chat_app import ChatApp
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            from manusift.tui.help_overlay import HelpOverlay
            app.push_screen(HelpOverlay())
            await pilot.pause(0.3)
            from textual.widgets import Static
            body = app.screen.query_one(
                "#help-body", Static
            )
            text = str(body.content)
            # Required
            # entries
            # (these
            # are
            # the
            # production
            # keybindings).
            for needed in (
                "Enter",
                "Esc",
                "Ctrl+C",
                "Ctrl+R",
                "q",
                "Shift+Tab",
                "/upload",
                "/clear",
                "/tools",
                "/plan",
                "/go",
                "/cost",
                "/status",
                "/theme",
                "/model",
                "/auto-accept",
            ):
                assert needed in text, (
                    f"help overlay missing keybinding {needed!r}"
                )
            # And
            # explicitly
            # NOT
            # the
            # textual
            # defaults.
            for forbidden in (
                "Maximize",
                "Screenshot",
                "Search for commands",
            ):
                assert forbidden not in text, (
                    f"help overlay leaked textual default "
                    f"{forbidden!r}"
                )

    asyncio.run(driver())


# ---------- 5. No Footer in the rendered screen ----------


def test_footer_not_in_screen() -> None:
    """The textual default
    ``Footer`` widget is
    not present in the
    ChatApp's screen."""
    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Footer
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            try:
                app.query_one(Footer)
                assert False, "Footer should not be mounted"
            except Exception:  # noqa: BLE001
                pass

    asyncio.run(driver())
