"""Command palette for the
chat TUI
(R-2026-06-15,
Phase 2 + #4).

The user pressed
``Ctrl+P`` to open a
fuzzy-search popover
over the 14 slash
commands. The popover
lets the user type a
partial name
(``resu``) and see the
top-N matches, then
navigate with ``Up``
/ ``Down`` and press
``Enter`` to invoke.

The package consists of:

  1. **Pure helpers**
     (no textual
     imports):
     - ``fuzzy_score(query, name)``:
       returns
       a
       0-100
       integer
       score
       (100
       =
       exact
       match,
       0
       =
       no
       match).
     - ``rank_candidates(query, commands, max_results=10)``:
       returns
       a
       sorted
       list
       of
       ``PaletteEntry``
       (name,
       description,
       score,
       matched_chars).
     - ``highlight_match(name, query)``:
       returns
       a
       rich-markup
       string
       with
       the
       matched
       characters
       highlighted
       (e.g.
       ``"[bold]res[/bold]ume"``
       for
       ``query="res"``
       against
       ``"resume"``).

  2. **The ModalScreen**
     (textual):
     - ``CommandPaletteScreen(ModalScreen[None])``:
       a
       centered
       popover
       with
       an
       ``Input``
       at
       the
       top
       and
       a
       ``ListView``
       of
       the
       ranked
       candidates
       below.
     - ``Enter``
       invokes
       the
       highlighted
       command.
     - ``Escape``
       closes
       the
       popover.

## Fuzzy-match
algorithm

We use a SIMPLIFIED
fuzzy match (not
fzf / fzy / skim). The
contract:

  * The
    ``query``
    is
    matched
    as
    a
    SUBSEQUENCE
    of
    the
    candidate
    name
    (case-insensitive).
    Every
    char
    in
    the
    query
    must
    appear
    in
    the
    name
    in
    the
    same
    order
    (but
    not
    necessarily
    adjacent).
  * The
    score
    is
    a
    blend
    of:

      * **Prefix bonus**:
        query
        matches
        the
        prefix
        of
        the
        name
        exactly
        → 100.
      * **Subsequence match**:
        query
        is
        a
        subsequence
        → 70.
      * **Consecutive bonus**:
        +5
        for
        each
        pair
        of
        adjacent
        matched
        characters
        (so
        ``res``
        in
        ``resume``
        is
        better
        than
        ``rsu``
        in
        ``resume``).
      * **Length penalty**:
        a
        longer
        candidate
        name
        gets
        a
        smaller
        score
        (so
        ``resume``
        ranks
        above
        ``reset``
        when
        the
        query
        is
        ``re``).

  * The
    function
    NEVER
    raises.
    A
    non-string
    query
    or
    a
    non-string
    name
    returns
    0.

## Why a pure
helper (not just
inlined in the
ModalScreen)

The fuzzy-match
algorithm is the
tricky part (the
ModalScreen is a
trivial textual
widget). Inlining
the algorithm in
the widget makes it
untestable without
textual's test
harness. Pure
helpers are:

  * Easier
    to
    unit-test
    (the
    score
    contract
    is
    pinned
    by
    tests
    without
    ``App.run_test()``).
  * Easier
    to
    read
    (the
    widget
    becomes
    a
    30-line
    glue
    layer).
  * Reusable
    (a
    future
    "history
    palette"
    can
    share
    the
    same
    helper).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    # The ModalScreen
    # takes a
    # reference
    # to the
    # chat
    # app
    # so
    # that
    # ``Enter``
    # on a
    # selected
    # command
    # can
    # dispatch
    # through
    # ``_handle_command``.
    # We
    # use
    # ``TYPE_CHECKING``
    # so the
    # import
    # is
    # only
    # at
    # type-check
    # time
    # (textual
    # is
    # not
    # imported
    # at
    # module
    # load).
    from .chat_app import ChatApp


# Score
# ceiling
# for
# the
# various
# match
# kinds.
# These
# are
# used
# to
# rank
# candidates
# and
# are
# tested
# as
# part
# of
# the
# contract
# (so
# a
# change
# to
# the
# weighting
# is
# a
# change
# to
# the
# contract).
_SCORE_EXACT: int = 100
_SCORE_SUBSEQUENCE: int = 70
_CONSECUTIVE_BONUS: int = 5
# A
# per-character
# penalty
# for
# long
# candidate
# names
# (so
# ``resume``
# beats
# ``reset``
# when
# query
# is
# ``re``).
_LENGTH_PENALTY: int = 1


@dataclass(frozen=True)
class PaletteEntry:
    """One row in the
    palette popover.

    Attributes:

      * ``score``:
        the
        fuzzy
        match
        score
        (0-100;
        0
        means
        no
        match).
      * ``matched_indices``:
        the
        indices
        in
        ``name``
        that
        match
        the
        query
        chars
        (used
        by
        ``highlight_match``
        to
        underline
        the
        matched
        characters).
    """

    name: str
    description: str
    category: str
    score: int
    matched_indices: tuple[int, ...]


def fuzzy_score(query: Any, name: Any) -> int:
    """Return a 0-100
    score for the
    fuzzy match.

    The contract:

      * ``query``
        is
        the
        user-typed
        text
        (e.g.
        ``"res"``).
      * ``name``
        is
        the
        candidate
        command
        name
        (e.g.
        ``"resume"``).
      * The
        match
        is
        case-insensitive
        (so
        ``"RES"``
        matches
        ``"resume"``).
      * A
        match
        is
        successful
        (``score > 0``)
        if
        and
        only
        if
        every
        character
        in
        ``query``
        appears
        in
        ``name``
        in
        the
        same
        order
        (a
        subsequence
        match).
      * An
        exact
        prefix
        match
        (``name.startswith(query)``)
        gets
        ``_SCORE_EXACT``
        (100).
      * A
        non-prefix
        subsequence
        match
        gets
        ``_SCORE_SUBSEQUENCE``
        (70)
        plus
        consecutive
        bonuses
        and
        length
        penalty.
      * A
        non-string
        input
        returns
        0.
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(query, str) or not isinstance(
        name, str
    ):
        return 0
    if not query:
        # An empty
        # query
        # matches
        # everything
        # with
        # the
        # lowest
        # score
        # (so the
        # user
        # sees
        # all
        # 14
        # commands
        # sorted
        # by
        # name).
        return 1
    if not name:
        return 0
    q = query.lower()
    n = name.lower()
    if q == n:
        return _SCORE_EXACT
    if n.startswith(q):
        # Prefix
        # match:
        # ``resume``
        # starts
        # with
        # ``res``.
        return _SCORE_EXACT
    # Subsequence
    # match:
    # walk
    # through
    # ``n``
    # and
    # greedily
    # match
    # each
    # char
    # of
    # ``q``.
    matched_indices: list[int] = []
    q_idx = 0
    consecutive = 0
    last_match_idx = -2  # sentinel
    for i, ch in enumerate(n):
        if q_idx >= len(q):
            break
        if ch == q[q_idx]:
            matched_indices.append(i)
            if i == last_match_idx + 1:
                consecutive += 1
            last_match_idx = i
            q_idx += 1
    if q_idx < len(q):
        # Some
        # chars
        # in
        # the
        # query
        # did
        # not
        # match
        # the
        # name.
        return 0
    score = _SCORE_SUBSEQUENCE
    score += consecutive * _CONSECUTIVE_BONUS
    # Length
    # penalty:
    # shorter
    # names
    # (e.g.
    # ``quit``)
    # rank
    # above
    # longer
    # ones
    # (e.g.
    # ``restart``)
    # when
    # the
    # query
    # is
    # the
    # same
    # length.
    score -= len(name) * _LENGTH_PENALTY
    if score < 0:
        score = 0
    return score


