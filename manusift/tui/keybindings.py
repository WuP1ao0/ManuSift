"""R-2026-06-19 (P3-D8):
keyboard
shortcut
table.

The TUI
already
implements
``action_help``
which
pushes
a
``HelpOverlay``
modal
when the
user
presses
``?``
or
``F1``.
P3-D8 adds
a
*programmatic*
list of
key bindings
that
the
``HelpOverlay``
renders
+ that
the tests
can verify.

Why a
separate
module
instead of
parsing the
``BINDINGS``
list? The
``BINDINGS``
list is
Textual-specific
(``Binding``
class with
``key``,
``action``,
``description``
attributes)
and the
overlay
needs the
key/action
pair PLUS
a
human-readable
*category*
("Chat" /
"Plan" /
"Tools")
for grouping.
This module
owns the
canonical
list and
the
``HelpOverlay``
imports
it.

Tests:

  * The
    keybinding
    list
    is
    non-empty.
  * Every
    binding
    has
    a
    non-empty
    ``key``,
    ``action``,
    ``description``,
    and
    ``category``.
  * Common
    bindings
    are
    present
    (Enter
    → submit,
    Ctrl+C
    → abort,
    ? / F1
    → help).
  * The
    ``format_keybinding_help``
    function
    returns
    a
    non-empty
    text
    report
    with
    the
    bindings
    grouped
    by
    category.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class KeyBinding:
    """One keyboard
    shortcut.

    Attributes:
        key: the
            Textual
            key
            spec
            (e.g.
            ``"enter"``,
            ``"ctrl+c"``,
            ``"?"``,
            ``"f1"``).
        action: the
            ``action_*``
            method
            name
            (e.g.
            ``"submit_input"``,
            ``"abort"``,
            ``"help"``).
        description:
            one-line
            description
            shown
            in
            the
            help
            overlay.
        category:
            group
            label
            (e.g.
            ``"Chat"``,
            ``"Plan"``,
            ``"Tools"``).
    """

    key: str
    action: str
    description: str
    category: str


# R-2026-06-19 (P3-D8):
# the canonical
# list.  The
# ``action_*``
# names
# mirror
# the
# ChatApp
# methods in
# ``manusift.tui.chat_app``.
KEYBINDINGS: tuple[KeyBinding, ...] = (
    # Chat surface
    KeyBinding(
        key="enter",
        action="submit_input",
        description="submit the input line",
        category="Chat",
    ),
    KeyBinding(
        key="ctrl+j",
        action="submit_input",
        description=(
            "submit the input line (alias for Enter; "
            "works in TextArea mode too)"
        ),
        category="Chat",
    ),
    KeyBinding(
        key="ctrl+c",
        action="abort",
        description="abort the current generation",
        category="Chat",
    ),
    KeyBinding(
        key="up",
        action="history_prev",
        description=(
            "recall the previous input from history"
        ),
        category="Chat",
    ),
    KeyBinding(
        key="down",
        action="history_next",
        description=(
            "recall the next input from history"
        ),
        category="Chat",
    ),
    # Plan mode
    KeyBinding(
        key="ctrl+t",
        action="toggle_plan",
        description=(
            "toggle plan mode (pause before tool calls)"
        ),
        category="Plan",
    ),
    # Diagnostics
    KeyBinding(
        key="?",
        action="help",
        description="open this help overlay",
        category="Diagnostics",
    ),
    KeyBinding(
        key="f1",
        action="help",
        description=(
            "open this help overlay (alias for ?)"
        ),
        category="Diagnostics",
    ),
    KeyBinding(
        key="d",
        action="toggle_debug_drawer",
        description=(
            "toggle the raw-JSON debug drawer"
        ),
        category="Diagnostics",
    ),
    # Slash commands
    KeyBinding(
        key="ctrl+/",
        action="palette",
        description=(
            "open the slash-command palette"
        ),
        category="Slash",
    ),
)


def by_category() -> dict[str, list[KeyBinding]]:
    """Group the
    ``KEYBINDINGS``
    by their
    ``category``
    field.

    R-2026-06-19 (P3-D8):
    the
    HelpOverlay
    uses this
    to render
    one table
    per category
    (Chat / Plan /
    Diagnostics
    / Slash).
    """
    out: dict[str, list[KeyBinding]] = {}
    for kb in KEYBINDINGS:
        out.setdefault(kb.category, []).append(kb)
    return out


def format_keybinding_help() -> str:
    """Render the
    keybindings as a
    text report.

    R-2026-06-19 (P3-D8):
    the TUI
    ``HelpOverlay``
    uses this
    function to
    build the
    table cells.
    The CLI can
    also print
    it via
    ``manusift
    --help-keys``.
    """
    lines: list[str] = []
    lines.append("ManuSift keyboard shortcuts")
    lines.append("=" * 32)
    lines.append("")
    for category, kbs in by_category().items():
        lines.append(f"## {category}")
        for kb in kbs:
            # Pad
            # the
            # key
            # to
            # 14
            # chars
            # for
            # a
            # tidy
            # table.
            key_padded = kb.key.ljust(14)
            lines.append(
                f"  {key_padded} {kb.description}"
            )
        lines.append("")
    return "\n".join(lines)
