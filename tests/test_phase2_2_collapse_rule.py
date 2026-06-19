"""Tests for the R-2026-06-15
(Phase 2 + #2) auto-
collapse rule.

Covers:

  * ``should_collapse_new_turn``
    threshold
    (the
    5-turn
    boundary).
  * Defensive
    tolerance
    (non-int
    input
    is
    treated
    as
    ``0``
    so
    the
    first
    turn
    is
    always
    expanded).

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

import pytest

from manusift.tui.collapse_rule import (
    _AUTO_COLLAPSE_THRESHOLD,
    should_collapse_new_turn,
)


# --------------------------------------------------------------------
# should_collapse_new_turn: threshold
# --------------------------------------------------------------------


def test_first_turn_not_collapsed():
    """The first turn
    (0 existing
    turns) is NOT
    collapsed -- the
    user just sent
    their first
    message and
    needs to see the
    tool calls in
    context.
    """
    assert (
        should_collapse_new_turn(0) is False
    )


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
def test_below_threshold_not_collapsed(n: int):
    """A new turn is
    NOT collapsed
    when there are
    fewer than
    ``_AUTO_COLLAPSE_THRESHOLD``
    existing turns
    (the visible
    region is still
    small enough to
    show every turn
    expanded).
    """
    assert (
        should_collapse_new_turn(n) is False
    )


@pytest.mark.parametrize("n", [5, 6, 7, 8, 9])
def test_at_or_above_threshold_collapsed(n: int):
    """A new turn IS
    collapsed when
    there are
    ``_AUTO_COLLAPSE_THRESHOLD``
    or more existing
    turns (the chat
    is getting
    long; older
    turns should
    yield screen
    real estate to
    the most recent
    one).
    """
    assert (
        should_collapse_new_turn(n) is True
    )


@pytest.mark.parametrize("n", [10, 50, 100, 999])
def test_far_above_threshold_still_collapsed(n: int):
    """A very long
    chat (10+
    turns) is also
    collapsed (the
    threshold is a
    soft one; the
    rule does not
    become more
    aggressive at
    very high
    counts).
    """
    assert (
        should_collapse_new_turn(n) is True
    )


# --------------------------------------------------------------------
# should_collapse_new_turn: tolerance
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [None, "5", 5.0, [], {}, object()],
)
def test_non_int_input_treated_as_zero(bad: object):
    """A non-int
    ``num_existing_turns``
    (e.g. ``None``
    from a missing
    query) is
    treated as
    ``0`` (the
    first turn is
    always
    expanded). The
    function never
    raises.
    """
    assert (
        should_collapse_new_turn(bad) is False
    )


def test_negative_int_treated_as_zero():
    """A negative
    ``num_existing_turns``
    is treated as
    ``0`` (defensive;
    the caller is
    expected to
    pass a
    non-negative
    count, but we
    do not crash on
    a bad value).
    """
    assert (
        should_collapse_new_turn(-1) is False
    )
    assert (
        should_collapse_new_turn(-100) is False
    )


# --------------------------------------------------------------------
# Threshold constant
# --------------------------------------------------------------------


def test_auto_collapse_threshold_is_5():
    """The threshold is
    ``5`` (a soft
    constant; the
    only piece of
    magic in this
    module).
    """
    assert _AUTO_COLLAPSE_THRESHOLD == 5


def test_threshold_is_exactly_at_boundary():
    """The rule's
    boundary is
    INCLUSIVE on
    the high side
    (a new turn at
    threshold ``5``
    is collapsed).
    """
    # ``4``
    # ->
    # not
    # collapsed
    assert (
        should_collapse_new_turn(
            _AUTO_COLLAPSE_THRESHOLD - 1
        )
        is False
    )
    # ``5``
    # ->
    # collapsed
    assert (
        should_collapse_new_turn(
            _AUTO_COLLAPSE_THRESHOLD
        )
        is True
    )