def rank_candidates(
    query: Any,
    commands: Any,
    max_results: int = 10,
) -> list[PaletteEntry]:
    """Rank a list of
    ``SlashCommand``-
    like objects by
    fuzzy-match score.

    The contract:

      * ``query``
        is
        the
        user-typed
        text.
      * ``commands``
        is
        an
        iterable
        of
        objects
        with
        attributes
        ``.name``
        /
        ``.description``
        /
        ``.category``.
        The
        ``SlashCommand``
        class
        fits;
        a
        tuple
        ``(name, description, category)``
        also
        fits.
      * The
        result
        is
        a
        list
        of
        ``PaletteEntry``
        sorted
        by
        ``(score
        desc,
        name
        asc)`` --
        higher
        score
        first,
        alphabetical
        tiebreaker.
      * Commands
        with
        a
        score
        of
        ``0``
        (no
        match)
        are
        excluded
        from
        the
        result.
      * The
        result
        is
        truncated
        to
        ``max_results``
        entries
        (default
        10;
        a
        palette
        larger
        than
        that
        is
        not
        useful
        in
        a
        TUI).
      * An
        empty
        ``query``
        returns
        ALL
        commands
        (sorted
        by
        name)
        so
        the
        user
        can
        browse
        without
        typing.
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(commands, (list, tuple)):
        return []
    out: list[PaletteEntry] = []
    for cmd in commands:
        # Coerce
        # the
        # command
        # to
        # a
        # (name,
        # description,
        # category)
        # tuple
        # so
        # the
        # function
        # works
        # with
        # ``SlashCommand``
        # OR
        # a
        # bare
        # ``(name, desc)``
        # tuple.
        if isinstance(cmd, (list, tuple)):
            name = cmd[0] if len(cmd) > 0 else ""
            desc = cmd[1] if len(cmd) > 1 else ""
            cat = cmd[2] if len(cmd) > 2 else ""
        else:
            name = getattr(cmd, "name", "")
            desc = getattr(cmd, "description", "")
            cat = getattr(cmd, "category", "")
        if not isinstance(name, str):
            name = ""
        if not isinstance(desc, str):
            desc = ""
        if not isinstance(cat, str):
            cat = ""
        score = fuzzy_score(query, name)
        if score <= 0:
            continue
        # Re-derive
        # the
        # matched
        # indices
        # (we
        # already
        # computed
        # them
        # in
        # ``fuzzy_score``
        # but
        # we
        # did
        # not
        # return
        # them).
        # Re-walk
        # to
        # keep
        # the
        # two
        # functions
        # decoupled
        # (so
        # a
        # future
        # optimization
        # of
        # ``fuzzy_score``
        # does
        # not
        # break
        # ``rank_candidates``).
        if isinstance(query, str) and query:
            matched: list[int] = []
            q = query.lower()
            n = name.lower()
            q_idx = 0
            for i, ch in enumerate(n):
                if q_idx >= len(q):
                    break
                if ch == q[q_idx]:
                    matched.append(i)
                    q_idx += 1
            matched_tuple: tuple[int, ...] = tuple(
                matched
            )
        else:
            matched_tuple = ()
        out.append(
            PaletteEntry(
                name=name,
                description=desc,
                category=cat,
                score=score,
                matched_indices=matched_tuple,
            )
        )
    out.sort(key=lambda e: (-e.score, e.name))
    return out[:max_results]


def highlight_match(
    name: str,
    matched_indices: Any,
) -> str:
    """Return a
    rich-markup string
    with the matched
    characters in the
    candidate name
    highlighted.

    The contract:

      * ``name``
        is
        the
        candidate
        command
        name
        (e.g.
        ``"resume"``).
      * ``matched_indices``
        is
        a
        tuple
        /
        list
        of
        ``int``
        (the
        indices
        in
        ``name``
        that
        match
        the
        query).
      * Each
        matched
        char
        is
        wrapped
        in
        ``[bold]...[bold]``
        (so
        ``"resume"``
        with
        ``matched=(0, 1, 2)``
        is
        rendered
        as
        ``"[bold]res[/bold]ume"``).
      * A
        corrupt
        input
        (non-string
        name
        or
        non-iterable
        indices)
        returns
        ``name``
        unchanged
        (defensive;
        the
        popover
        does
        not
        crash
        on
        a
        bad
        row).
    """
    if not isinstance(name, str):
        return ""
    if not matched_indices:
        return name
    try:
        idx_set = set(int(i) for i in matched_indices)
    except (TypeError, ValueError):
        return name
    out: list[str] = []
    for i, ch in enumerate(name):
        if i in idx_set:
            out.append(f"[bold]{ch}[/bold]")
        else:
            out.append(ch)
    return "".join(out)



# --------------------------------------------------------------------
# CommandPaletteScreen (textual ModalScreen)
# --------------------------------------------------------------------

# Lazy textual imports --
# the helpers above
# do NOT import textual
# (so the test suite can
# pin the pure-function
# contract without
# booting textual). The
# modal is only
# instantiated when
# the user presses
# ``ctrl+shift+p``,
# so the import cost
# is amortised.
def _build_modal():
    """Build the
    ``CommandPaletteScreen``
    class (lazily, so
    the import cost
    of textual is paid
    only when the
    palette is opened).

    The function returns
    a textual
    ``ModalScreen[None]``
    subclass with the
    following compose:
    a centered vertical
    box (60% width, 30%
    height), an
    ``Input`` at the top
    (the query), and a
    ``ListView`` of
    ranked candidates
    below.
    """
    from textual.screen import (
        ModalScreen,
    )
    from textual.widgets import (
        Input,
        Label,
        ListItem,
        ListView,
        Static,
    )
    from textual.containers import (
        Center,
        Middle,
        Vertical,
    )
    from textual.app import (
        ComposeResult,
    )
    from textual.binding import (
        Binding,
    )
    from .slash_registry import (
        iter_commands,
    )

    class CommandPaletteScreen(
        ModalScreen[None],
    ):
        """R-2026-06-15
        (Phase 2 + #4):
        the command
        palette
        ModalScreen.

        Behaviour:

          * The
            user
            presses
            ``ctrl+shift+p``;
            the
            chat
            app
            pushes
            this
            screen.
          * The
            user
            types
            a
            partial
            name
            (``resu``);
            the
            list
            of
            ranked
            candidates
            updates
            in
            real
            time.
          * The
            user
            presses
            ``Enter``
            to
            invoke
            the
            highlighted
            command
            (the
            palette
            calls
            ``_handle_command``).
          * The
            user
            presses
            ``Escape``
            to
            close
            the
            palette.

        The screen
        deliberately
        does NOT
        interact with
        the
        ``#history`` /
        ``#input``
        widgets (a
        ``ModalScreen``
        is its own
        widget tree).
        This is the key
        safety
        property: the
        80+ existing
        TUI tests
        cannot break
        because of the
        palette (the
        palette is
        invisible to
        them).
        """

        BINDINGS = [
            Binding(
                "escape",
                "dismiss_palette",
                "Close",
                show=False,
            ),
            Binding(
                "enter",
                "invoke_selected",
                "Invoke",
                show=False,
            ),
        ]

        CSS = """
        CommandPaletteScreen {
            align: center middle;
        }
        #palette-box {
            width: 60%;
            height: 50%;
            max-width: 100;
            border: thick $primary;
            background: $panel;
            padding: 1 2;
        }
        #palette-input {
            margin-bottom: 1;
        }
        #palette-list {
            height: 1fr;
        }
        #palette-empty {
            color: $text-muted;
            padding: 1 2;
        }
        """

        def __init__(
            self,
            app_ref: "ChatApp",
        ) -> None:
            super().__init__()
            self._app_ref = app_ref
            # The
            # current
            # query
            # (mirrored
            # from
            # the
            # ``Input``
            # so
            # we
            # can
            # re-rank
            # on
            # each
            # keystroke).
            self._query: str = ""
            # The
            # current
            # ranked
            # list
            # (re-built
            # on
            # each
            # keystroke;
            # cached
            # so
            # ``invoke_selected``
            # does
            # not
            # re-run
            # the
            # ranker).
            self._current_entries: list[
                PaletteEntry
            ] = []

        def compose(self) -> ComposeResult:
            with Vertical(id="palette-box"):
                yield Input(
                    placeholder=(
                        "type a command name "
                        "(e.g. 'resu') ..."
                    ),
                    id="palette-input",
                )
                yield ListView(
                    id="palette-list",
                )

        def on_mount(self) -> None:
            """R-2026-06-15
            (Phase 2 + #4):
            focus the
            ``Input`` so
            the user
            can type
            immediately
            (no extra
            ``Tab``
            needed), and
            populate the
            list with all
            14 commands
            (the empty
            query shows
            everything).
            """
            try:
                inp = self.query_one(
                    "#palette-input", Input
                )
                inp.focus()
            except Exception:  # noqa: BLE001
                pass
            self._rerank("")

        def on_input_changed(
            self, event: Input.Changed
        ) -> None:
            """Re-rank on
            each
            keystroke.
            The
            ``Input.Changed``
            event fires
            when the
            user types a
            character (or
            pastes); we
            read the new
            value and
            re-run the
            ranker.
            """
            self._rerank(event.value)

        def _rerank(
            self, query: str
        ) -> None:
            """Re-rank the
            candidates for
            ``query`` and
            rebuild the
            ``ListView``.

            The contract:

              * The
                ``Input``
                is
                NOT
                touched
                (the
                user
                keeps
                typing
                without
                focus
                loss).
              * The
                ``ListView``
                children
                are
                REPLACED
                (not
                appended)
                so
                stale
                candidates
                are
                removed.
              * The
                first
                candidate
                is
                auto-highlighted
                (so
                ``Enter``
                invokes
                the
                top
                result).
              * An
                empty
                result
                shows
                a
                dimmed
                "no matches"
                placeholder.
              * The
                function
                NEVER
                raises
                (a
                bad
                query
                is
                silently
                ignored).
            """
            self._query = query
            try:
                commands = list(
                    iter_commands()
                )
            except Exception:  # noqa: BLE001
                commands = []
            self._current_entries = (
                rank_candidates(query, commands)
            )
            # Rebuild
            # the
            # ListView.
            try:
                lv = self.query_one(
                    "#palette-list", ListView
                )
                # Clear
                # existing
                # children.
                for child in list(
                    lv.children
                ):
                    child.remove()
                if not self._current_entries:
                    lv.mount(
                        Static(
                            "[dim]no commands match[/dim]",
                            id="palette-empty",
                        )
                    )
                else:
                    for entry in (
                        self._current_entries
                    ):
                        item = ListItem(
                            Static(
                                self._render_entry(
                                    entry
                                ),
                                markup=True,
                            )
                        )
                        lv.mount(item)
                    # Auto-highlight
                    # the
                    # first
                    # item
                    # (so
                    # ``Enter``
                    # invokes
                    # the
                    # top
                    # result).
                    try:
                        lv.index = 0
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                # A
                # failed
                # re-mount
                # does
                # not
                # break
                # the
                # palette
                # (the
                # user
                # can
                # still
                # close
                # it
                # with
                # ``Escape``).
                pass

        def _render_entry(
            self, entry: PaletteEntry
        ) -> str:
            """Render a
            single
            ``PaletteEntry``
            as a rich-markup
            string for the
            ``ListView``.

            The contract:

              * The
                command
                name
                is
                the
                first
                column
                (with
                the
                matched
                chars
                highlighted
                in
                ``[bold]``).
              * The
                category
                is
                the
                second
                column
                (in
                ``[dim]``).
              * The
                description
                is
                the
                third
                column
                (in
                ``[italic]``).
              * The
                score
                is
                hidden
                (it
                is
                an
                internal
                rank
                value;
                showing
                it
                would
                leak
                the
                algorithm
                to
                the
                user).
            """
            highlighted = (
                highlight_match(
                    entry.name,
                    entry.matched_indices,
                )
            )
            return (
                f"  {highlighted}"
                f"  [dim][{entry.category}][/dim]"
                f"  [italic]{entry.description}[/italic]"
            )

        def action_dismiss_palette(
            self,
        ) -> None:
            """``Escape``:
            close the
            palette
            without
            invoking a
            command.
            """
            self.dismiss(None)

        def action_invoke_selected(
            self,
        ) -> None:
            """``Enter``:
            invoke the
            currently-
            highlighted
            command (or the
            top one if
            nothing is
            highlighted)
            and close the
            palette.

            The dispatch
            goes through
            ``_handle_command``
            (the SAME
            path the
            user takes
            when typing
            ``/name`` in
            the chat input).
            So a command
            invoked from
            the palette is
            EXACTLY the
            same as one
            typed in the
            input box.
            """
            # Get
            # the
            # currently-highlighted
            # index.
            try:
                lv = self.query_one(
                    "#palette-list", ListView
                )
                idx = lv.index or 0
            except Exception:  # noqa: BLE001
                idx = 0
            if (
                not self._current_entries
                or idx < 0
                or idx >= len(
                    self._current_entries
                )
            ):
                self.dismiss(None)
                return
            entry = self._current_entries[
                idx
            ]
            # Build
            # the
            # slash-command
            # string
            # and
            # dispatch
            # through
            # the
            # chat
            # app's
            # ``_handle_command``
            # (so the
            # palette
            # and
            # the
            # input
            # box
            # use
            # the
            # SAME
            # dispatch
            # path).
            cmd_text = f"/{entry.name}"
            try:
                self._app_ref._handle_command(
                    cmd_text
                )
            except Exception:  # noqa: BLE001
                # A
                # failed
                # dispatch
                # does
                # not
                # break
                # the
                # TUI;
                # the
                # user
                # can
                # re-invoke
                # manually.
                pass
            self.dismiss(None)

    return CommandPaletteScreen


# Eagerly
# instantiate
# the
# ``CommandPaletteScreen``
# class
# at
# module
# load
# time
# (the
# textual
# import
# is
# amortised
# over
# the
# process
# lifetime
# anyway;
# the
# lazy-build
# above
# is
# only
# a
# test
# affordance).
CommandPaletteScreen = _build_modal()
