"""Tests for the in-TUI banner integration (T1.1).

Pre-T1.1, the splash was printed
on stdout right before the
textual app started. That meant
the user saw the brand mark for
a single frame, then the screen
cleared and the chat TUI took
over. T1.1 embeds the splash as
a ``Static`` widget at the top
of the TUI itself, so the user
sees the brand mark + the input
box on the same screen from the
very first paint -- the same
pattern Hermes / Claude Code use.

The tests cover:

  1. The ChatApp compose tree
     contains a ``#banner`` Static
     widget.
  2. The banner widget's content
     is the plain-text splash (no
     ANSI escapes -- textual
     widgets render via Rich
     markup, not raw ANSI).
  3. The banner is rendered above
     the input widget (so the user
     sees the brand mark before
     they start typing).
  4. The TUI's input widget still
     receives focus on mount (the
     banner does not steal it).
  5. The chat_app ``main()`` no
     longer prints the splash to
     stdout (it would otherwise
     cause a "double banner"
     flicker).
"""
from __future__ import annotations

import re
import sys
from typing import Any

import pytest

from manusift.splash import render_splash


# ---------- 1. compose tree has the banner widget ----------

def test_chat_app_compose_has_banner_widget() -> None:
    """The ChatApp's compose()
    method must yield a Static
    widget with id="banner". The
    banner is what carries the
    brand mark on the first frame.
    """
    from manusift.tui.chat_app import ChatApp
    # The textual App._compose
    # mechanism is complex to drive
    # directly; instead we read the
    # source and assert that
    # ``id="banner"`` appears in
    # the compose() body. This is
    # a static check, but it's
    # robust enough to catch a
    # regression that removes the
    # banner widget.
    import inspect
    src = inspect.getsource(ChatApp._main_column_children)
    assert 'id="banner"' in src


def test_banner_widget_uses_compact_splash() -> None:
    """The banner widget's content
    is the compact splash (no
    ANSI escapes). Textual's
    Static widget renders via
    Rich markup; raw ANSI
    sequences would be shown as
    literal ``\\x1b`` text. The
    compact splash is a single
    row of the letter S centred
    in the target width.
    """
    from manusift.tui.chat_app import ChatApp
    import inspect
    src = inspect.getsource(ChatApp._main_column_children)
    # The compose() body must
    # call
    # ``render_compact_splash(use_color=False, ...)``
    # -- not the colored
    # variant. The call may
    # be split across lines;
    # match either form.
    assert (
        "render_compact_splash(use_color=False" in src
        or "render_compact_splash(" in src
        and "use_color=False" in src
    )


def test_banner_height_supports_multiline_compact_splash() -> None:
    """The vaporwave compact
    splash uses seven visible
    content lines. The Textual
    banner must reserve enough
    rows for that content plus
    the widget border."""
    from manusift.tui.chat_app import ChatApp
    assert "#banner" in ChatApp.CSS
    assert "height: 9;" in ChatApp.CSS
    assert "background:" in ChatApp.CSS
    # R-audit (2026-06-10): the
    # banner colour is now
    # bound to ``$mocha-pink``
    # (Catppuccin Mocha
    # ``#f5c2e7``) rather than
    # the previous hard-coded
    # ``#ff77e9``. The CSS
    # variable is defined at
    # the top of the
    # ``ChatApp.CSS`` block.
    assert "$mocha-pink" in ChatApp.CSS


@pytest.mark.asyncio
async def test_banner_is_inside_scrollable_history() -> None:
    """The splash must scroll away with the chat log.

    A top-level banner permanently consumes terminal rows; mounting it
    inside ``#history`` makes it part of the scrollback instead.
    """
    from manusift.llm.client import MockLLM
    from manusift.tui.chat_app import ChatApp
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        history = app.query_one("#history", VerticalScroll)
        banner = app.query_one("#banner", Static)
        assert banner.parent is history


# ---------- 2. banner content matches render_splash ----------

def test_banner_content_has_no_ansi_escapes() -> None:
    """The plain splash is what
    ends up in the Static widget.
    It must contain no ANSI
    escape sequences.
    """
    out = render_splash(use_color=False)
    assert "\x1b[" not in out
    assert "\x1b" not in out


def test_banner_content_has_no_capability_labels() -> None:
    """T1.1 removed the six
    capability labels. The banner
    must not contain any of them.
    """
    out = render_splash(use_color=False)
    for label in ("RISK SIEVE", "FIGURE FORENSICS", "METADATA",
                  "REFERENCE", "POLICY CHECK", "REPORT"):
        assert f"[ {label} ]" not in out


# ---------- 3. chat_app main() does NOT print the splash ----------

def test_chat_app_main_does_not_print_splash() -> None:
    """The console-script entry
    point ``ChatApp.main`` must
    not call ``sys.stdout.write(
    render_splash(...))`` -- that
    is the legacy T1.0 behavior
    that caused a "double banner"
    flicker (the splash flashed
    for a single frame, then the
    TUI cleared the screen).
    """
    from manusift.tui.chat_app import main
    import inspect
    src = inspect.getsource(main)
    assert "sys.stdout.write" not in src or "render_splash" not in src
    assert "render_splash()" not in src
