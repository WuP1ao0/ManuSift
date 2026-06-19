"""Slash-command autocomplete popover (R-2026-06-15, Phase 6 + #5).

When the user types ``/`` in the chat input
the *slash-command popover* drops down
beneath the input, lists every registered
slash command, fuzzy-filters the list as the
user keeps typing, and on ``Enter`` inserts
the chosen command name back into the main
input (e.g. ``/help ``).  ``Esc`` dismisses
the popover without changing the main input
value.

The popover is implemented as a *regular
``Widget``* (not a ``ModalScreen``) so the
chat app does not lose its layout.  The
popover uses CSS ``position: absolute`` to
float directly under the ``#input`` widget.

Design note
-----------

The popover does **not** contain its own
``Input``.  The main ``#input`` widget
retains focus while the popover is visible;
the chat app re-renders the popover's
``ListView`` on every ``Input.Changed`` event.
This avoids the focus-management pitfalls of
a popover-with-its-own-input (a common
textual anti-pattern).

Comparison with the existing command palette
(``manusift/tui/command_palette.py``):

  * The command palette is a *full-screen
    modal* that **invokes** a command
    immediately on selection.  Bound to
    ``ctrl+shift+p``.
  * The slash popover is a *floats-under-
    input popover* that **fills the input
    with a command name** (the user
    presses Enter again to actually invoke
    it).  Bound to typing ``/`` in the
    input.

Both reuse the same ``slash_registry`` so
the 14 commands, their aliases, and their
descriptions stay in sync.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from .slash_registry import (
    SlashCommand,
    iter_commands,
)

log = logging.getLogger(__name__)


# ---- Fuzzy match (light) ----
#
# Re-use the same simple subsequence score
# the command palette uses (it is exported
# as ``fuzzy_score``).  Import lazily so a
# crash in the palette does not break the
# popover.
try:
    from .command_palette import (
        fuzzy_score as _fuzzy_score,
    )
except Exception:  # noqa: BLE001
    # Defensive fallback: linear contains
    # match.  The popover still works, just
    # without fuzzy ranking.
    def _fuzzy_score(query: str, name: str) -> int:
        if not query:
            return 0
        if query in name:
            return 100 - len(name)
        return -1


@dataclass(frozen=True)
class PopoverEntry:
    """One row in the popover list."""

    command: SlashCommand
    score: int


# ---- Popover widget ----


class SlashPopover(Vertical):
    """Floats below the chat input, shows the
    registered slash commands, fuzzy-filters
    on the typed query.

    The popover is mounted by the chat app
    via ``app.mount(SlashPopover(), ...)``
    *once*; the chat app then calls
    ``popover.show_for(query)`` /
    ``popover.hide()`` to toggle visibility.

    The popover has NO own ``Input`` -- the
    main ``#input`` retains focus and the
    popover reflects the current value on
    every ``Input.Changed`` event (driven by
    the chat app).

    The popover does NOT call any handler.
    It only emits a ``SlashChosen`` message
    containing the chosen ``SlashCommand``;
    the chat app decides what to do (insert
    the name into the main input).
    """

    DEFAULT_CSS = """
    SlashPopover {
        height: auto;
        max-height: 14;
        width: 60;
        /* R-2026-06-15 (Phase 6 + #5):
           use plain colour values
           instead of the
           ``$mocha-*`` theme
           variables -- those
           are defined in
           ``chat_app.py``'s
           DEFAULT_CSS and are
           not visible at
           module-scope CSS
           evaluation time.  The
           popover is mounted
           inside the chat app
           so the colours will
           still match the
           theme visually
           (mocha-mantle ≈
           #181825, mocha-mauve
           ≈ #cba6f7). */
        background: #181825;
        border: round #cba6f7;
        padding: 0 1;
        display: none;
    }
    SlashPopover.-visible {
        display: block;
    }
    #slash-popover-list {
        height: auto;
        max-height: 12;
        background: #181825;
    }
    #slash-popover-list > ListItem {
        padding: 0 1;
    }
    #slash-popover-list > ListItem.-highlighted {
        background: #313244;
    }
    .slash-popover-hint {
        color: #a6adc8;
        text-style: italic;
    }
    """

    class SlashChosen(Message):
        """Posted when the user picks a command
        (Enter on a ListItem, or click).

        The chat app should *insert* the
        command's name into the main input
        and then dismiss the popover.  The
        popover does NOT call the handler
        itself -- that keeps it consistent
        with typing the command manually and
        pressing Enter.
        """

        def __init__(
            self, command: SlashCommand
        ) -> None:
            super().__init__()
            self.command = command

    class SlashCancelled(Message):
        """Posted when the user presses Esc.

        The chat app dismisses the popover
        but keeps whatever the user has
        already typed in the main input
        (e.g. the ``/`` itself)."""

        def __init__(self) -> None:
            super().__init__()

    def __init__(self) -> None:
        super().__init__(id="slash-popover")
        # The current list of entries (after
        # filtering).  Empty when the popover
        # is hidden.
        self._entries: list[PopoverEntry] = []
        # All registered commands, computed
        # once at mount.  The popover reads
        # from this and re-ranks on each
        # keystroke.
        self._all_commands: list[
            SlashCommand
        ] = list(iter_commands())
        # The currently-highlighted index
        # in ``_entries``.  We track this
        # on the popover itself (not just on
        # the ListView) so the popover
        # works in test contexts where the
        # ListView is not mounted (e.g.
        # unit tests that don't run a Textual
        # Pilot).  ``None`` means "not
        # highlighted yet".
        self._selected_idx: int | None = None

    # ---- Compose ----

    def compose(self) -> ComposeResult:
        yield Static(
            "Enter to insert  |  Esc to dismiss",
            id="slash-popover-hint",
            classes="slash-popover-hint",
        )
        yield ListView(id="slash-popover-list")

    # ---- Public API ----

    def show_for(self, query: str) -> None:
        """Show the popover and filter its
        list to ``query``.

        ``query`` is the *current value of
        the main input* (including the
        leading ``/``).  We strip the ``/``
        and use the remainder as the
        fuzzy-search term.

        Idempotent: calling ``show_for`` when
        the popover is already visible is a
        no-op except for re-filtering.
        """
        self._rebuild(query)
        # Mark visible via CSS class so the
        # default ``display: none`` is
        # overridden.
        if "-visible" not in self.classes:
            self.add_class("-visible")
        # We do NOT transfer focus -- the
        # main ``#input`` keeps focus.  All
        # keystrokes (filter, Enter, Esc) go
        # through the main input; we
        # intercept them at the chat-app
        # level.

    def hide(self) -> None:
        """Hide the popover.  Clears the
        filter list and removes the
        ``-visible`` CSS class."""
        self._entries = []
        try:
            lv = self.query_one(
                "#slash-popover-list", ListView
            )
            lv.clear()
        except Exception:  # noqa: BLE001
            pass
        if "-visible" in self.classes:
            self.remove_class("-visible")

    def is_visible(self) -> bool:
        return "-visible" in self.classes

    def selected_command(self) -> SlashCommand | None:
        """Return the currently-highlighted
        ``SlashCommand`` in the popover's
        ``ListView``, or ``None`` if the
        popover is hidden or has no
        entries."""
        if not self.is_visible():
            return None
        if not self._entries:
            return None
        # Prefer the popover's own index
        # (always present, even in
        # test contexts without a mounted
        # ListView).  Fall back to the
        # ListView's index for the
        # in-app case.
        idx = self._selected_idx
        if idx is None:
            try:
                lv = self.query_one(
                    "#slash-popover-list",
                    ListView,
                )
                idx = (
                    lv.index
                    if lv.index is not None
                    else 0
                )
            except Exception:  # noqa: BLE001
                idx = 0
        if 0 <= idx < len(self._entries):
            return self._entries[idx].command
        return None

    def move_selection(self, delta: int) -> None:
        """Move the popover's ListView
        selection by ``delta`` (typically
        ``+1`` or ``-1``).  Wraps around.
        No-op if the popover is hidden or
        has fewer than 2 entries."""
        if (
            not self.is_visible()
            or len(self._entries) < 1
        ):
            return
        # Update our own index first.
        if self._selected_idx is None:
            self._selected_idx = 0
        n = len(self._entries)
        self._selected_idx = (
            self._selected_idx + delta
        ) % n
        # Also poke the ListView so the
        # highlight visual is in sync
        # (no-op when the ListView is
        # not mounted).
        try:
            lv = self.query_one(
                "#slash-popover-list", ListView
            )
            lv.index = self._selected_idx
        except Exception:  # noqa: BLE001
            pass

    # ---- Filtering ----

    def _rebuild(self, query: str) -> None:
        """Recompute the entry list and
        re-render the ListView."""
        q = (query or "").lstrip("/").lower()
        ranked: list[PopoverEntry] = []
        for cmd in self._all_commands:
            # Score the primary name and
            # every alias.  Take the best.
            names = [cmd.name] + list(
                cmd.aliases
            )
            if q:
                # Real filter: the fuzzy
                # score is 0 for "no match"
                # so we use ``> 0`` to
                # detect a real hit.
                best = max(
                    (
                        _fuzzy_score(q, n)
                        for n in names
                    ),
                    default=0,
                )
                if best <= 0:
                    continue
            else:
                # Empty query -- show all
                # commands with score 0.
                best = 0
            ranked.append(
                PopoverEntry(
                    command=cmd, score=best
                )
            )
        # Sort: higher score first, then
        # registration order.  Stable sort
        # via Python's Timsort on a
        # (score, idx) tuple.
        ranked.sort(
            key=lambda e: (-e.score, 0)
        )
        self._entries = ranked
        # Reset the selection if the new
        # list is empty.
        if not ranked:
            self._selected_idx = None
        self._render_list()

    def _render_list(self) -> None:
        """Rebuild the ListView rows from
        ``self._entries``.

        R-2026-06-15 (Phase 6 + #5):
        fix a Textual ``DuplicateIds``
        crash that happens when the user
        types more characters after the
        popover is already visible.
        ``ListView.clear()`` removes the
        children from the visual tree
        but the widget *IDs* are still
        registered for one frame, so
        re-appending a ListItem with the
        same ID (``slash-popover-item-help``)
        raises ``DuplicateIds``.

        The fix is to NOT give the
        ListItem children any
        application-defined IDs.  The
        popover does not need them --
        the highlighted command is
        identified by index, and
        ``selected_command()`` already
        returns the right
        ``SlashCommand`` via
        ``self._selected_idx``.
        """
        try:
            lv = self.query_one(
                "#slash-popover-list", ListView
            )
        except Exception:  # noqa: BLE001
            lv = None
        if lv is not None:
            lv.clear()
        for entry in self._entries:
            label = (
                f"/{entry.command.name}  "
                f"-- {entry.command.description}"
            )
            if lv is not None:
                # R-2026-06-15 (Phase 6 + #5):
                # no ``id=`` here -- see
                # the docstring above.  The
                # ListItem's parent ListView
                # index is the source of
                # truth for which entry the
                # user is on.
                lv.append(ListItem(Static(label)))
        # Highlight the first item so the
        # user can press Enter immediately
        # to insert the top match.
        if self._entries:
            self._selected_idx = 0
            if lv is not None:
                lv.index = 0
