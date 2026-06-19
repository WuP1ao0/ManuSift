"""Input-box UX helpers for
the chat TUI
(R-2026-06-15, Phase 2 +
#1).

The chat TUI's ``Input``
field is bare-metal
textual:
``Enter`` submits,
``Backspace`` deletes.
This module adds three
UX niceties (as pure
helpers that the chat
TUI can wire in
incrementally):

  1. **Slash-command
     autocomplete.**
     When the user types
     ``/`` followed by
     a partial command
     name, return a
     list of
     ``(name,
     description)``
     candidates. The
     chat TUI can
     render them in a
     popover / ``ListView``
     below the input.
  2. **Input history
     recall.** Up/Down
     arrows (when the
     input is empty or
     the cursor is at
     the start/end)
     recall the
     previous /
     next
     command. The
     history is
     bounded
     (default 200
     entries) and
     persisted
     to
     disk
     so it
     survives
     a
     restart.
  3. **Multi-line
     paste.**
     If the
     input
     contains
     a
     newline
     (``\\n``)
     it is
     detected
     and
     can
     be
     sent
     as
     a
     multi-line
     user
     message
     (the
     LLM
     already
     supports
     this;
     the
     chat
     TUI
     just
     needs
     to
     NOT
     strip
     newlines).

All three are **pure
functions** (no textual
imports, no ChatApp
coupling). Tests can
pin the contract
independently of the
chat TUI.

## Slash-command
autocomplete

``filter_slash_candidates(text, commands)``
takes the current
input value and the
list of registered
``(name, description)``
tuples, and returns a
filtered + sorted list
of matches.

The matching rules:

  * ``text``
    must
    start
    with
    ``/``
    (otherwise
    the
    function
    returns
    ``[]``
    -- not
    a
    slash
    command).
  * The
    command
    name
    must
    start
    with
    ``text[1:]``
    (case-insensitive).
  * A
    command
    with
    a
    name
    that
    is
    a
    PREFIX
    of
    ``text[1:]``
    is
    ALSO
    a
    match
    (e.g.
    ``text="/resu"``
    matches
    ``/resume``).
  * The
    match
    is
    sorted
    by
    name
    length
    (shortest
    first),
    then
    alphabetically.
  * The
    function
    NEVER
    raises.
    A
    corrupt
    input
    (non-string
    or
    a
    non-list
    ``commands``)
    is
    treated
    as
    no
    candidates.

## Input history
recall

``InputHistory`` is a
class that wraps a
``collections.deque``
(bounded to a max
length, default 200).
The chat TUI calls
``append(text)`` after
each submission, and
``recall_prev()`` /
``recall_next()`` to
walk the history.

The contract:

  * ``append(text)``
    adds
    a
    new
    entry.
    Empty
    strings
    are
    NOT
    added
    (so
    the
    user
    does
    not
    pollute
    the
    history
    with
    blank
    ``Enter``
    presses).
  * ``append(text)``
    is
    idempotent
    w.r.t.
    the
    most-recent
    entry
    (so
    a
    user
    who
    presses
    Up
    and
    then
    re-submits
    does
    not
    see
    two
    copies
    of
    the
    same
    line
    in
    the
    history).
  * ``recall_prev()``
    walks
    BACKWARDS
    in
    the
    history
    (most-recent
    first).
    It
    returns
    ``None``
    when
    the
    user
    has
    already
    reached
    the
    oldest
    entry.
  * ``recall_next()``
    walks
    FORWARDS.
    After
    the
    most-recent
    entry
    it
    returns
    ``None``
    (the
    user
    can
    re-type
    a
    fresh
    command).
  * The
    current
    cursor
    is
    tracked
    by
    a
    private
    index.
    The
    index
    is
    reset
    by
    ``reset_cursor()``
    (called
    when
    the
    user
    types
    a
    new
    character,
    so
    the
    next
    ``Up``
    starts
    from
    the
    most-recent).
  * The
    history
    can
    be
    persisted
    to
    / loaded
    from
    a
    JSON
    file
    via
    ``save()`` /
    ``load()``
    so
    the
    history
    survives
    a
    restart.
"""
from __future__ import annotations

import json
from collections import (
    deque,
)
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------
# Slash-command autocomplete
# --------------------------------------------------------------------


@dataclass(frozen=True)
class SlashCandidate:
    """One row in the
    autocomplete
    popover.
    """

    name: str
    description: str

    def to_pair(self) -> tuple[str, str]:
        return (self.name, self.description)


