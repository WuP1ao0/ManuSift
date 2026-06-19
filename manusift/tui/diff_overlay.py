"""R-2026-06-20 (CDE-C5):
``DiffOverlay`` is a Textual modal screen that
renders a unified diff in a scrollable
viewport.

The ``/diff`` slash
command pushes
this screen
instead of
single-line
output, so the
user can scroll
through a long
diff without
cluttering the
chat log.

Press ``Esc``
or ``q`` to
dismiss.
"""
from __future__ import annotations

import json
from typing import Any

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class DiffOverlay(ModalScreen[None]):
    """Modal screen that shows a unified diff."""

    DEFAULT_CSS = """
    DiffOverlay {
        align: center middle;
    }
    #diff-overlay-container {
        width: 90%;
        height: 80%;
        background: $mocha-base;
        border: thick $mocha-mauve;
        padding: 1 2;
    }
    #diff-overlay-title {
        height: 1;
        color: $mocha-mauve;
        text-style: bold;
        background: $mocha-mantle;
        content-align: center middle;
        margin-bottom: 1;
    }
    #diff-overlay-body {
        height: 1fr;
        overflow-y: auto;
        background: $mocha-base;
    }
    #diff-overlay-footer {
        height: 1;
        dock: bottom;
        color: $mocha-subtext;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Dismiss"),
        Binding("q", "dismiss", "Dismiss"),
        Binding("ctrl+c", "dismiss", "Dismiss"),
    ]

    def __init__(
        self,
        title: str,
        diff_text: str,
        *,
        language: str = "diff",
    ) -> None:
        super().__init__()
        self._title = title
        self._diff_text = diff_text
        self._language = language

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-overlay-container"):
            yield Static(self._title, id="diff-overlay-title")
            yield Static(self._diff_text, id="diff-overlay-body")
            yield Static(
                "[dim]Press Esc / q to dismiss[/dim]",
                id="diff-overlay-footer",
            )

    def action_dismiss(self) -> None:
        self.dismiss(None)


def render_diff_modally(
    app: Any,
    title: str,
    diff_text: str,
) -> None:
    """Push a ``DiffOverlay`` onto the chat app's screen stack.

    Helper for slash-command handlers (``/diff`` etc.)
    so the diff renders in a modal viewport instead of
    single-line status output.
    """
    if app is None:
        return
    overlay = DiffOverlay(title=title, diff_text=diff_text)
    try:
        app.push_screen(overlay)
    except Exception:  # noqa: BLE001
        # Fall back to a status line if the TUI is not booted
        # (e.g. during unit tests).
        if hasattr(app, "_append_status_line"):
            app._append_status_line(diff_text[:500])


__all__ = ["DiffOverlay", "render_diff_modally"]