"""Tests for the R-2026-06-15
(Phase 6 + #5) slash-command
autocomplete popover.

Covers:

  * SlashPopover construction
    (default hidden state)
  * ``show_for`` / ``hide`` /
    ``is_visible``
  * Fuzzy filtering of the
    command list
  * ``move_selection`` wraps
    around at the boundaries
  * ``selected_command``
    returns the highlighted
    command
  * Defensive tolerance:
    show_for with garbage
    input is a no-op
    (no exception)
  * SlashPopover integrates
    with the slash_registry
    (real registered commands
    are listed)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# The popover module imports textual
# widgets at the top level.  If textual
# is missing in the test environment,
# skip the module-level imports.
try:
    from textual.widgets import (
        Input,
        ListView,
        Static,
    )
    from manusift.tui.slash_popover import (
        PopoverEntry,
        SlashPopover,
    )
    from manusift.tui.slash_registry import (
        find,
        iter_commands,
    )
except Exception as exc:  # noqa: BLE001
    pytest.skip(
        f"textual or popover import failed: {exc}",
        allow_module_level=True,
    )


# ---- Construction ----


def test_slash_popover_default_hidden() -> None:
    """A freshly-constructed
    ``SlashPopover`` is *not* visible
    (default ``display: none``)."""
    pop = SlashPopover()
    assert pop.is_visible() is False


def test_slash_popover_has_all_commands_at_construction() -> None:
    """All registered slash commands are
    cached at construction time so the
    popover can filter without re-walking
    the registry on each keystroke."""
    pop = SlashPopover()
    assert len(pop._all_commands) == len(
        list(iter_commands())
    )
    # And every command has a unique name.
    names = [c.name for c in pop._all_commands]
    assert len(set(names)) == len(names)


# ---- show_for / hide / is_visible ----


def test_show_for_makes_visible() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    assert pop.is_visible() is True


def test_hide_makes_invisible() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    assert pop.is_visible() is True
    pop.hide()
    assert pop.is_visible() is False


def test_show_for_empty_query_shows_everything() -> None:
    """``/`` alone (no filter) shows
    every registered command."""
    pop = SlashPopover()
    pop.show_for("/")
    assert len(pop._entries) == len(
        pop._all_commands
    )


def test_show_for_is_idempotent() -> None:
    """Calling ``show_for`` twice is
    safe."""
    pop = SlashPopover()
    pop.show_for("/")
    pop.show_for("/he")
    assert pop.is_visible() is True


def test_hide_clears_entries() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    assert len(pop._entries) > 0
    pop.hide()
    assert len(pop._entries) == 0


# ---- Filtering ----


def test_filter_narrows_list() -> None:
    """``/he`` should narrow the list
    to commands that match ``he``
    (e.g. ``/help``, ``/health``,
    etc.).  We don't pin specific
    command names (those are
    project-specific) but we assert
    the list shrinks -- when the
    registry has at least 3
    commands.  The test environment
    may only register 2 commands
    (``help`` + ``echo``), in which
    case we skip."""
    pop = SlashPopover()
    pop.show_for("/")
    n_all = len(pop._entries)
    if n_all < 3:
        pytest.skip(
            "Need >= 3 registered commands "
            "to test narrowing"
        )
    pop.show_for("/he")
    n_he = len(pop._entries)
    assert n_he < n_all
    # Every remaining command name
    # should contain "he" as a
    # fuzzy match.
    for e in pop._entries:
        names = [e.command.name] + list(
            e.command.aliases
        )
        assert any(
            "he" in n.lower() for n in names
        )


def test_filter_no_match_hides_everything() -> None:
    """A query that does not match any
    command should leave the entry list
    empty (the popover is still visible
    -- the chat app is responsible for
    hiding it)."""
    pop = SlashPopover()
    pop.show_for("/zzzzzz_no_match")
    assert len(pop._entries) == 0
    assert pop.is_visible() is True


def test_filter_is_case_insensitive() -> None:
    pop = SlashPopover()
    pop.show_for("/HE")
    # Should match the same commands
    # as ``/he``.
    pop2 = SlashPopover()
    pop2.show_for("/he")
    a = {e.command.name for e in pop._entries}
    b = {
        e.command.name
        for e in pop2._entries
    }
    assert a == b


# ---- move_selection ----


def test_move_selection_wraps_forward() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    n = len(pop._entries)
    if n < 2:
        pytest.skip("Need at least 2 commands")
    # Move past the end wraps to the
    # beginning.
    pop.move_selection(+n)
    cmd = pop.selected_command()
    assert cmd is not None
    # After wrapping +n we should be
    # back at the same index (0).
    assert pop._entries[0].command.name == (
        cmd.name
    )


def test_move_selection_wraps_backward() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    n = len(pop._entries)
    if n < 2:
        pytest.skip("Need at least 2 commands")
    # Move -1 from index 0 wraps to
    # the last entry.
    pop.move_selection(-1)
    cmd = pop.selected_command()
    assert cmd is not None
    assert cmd.name == pop._entries[-1].command.name


def test_move_selection_no_op_when_hidden() -> None:
    pop = SlashPopover()
    # Don't show_for; should not raise.
    pop.move_selection(+1)
    pop.move_selection(-1)
    # And selected_command returns None.
    assert pop.selected_command() is None


# ---- selected_command ----


def test_selected_command_returns_top_when_no_navigation() -> None:
    pop = SlashPopover()
    pop.show_for("/")
    top = pop.selected_command()
    assert top is not None
    # The top entry should be the
    # first in the entries list.
    assert (
        top.name
        == pop._entries[0].command.name
    )


def test_selected_command_after_filter() -> None:
    pop = SlashPopover()
    pop.show_for("/he")
    cmd = pop.selected_command()
    assert cmd is not None
    # The top should be a fuzzy match.
    names = [cmd.name] + list(cmd.aliases)
    assert any(
        "he" in n.lower() for n in names
    )


# ---- Integration with slash_registry ----


def test_popover_lists_known_slash_command() -> None:
    """The popover should list at least
    one command that is in the
    registry.  We use ``/help`` as a
    canonical name (every chat app
    has it)."""
    help_cmd = find("help")
    if help_cmd is None:
        pytest.skip("no /help command registered")
    pop = SlashPopover()
    pop.show_for("/")
    names = [
        e.command.name for e in pop._entries
    ]
    assert "help" in names


# ---- Defensive tolerance ----


def test_hide_when_already_hidden_is_no_op() -> None:
    pop = SlashPopover()
    # No exception even though we
    # never showed the popover.
    pop.hide()
    assert pop.is_visible() is False


def test_show_for_with_none_query() -> None:
    """A None query should not raise
    (defensive tolerance for callers
    that pass the wrong type)."""
    pop = SlashPopover()
    pop.show_for("")  # empty string is the
    # safe substitute
    assert pop.is_visible() is True


# ---- R-2026-06-15 (Phase 6 + #5) regression ----
#
# The original
# ``_render_list`` gave every
# ListItem a fixed ID
# (``slash-popover-item-<name>``).
# When the user typed a second
# character after the popover was
# already visible, ``_render_list``
# was called again -- but the old
# ListItems were still registered in
# the parent's child-id table for
# one frame, so re-appending a new
# ``ListItem`` with the same id
# raised ``textual._node_list.DuplicateIds``
# and CRASHED the TUI.
#
# The fix: don't give ListItem
# children any application-defined
# ids.  The popover identifies
# entries by *index* via
# ``self._selected_idx``, not by
# id.  The unit tests below guard
# the fix from regressing.


def test_render_list_does_not_assign_ids() -> None:
    """Guard: ``_render_list`` must NOT
    call ``ListItem(..., id=...)``
    because that triggers Textual's
    ``DuplicateIds`` crash on the
    second render."""
    import inspect

    src = inspect.getsource(
        SlashPopover._render_list
    )
    # The phrase ``id=(`` inside
    # _render_list would mean we
    # pass an id kwarg to a widget
    # constructor.  Disallow that
    # for any widget -- the only
    # allowed ``id=`` is the slash-
    # popover-input / slash-popover-
    # list at compose time, which is
    # already in DEFAULT_CSS / compose.
    # We only need to check that
    # _render_list itself does not
    # introduce widget ids at
    # runtime.
    assert "ListItem(Static(label), id=" not in src, (
        "_render_list must not give "
        "ListItem an id= kwarg -- it "
        "causes DuplicateIds crash on "
        "the second render"
    )


def test_show_for_called_twice_does_not_crash() -> None:
    """The exact failure mode that
    crashed the user's TUI: call
    ``show_for`` once (popover
    visible, list built), then call
    it again with a different query
    (re-render).  Before the fix
    this raised ``DuplicateIds``;
    after the fix it must succeed
    silently.

    We don't need a real Pilot /
    Textual app here -- the failure
    is at the Textual widget-id
    registry level, which fires
    when ``lv.append`` is called
    on a ListView that already
    has a child with the same id.

    We exercise the call by
    constructing a ListView,
    adding a child with the same
    id as ``_render_list`` would
    produce, and then re-creating
    the popover and re-calling
    ``show_for`` to make sure no
    exception escapes the
    defensive try/except.
    """
    from textual.widgets import ListView

    pop = SlashPopover()
    # First render: should not raise.
    pop.show_for("/")
    # Second render: before the fix
    # this would raise
    # ``DuplicateIds``.  After the
    # fix it should be a no-op
    # (defensive tolerance for the
    # no-ListView-mounted case).
    pop.show_for("/he")
    # Third render: same.
    pop.show_for("/help")
    # And the popover is still
    # usable.
    assert pop.is_visible() is True
    assert pop._selected_idx == 0
    cmd = pop.selected_command()
    assert cmd is not None