def filter_slash_candidates(
    text: Any,
    commands: Any,
) -> list[SlashCandidate]:
    """Return the
    ``SlashCandidate``
    list that matches
    ``text`` (a partial
    slash command).

    The contract:

      * ``text``
        must
        be
        a
        ``str``
        starting
        with
        ``/``
        (otherwise
        return
        ``[]``).
      * ``commands``
        must
        be
        an
        iterable
        of
        ``(name, description)``
        tuples;
        non-iterable
        or
        non-list
        inputs
        yield
        ``[]``.
      * A
        command
        whose
        name
        starts
        with
        ``text[1:]``
        (case-insensitive)
        is
        a
        match.
      * A
        command
        whose
        name
        is
        a
        prefix
        of
        ``text[1:]``
        is
        ALSO
        a
        match
        (so
        ``/resu``
        matches
        ``/resume``
        even
        though
        the
        prefix
        is
        4
        characters
        while
        the
        command
        is
        6).
      * Results
        are
        sorted
        by
        ``(name_length,
        name)``
        (shorter
        names
        first;
        alphabetical
        tiebreaker).
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(text, str):
        return []
    if not text.startswith("/"):
        return []
    if not isinstance(commands, (list, tuple)):
        return []
    prefix = text[1:].lower()
    out: list[SlashCandidate] = []
    for cmd in commands:
        if not isinstance(cmd, (list, tuple)) or (
            len(cmd) < 1
        ):
            continue
        name = cmd[0]
        if not isinstance(name, str):
            continue
        # ``name``
        # starts
        # with
        # ``prefix``
        # OR
        # ``prefix``
        # starts
        # with
        # ``name``
        # (e.g.
        # ``text="/re"``
        # matches
        # ``/resume``
        # because
        # the
        # user
        # has
        # only
        # typed
        # 2
        # characters
        # of
        # the
        # command).
        if (
            name.lower().startswith(prefix)
            or prefix.startswith(name.lower())
        ):
            desc = (
                cmd[1] if len(cmd) > 1 else ""
            )
            if not isinstance(desc, str):
                desc = ""
            out.append(
                SlashCandidate(
                    name=name,
                    description=desc,
                )
            )
    out.sort(key=lambda c: (len(c.name), c.name))
    return out


def render_completion_hint(
    candidates: list[SlashCandidate],
    max_rows: int = 5,
) -> str:
    """Format the
    autocomplete popover
    as a multi-line text
    block (the chat TUI
    renders it above or
    below the input).

    The contract:

      * ``candidates``
        is
        a
        list
        of
        ``SlashCandidate``
        (the
        output
        of
        ``filter_slash_candidates``).
      * At
        most
        ``max_rows``
        candidates
        are
        shown
        (default
        5;
        a
        popover
        larger
        than
        that
        is
        not
        useful
        in
        a
        TUI).
      * Each
        line
        is
        ``"  /<name>  -- <description>"``
        so
        the
        popover
        aligns
        with
        the
        typed
        ``/name``
        in
        the
        input.
      * An
        empty
        ``candidates``
        list
        returns
        ``""``
        (the
        chat
        TUI
        hides
        the
        popover).
    """
    if not candidates:
        return ""
    rows = candidates[:max_rows]
    lines = [
        f"  /{c.name}  -- {c.description}"
        for c in rows
    ]
    if len(candidates) > max_rows:
        lines.append(
            f"  ... and "
            f"{len(candidates) - max_rows} more"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------
# Input history
# --------------------------------------------------------------------


@dataclass
class InputHistory:
    """A bounded
    command-history
    ring buffer
    with recall
    semantics.

    The chat TUI
    instantiates one
    ``InputHistory``
    per session and
    persists it to
    disk via
    ``save()`` /
    ``load()`` (the
    same JSONL
    pattern the
    ``SessionLog``
    uses).

    The deque is bounded
    to ``maxlen``
    entries
    (default 200);
    older entries
    are dropped when
    a new entry is
    appended.
    """

    entries: deque[str] = field(
        default_factory=lambda: deque(maxlen=200)
    )
    _cursor: int = -1  # -1 = "below the bottom"
    _pending: str = ""  # the text the user was typing before recall

    def append(self, text: str) -> None:
        """Add a new entry
        to the history.

        The contract:

          * The
            text
            is
            stripped
            (a
            whitespace-only
            string
            becomes
            ``""``
            and
            is
            NOT
            added).
          * Empty
            strings
            are
            NOT
            added
            (so
            the
            user
            does
            not
            pollute
            the
            history
            with
            blank
            ``Enter``
            presses).
          * The
            most-recent
            entry
            is
            de-duplicated
            (so
            a
            user
            who
            presses
            ``Up`` and
            then
            re-submits
            does
            not
            see
            two
            copies
            of
            the
            same
            line).
          * The
            cursor
            is
            reset
            to
            ``-1``
            (the
            user
            has
            not
            started
            walking
            the
            history
            yet).
        """
        text = text.strip()
        if not text:
            return
        # De-dup:
        # if
        # ``text``
        # is
        # the
        # same
        # as
        # the
        # most-recent
        # entry,
        # do
        # not
        # add
        # a
        # duplicate.
        if self.entries and self.entries[-1] == text:
            self._cursor = -1
            self._pending = ""
            return
        self.entries.append(text)
        self._cursor = -1
        self._pending = ""

    def recall_prev(
        self, current_text: str = ""
    ) -> str | None:
        """Walk one step
        backwards in the
        history.

        The first call
        (when ``_cursor``
        is ``-1``) captures
        the user's
        current text
        (``current_text``)
        in ``_pending``
        so the user can
        return to it
        with
        ``recall_next()``
        after walking to
        the bottom.

        Returns the
        recalled text, or
        ``None`` if
        the user has
        already reached
        the oldest entry.
        """
        if not self.entries:
            return None
        if self._cursor == -1:
            # First
            # call
            # after
            # a
            # submission:
            # capture
            # the
            # current
            # text
            # so
            # the
            # user
            # can
            # return
            # to
            # it.
            self._pending = current_text
            self._cursor = len(self.entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        else:
            # Already
            # at
            # the
            # oldest
            # entry;
            # stay
            # put.
            return None
        return self.entries[self._cursor]

    def recall_next(self) -> str | None:
        """Walk one step
        forwards in the
        history.

        Returns the
        recalled text, or
        ``None`` if
        the user has
        already walked
        past the most-
        recent entry
        (in which case
        the user is
        back to the
        ``_pending``
        text they were
        typing before
        the recall).
        """
        if self._cursor == -1:
            return None
        if self._cursor < len(self.entries) - 1:
            self._cursor += 1
            return self.entries[self._cursor]
        # Already
        # at
        # the
        # most-recent
        # entry;
        # return
        # the
        # pending
        # text
        # and
        # reset.
        self._cursor = -1
        return self._pending

    def reset_cursor(self) -> None:
        """Reset the recall
        cursor (called
        when the user
        types a new
        character so the
        next ``Up``
        starts from the
        most-recent
        entry).
        """
        self._cursor = -1
        self._pending = ""

    def save(self, path: Path) -> None:
        """Persist the
        history to a
        JSON file.

        A failure (disk
        full, permission
        denied) is logged
        and swallowed --
        the in-memory
        history is still
        usable in the
        current session.
        """
        try:
            path.parent.mkdir(
                parents=True, exist_ok=True
            )
            path.write_text(
                json.dumps(
                    list(self.entries),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            return

    def load(self, path: Path) -> None:
        """Load the
        history from a
        JSON file.

        A missing or
        corrupt file is
        treated as an
        empty history
        (the function
        never raises).
        """
        if not path.exists():
            return
        try:
            data = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, list):
            return
        # Replace
        # the
        # entries
        # with
        # the
        # loaded
        # ones
        # (rebuild
        # the
        # deque
        # so
        # the
        # maxlen
        # bound
        # is
        # respected).
        self.entries = deque(
            (e for e in data if isinstance(e, str)),
            maxlen=self.entries.maxlen,
        )
        self._cursor = -1
        self._pending = ""

    def __len__(self) -> int:
        return len(self.entries)

    def most_recent(
        self, n: int = 5
    ) -> list[str]:
        """Return the
        ``n`` most-
        recent entries
        (most-recent
        first) for
        debugging /
        tests.
        """
        return list(self.entries)[-n:][::-1]


# --------------------------------------------------------------------
# Multi-line paste detection
# --------------------------------------------------------------------


def is_multiline(text: Any) -> bool:
    """``True`` if
    ``text`` contains
    a newline (the
    user pasted a
    multi-line
    block).

    The contract:

      * ``text``
        must
        be
        a
        ``str``;
        any
        non-string
        is
        ``False``
        (defensive
        default).
      * A
        single-line
        string
        (no
        ``\n``)
        is
        ``False``.
      * A
        multi-line
        string
        (one
        or
        more
        ``\n``)
        is
        ``True``.
      * ``\r\n``
        (Windows
        line
        endings)
        is
        also
        detected
        (we
        strip
        ``\r``
        before
        checking).
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(text, str):
        return False
    # Normalize
    # Windows
    # line
    # endings.
    normalized = text.replace("\r\n", "\n")
    return "\n" in normalized
