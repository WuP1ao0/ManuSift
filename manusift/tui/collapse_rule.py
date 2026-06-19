"""Auto-collapse rule for
``ToolTraceBlock``
(R-2026-06-15, Phase 2 +
#2).

The chat TUI can grow
unbounded over a long
session: a 30-turn
chat has 30 turn
blocks, each of which
can be 5-20 lines tall
when expanded. The
visible region
becomes unmanageable
once the chat scrolls
past the most recent
~2 turns.

The fix: as the chat
grows, OLDER turns
auto-collapse so the
visible region stays
focused on the most
recent turns. The
rule is encoded as a
pure function so
tests can pin the
threshold.

## The rule

``should_collapse_new_turn(num_existing_turns)``
returns ``True`` if the
NEXT turn block (the
one being created
right now) should
default to
``collapsed=True``.

The contract:

  * 0
    existing
    turns:
    the
    first
    turn
    is
    NOT
    collapsed
    (the
    user
    just
    sent
    their
    first
    message
    and
    needs
    to
    see
    the
    tool
    calls
    in
    context).
  * 1
    to
    4
    existing
    turns:
    the
    new
    turn
    is
    NOT
    collapsed
    (the
    visible
    region
    is
    still
    small
    enough
    to
    show
    every
    turn
    expanded).
  * 5
    to
    9
    existing
    turns:
    the
    new
    turn
    is
    collapsed
    (the
    chat
    is
    getting
    long;
    older
    turns
    should
    yield
    screen
    real
    estate
    to
    the
    most
    recent
    one).
  * 10+
    existing
    turns:
    the
    new
    turn
    is
    collapsed
    (same
    rationale
    as
    5+;
    the
    threshold
    is
    a
    soft
    one).

The function NEVER
raises. A non-int
``num_existing_turns``
(e.g. ``None``) is
treated as ``0`` (the
user is in their first
turn).
"""
from __future__ import annotations


# The
# threshold
# is
# a
# soft
# constant.
# It
# is
# the
# ONLY
# piece
# of
# magic
# in
# this
# module.
# Bumping
# it
# would
# let
# the
# visible
# region
# grow
# further
# before
# collapsing;
# lowering
# it
# would
# collapse
# sooner.
# The
# default
# (5)
# is
# a
# reasonable
# "long
# enough
# that
# auto-collapse
# helps"
# threshold
# (4-5
# turns
# is
# usually
# enough
# to
# fill
# a
# chat
# window
# at
# 20-30
# lines/turn).
_AUTO_COLLAPSE_THRESHOLD: int = 5


def should_collapse_new_turn(
    num_existing_turns: int,
) -> bool:
    """``True`` if the
    next turn block
    should default
    to ``collapsed=True``.

    The contract:

      * ``num_existing_turns``
        is
        an
        ``int``
        (the
        count
        of
        turn
        blocks
        already
        in
        the
        chat
        before
        the
        new
        one
        is
        created).
      * The
        return
        is
        ``False``
        for
        ``num_existing_turns < 5``
        and
        ``True``
        for
        ``num_existing_turns >= 5``.
      * A
        non-int
        input
        (e.g.
        ``None``
        or
        a
        string)
        is
        treated
        as
        ``0``
        (the
        first
        turn
        is
        always
        expanded).
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(num_existing_turns, int):
        return False
    if num_existing_turns < 0:
        return False
    return (
        num_existing_turns >= _AUTO_COLLAPSE_THRESHOLD
    )
