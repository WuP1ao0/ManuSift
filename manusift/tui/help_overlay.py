"""ManuSift help overlay (R-audit 2026-06-10).

Before this audit, the
canonical ``how do I use
this`` surface in the
TUI was textual's default
``Footer`` (a grey-blue
row of keybinding hints
at the bottom of the
screen) and the
``Command Palette`` (a
``Ctrl+P``-triggered
modal with ``Search for
commands``, ``Keys``,
``Maximize``, ``Quit``,
``Screenshot``,
``Theme``). Both are
textual built-ins aimed
at development, not at
production TUIs.

This module provides a
ManuSift-custom
``HelpOverlay`` modal
that:

  * lists the actual
    keybindings the
    ``ChatApp`` accepts
    (no noisy ``Maximize``,
    ``Screenshot``,
    ``Theme`` etc.),
  * uses the Catppuccin
    Mocha colour palette
    defined in
    ``ChatApp.CSS``,
  * dismisses on ``Esc``,
    ``?``, ``F1``, or
    ``q``.

The overlay is a textual
``ModalScreen`` (a
centred ``Container``)
with a single ``Static``
holding the key / action
table. The CSS is in
``HelpOverlay.CSS`` so
the colours stay in
sync with the rest of
the TUI.
"""
from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

# The key / action table.
# Each row is ``(key, action)``
# -- rendered as
# ``key  action`` with the
# key in mauve and the
# action in subtext. Kept
# in sync with
# ``ChatApp.BINDINGS`` and
# the slash-command list.
_HELP_LINES: tuple[tuple[str, str], ...] = (
    ("Enter", "send the current input to the agent"),
    ("Esc / Ctrl+C", "abort the in-flight LLM call"),
    ("Ctrl+R", "retry the most-recent user message"),
    ("q", "quit the TUI"),
    ("?", "open this help overlay"),
    ("F1", "open this help overlay"),
    ("Shift+Tab", "toggle plan mode (off → on)"),
    ("", ""),
    ("Slash commands:", ""),
    ("/upload <path>", "switch the active PDF"),
    ("/clear", "clear the on-screen history"),
    ("/tools", "list all 44 tools"),
    ("/skill <name>", "load a skill (analyze_paper, "
     "summarize_findings, compare_pdfs, integrity_report)"),
    ("/skills", "list available skills"),
    ("/plan on|off", "toggle plan mode"),
    ("/go <message>", "confirm a planned agent run"),
    ("/cost", "show running token + USD totals"),
    ("/status", "show session metadata"),
    ("/theme", "switch the colour theme"),
    ("/model", "switch the LLM model (in-session)"),
    ("/auto-accept", "toggle tool auto-accept"),
)


class HelpOverlay(ModalScreen[None]):
    """ManuSift custom help
    overlay -- a centred
    modal ``Container`` with
    a single ``Static``
    holding the keybinding
    table.

    Press ``Esc``, ``?``,
    ``F1``, or ``q`` to
    dismiss. ``Enter`` and
    ``Space`` also dismiss
    so the user is never
    stuck.
    """

    DEFAULT_CSS = """
    HelpOverlay {
        align: center middle;
    }
    HelpOverlay > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        background: #181825;
        border: thick #cba6f7;
        padding: 1 2;
    }
    HelpOverlay #help-title {
        color: #cba6f7;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }
    HelpOverlay #help-body {
        color: #cdd6f4;
        height: auto;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        # R-audit (2026-06-10):
        # multiple ways to
        # dismiss so the user
        # is never trapped.
        Binding("escape", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
        Binding("?", "dismiss", "Close", show=False),
        Binding("f1", "dismiss", "Close", show=False),
        Binding("enter", "dismiss", "Close", show=False),
        Binding("space", "dismiss", "Close", show=False),
    ]

    def compose(self):
        with Center():
            with Vertical():
                yield Static(
                    " ManuSift \u2014 keyboard shortcuts ",
                    id="help-title",
                )
                yield Static(
                    self._render_body(),
                    id="help-body",
                )

    def _render_body(self) -> str:
        """Format the help
        table. Keys are
        rendered in mauve
        (escape) and actions
        in subtext. We do
        not parse the result
        as Rich markup -- the
        ``Static`` widget
        has ``markup=False``
        -- so we use the
        textual-rendered
        ``Content`` API on
        mount instead. We
        return plain text
        here; the actual
        styling is applied
        via ``Content.stylize``
        in ``on_mount``.
        """
        # Just
        # the
        # raw
        # text;
        # styling
        # is
        # applied
        # post-mount.
        lines: list[str] = []
        for key, action in _HELP_LINES:
            if not key and not action:
                # Spacer.
                lines.append("")
                continue
            if not action:
                # Section
                # header.
                lines.append(key)
                continue
            # Row:
            # pad
            # the
            # key
            # to
            # 18
            # chars
            # so
            # actions
            # align.
            lines.append(f"{key:<18s}  {action}")
        return "\n".join(lines)

    def on_mount(self) -> None:
        """After mount, walk the
        help text and apply
        inline styles: keys
        in mauve, section
        headers in pink,
        actions in subtext.
        """
        body = self.query_one("#help-body", Static)
        text = self._render_body()
        # Build
        # a
        # Content
        # with
        # per-line
        # styling.
        from textual.content import Content

        c = Content("")
        line_offset = 0
        for key, action in _HELP_LINES:
            line = self._line_for(key, action)
            c = c.append_text(line + "\n")
            line_len = len(line)
            if not key and not action:
                # Spacer
                # --
                # no
                # style.
                pass
            elif not action:
                # Section
                # header
                # --
                # pink
                # bold.
                c = c.stylize(
                    "role-system",
                    start=line_offset,
                    end=line_offset + line_len,
                )
            else:
                # Row
                # --
                # key
                # in
                # peach
                # (inline-code
                # style),
                # action
                # in
                # subtext.
                key_len = len(key)
                c = c.stylize(
                    "inline-code",
                    start=line_offset,
                    end=line_offset + key_len,
                )
                if action:
                    c = c.stylize(
                        "role-system",
                        start=line_offset
                        + key_len
                        + 2,  # skip the 2-space gap
                        end=line_offset + line_len,
                    )
            line_offset += len(line) + 1  # +1 for \n
        body.update(c)

    @staticmethod
    def _line_for(key: str, action: str) -> str:
        if not key and not action:
            return ""
        if not action:
            return key
        return f"{key:<18s}  {action}"

    def action_dismiss(self) -> None:
        """Dismiss the overlay."""
        self.dismiss(None)
