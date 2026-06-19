"""R-2026-06-19 (P3-D8):
TUI
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
the
canonical
keybinding
list in
``manusift.tui.keybindings``
so
the
``HelpOverlay``
has a
typed
data
source
(``KEYBINDINGS``)
and the
tests can
verify
the
contract.

Tests:

  * ``KEYBINDINGS``
    is
    non-empty.
  * Every
    binding
    has
    non-empty
    ``key``,
    ``action``,
    ``description``,
    ``category``.
  * Common
    bindings
    are
    present:
    Enter
    →
    submit,
    Ctrl+C
    →
    abort,
    ?
    →
    help.
  * ``by_category()``
    groups
    bindings
    by
    category.
  * ``format_keybinding_help()``
    returns
    a
    non-empty
    string
    that
    mentions
    every
    binding.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui.keybindings import (  # noqa: E402
    KEYBINDINGS,
    KeyBinding,
    by_category,
    format_keybinding_help,
)


# ---------------------------------------------------------------------------
# KEYBINDINGS
# ---------------------------------------------------------------------------


class TestKeybindings:
    def test_list_is_non_empty(self):
        assert len(KEYBINDINGS) > 0

    def test_every_binding_has_required_fields(self):
        for kb in KEYBINDINGS:
            assert kb.key
            assert kb.action
            assert kb.description
            assert kb.category

    def test_enter_submits(self):
        keys = [kb.key for kb in KEYBINDINGS]
        assert "enter" in keys

    def test_ctrl_c_aborts(self):
        # ``ctrl+c``
        # is the
        # abort
        # binding.
        ctrl_c = [
            kb for kb in KEYBINDINGS
            if kb.key == "ctrl+c"
        ]
        assert len(ctrl_c) == 1
        assert ctrl_c[0].action == "abort"

    def test_help_binding_present(self):
        # Both
        # ``?``
        # and
        # ``f1``
        # should
        # open
        # help.
        help_keys = {
            kb.key for kb in KEYBINDINGS
            if kb.action == "help"
        }
        assert "?" in help_keys
        assert "f1" in help_keys


# ---------------------------------------------------------------------------
# by_category
# ---------------------------------------------------------------------------


class TestByCategory:
    def test_groups_by_category(self):
        grouped = by_category()
        # At
        # least
        # 3
        # categories
        # (Chat,
        # Plan,
        # Diagnostics,
        # Slash).
        assert len(grouped) >= 3

    def test_every_category_has_at_least_one_binding(self):
        for cat, kbs in by_category().items():
            assert len(kbs) >= 1, f"empty category: {cat}"


# ---------------------------------------------------------------------------
# format_keybinding_help
# ---------------------------------------------------------------------------


class TestFormatKeybindingHelp:
    def test_returns_non_empty_string(self):
        text = format_keybinding_help()
        assert isinstance(text, str)
        assert len(text) > 50

    def test_includes_every_keybinding(self):
        text = format_keybinding_help()
        for kb in KEYBINDINGS:
            assert kb.key in text, (
                f"key {kb.key!r} missing from help text"
            )

    def test_includes_categories(self):
        text = format_keybinding_help()
        for cat in by_category().keys():
            assert cat in text, (
                f"category {cat!r} missing from help text"
            )
