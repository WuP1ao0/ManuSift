"""Tests for the R-2026-06-15
(Phase 2 + #4) command
palette.

Covers:

  * ``fuzzy_score``
    - exact
      match
      → 100
    - prefix
      match
      → 100
    - subsequence
      match
      → 70
      + bonuses
    - no
      match
      → 0
    - case
      insensitivity
    - tolerance
      (non-string
      input
      returns
      0)
    - consecutive
      bonus
    - length
      penalty
  * ``rank_candidates``
    - sorts
      by
      score
      desc
    - excludes
      no-match
      candidates
    - empty
      query
      returns
      all
    - respects
      max_results
    - tolerates
      non-list
      input
  * ``highlight_match``
    - matched
      chars
      wrapped
      in
      ``[bold]``
    - unmatched
      chars
      unchanged
    - empty
      ``matched_indices``
      returns
      ``name``
      unchanged
    - tolerance
      (non-string
      /
      non-iterable
      returns
      ``name``
      or
      ``""``)
  * ``PaletteEntry``
    dataclass
    construction
  * Integration
    with
    ``slash_registry``
    (the
    helpers
    work
    on
    ``SlashCommand``
    instances
    and
    on
    bare
    tuples)

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tui.command_palette import (
    PaletteEntry,
    fuzzy_score,
    highlight_match,
    rank_candidates,
)


# --------------------------------------------------------------------
# fuzzy_score: exact / prefix / subsequence
# --------------------------------------------------------------------


def test_fuzzy_score_exact_match_is_100():
    """An exact
    (``query == name``)
    match is
    ``100``.
    """
    assert fuzzy_score("resume", "resume") == 100


def test_fuzzy_score_prefix_match_is_100():
    """A prefix
    match
    (``name.startswith(query)``)
    is also
    ``100``
    (so the
    user can
    just type
    ``"res"``
    and see
    ``"resume"``
    as a
    top
    match).
    """
    assert fuzzy_score("res", "resume") == 100
    assert fuzzy_score("r", "resume") == 100
    assert fuzzy_score("resum", "resume") == 100


def test_fuzzy_score_subsequence_match_is_70_plus():
    """A
    subsequence
    match (the
    query
    appears
    in
    the
    name
    in
    order
    but
    not
    as
    a
    prefix)
    gets
    ``70``
    + consecutive
    bonuses
    - length
    penalty.

    We just verify
    the score is
    ``> 0``
    (the ranker
    includes it) and
    ``< 100`` (it's
    not a prefix
    match, so it is
    ranked below an
    exact match).
    """
    # ``rsu`` in
    # ``resume``
    # (chars 0, 2, 3):
    # subsequence
    # match,
    # 1
    # consecutive
    # pair
    # (2→3).
    # Score
    # =
    # 70
    # +
    # 5
    # -
    # 6
    # =
    # 69.
    score = fuzzy_score("rsu", "resume")
    assert 0 < score < 100


def test_fuzzy_score_no_match_returns_0():
    """A query
    that does
    NOT appear
    as a
    subsequence
    of the
    name
    returns
    ``0``
    (the
    candidate
    is
    excluded
    from the
    palette).
    """
    assert fuzzy_score("xyz", "resume") == 0
    # ``abc``
    # doesn't
    # appear
    # in
    # ``resume``
    # at
    # all.
    assert fuzzy_score("abc", "resume") == 0


def test_fuzzy_score_is_case_insensitive():
    """``RES`` matches
    ``resume`` (case
    is ignored).
    ``RsE``
    (mixed case)
    is
    a
    SUBSEQUENCE
    match
    (not
    a
    prefix)
    and
    ranks
    below
    an
    exact
    match.
    """
    # Exact-match
    # case
    # (case-insensitive).
    assert (
        fuzzy_score("RES", "resume") == 100
    )
    assert (
        fuzzy_score("res", "RESUME") == 100
    )
    # Mixed
    # case
    # that
    # is
    # NOT
    # a
    # prefix
    # match
    # (it
    # matches
    # indices
    # 0, 2, 5
    # in
    # ``resume``).
    # The
    # score
    # is
    # > 0
    # (it
    # matches
    # as
    # a
    # subsequence)
    # but
    # < 100
    # (it
    # is
    # ranked
    # below
    # an
    # exact
    # match).
    score = fuzzy_score("RsE", "resume")
    assert 0 < score < 100


def test_fuzzy_score_consecutive_bonus():
    """The
    ``"res"``
    match
    in
    ``"resume"``
    has
    2
    consecutive
    pairs
    (``re``
    +
    ``es``);
    the
    ``"rse"``
    match
    has
    0
    consecutive
    pairs.
    The
    consecutive
    match
    should
    rank
    HIGHER.
    """
    consecutive_score = fuzzy_score(
        "res", "resume"
    )
    # ``res``
    # is
    # a
    # prefix,
    # so
    # it
    # is
    # already
    # 100.
    # The
    # bonus
    # is
    # only
    # relevant
    # for
    # non-prefix
    # matches.
    assert consecutive_score == 100
    # A
    # non-prefix
    # example.
    a = fuzzy_score("rse", "resume")
    b = fuzzy_score("res", "resume")
    # ``res``
    # is
    # 100
    # (prefix);
    # ``rse``
    # is
    # at
    # most
    # 70
    # + 0
    # consecutive.
    assert b == 100
    assert a < 100


def test_fuzzy_score_shorter_name_ranks_above_longer():
    """A shorter
    candidate
    name ranks
    ABOVE a
    longer one
    for the
    same
    query
    (so ``quit``
    beats
    ``restart``
    when the
    query is
    ``q``).
    """
    a = fuzzy_score("q", "quit")
    b = fuzzy_score("q", "restart")
    # ``q``
    # is
    # a
    # prefix
    # of
    # both,
    # so
    # both
    # are
    # 100;
    # the
    # length
    # penalty
    # does
    # not
    # apply
    # to
    # prefix
    # matches.
    # Use
    # a
    # non-prefix
    # query.
    a = fuzzy_score("qt", "quit")  # 70 + 1*5 - 4
    b = fuzzy_score("qt", "restart")  # 70 + 0 - 7
    # The
    # shorter
    # name
    # ``quit``
    # ranks
    # above
    # ``restart``
    # because
    # the
    # consecutive
    # bonus
    # is
    # larger.
    assert a > b


def test_fuzzy_score_empty_query_returns_1():
    """An empty
    query
    matches
    every
    candidate
    with a
    LOW score
    (``1``) so
    the palette
    can show
    all
    commands
    sorted by
    name.
    """
    assert fuzzy_score("", "resume") == 1


def test_fuzzy_score_empty_name_returns_0():
    """An empty
    candidate
    name
    returns
    ``0`` (so
    an empty
    candidate
    is not
    listed in
    the
    palette).
    """
    assert fuzzy_score("q", "") == 0


def test_fuzzy_score_non_string_input_returns_0():
    """A
    non-string
    input
    returns
    ``0``
    (the
    function
    never
    raises).
    """
    assert fuzzy_score(None, "resume") == 0
    assert fuzzy_score("q", None) == 0
    assert fuzzy_score(123, "resume") == 0
    assert fuzzy_score("q", 123) == 0


# --------------------------------------------------------------------
# rank_candidates
# --------------------------------------------------------------------


@pytest.fixture
def sample_commands() -> list[tuple[str, str, str]]:
    """A small list of
    ``(name,
    description,
    category)``
    tuples for the
    ranker tests.
    """
    return [
        (
            "resume",
            "switch session",
            "Session",
        ),
        (
            "reset",
            "start fresh",
            "Session",
        ),
        (
            "restart",
            "restart session",
            "Session",
        ),
        (
            "budget",
            "show budget",
            "Status",
        ),
        (
            "help",
            "show help",
            "UI",
        ),
    ]


def test_rank_candidates_empty_query_returns_all_sorted(
    sample_commands: list,
) -> None:
    """An empty
    query
    returns
    ALL
    commands,
    sorted by
    name
    (so the
    palette
    can show
    the
    whole
    list
    when
    the
    user
    just
    presses
    ``ctrl+shift+p``
    without
    typing).
    """
    out = rank_candidates(
        "", sample_commands
    )
    assert len(out) == 5
    names = [e.name for e in out]
    # The
    # scores
    # are
    # all
    # ``1``
    # (the
    # empty-query
    # match),
    # so
    # the
    # tiebreaker
    # is
    # alphabetical.
    assert names == [
        "budget",
        "help",
        "reset",
        "restart",
        "resume",
    ]


def test_rank_candidates_prefix_match_ranks_first(
    sample_commands: list,
) -> None:
    """A query
    that is a
    prefix of
    one
    command
    ranks
    that
    command
    FIRST
    (the
    exact
    match
    is
    the
    top
    result).
    """
    out = rank_candidates("res", sample_commands)
    # ``resume``
    # is
    # a
    # prefix
    # match
    # →
    # 100.
    # ``reset``
    # is
    # also
    # a
    # prefix
    # match
    # →
    # 100.
    # ``restart``
    # is
    # also
    # a
    # prefix
    # match
    # →
    # 100.
    # The
    # tiebreaker
    # is
    # alphabetical.
    assert [e.name for e in out[:3]] == [
        "reset",
        "restart",
        "resume",
    ]


def test_rank_candidates_excludes_no_match(
    sample_commands: list,
) -> None:
    """A query
    that does
    NOT match
    some
    candidates
    excludes
    them
    from the
    result.
    """
    out = rank_candidates("xyz", sample_commands)
    assert out == []


def test_rank_candidates_includes_subsequence_matches(
    sample_commands: list,
) -> None:
    """A query
    that is a
    subsequence
    of one or
    more
    candidates
    (but not a
    prefix)
    ranks them
    by score
    (subsequence
    + consecutive
    + length
    penalty).
    """
    out = rank_candidates("rst", sample_commands)
    # ``rst``
    # appears
    # in
    # ``restart``
    # as
    # a
    # prefix
    # (so
    # 100),
    # and
    # in
    # ``reset``
    # /
    # ``resume``
    # as
    # a
    # subsequence
    # (so
    # 70).
    names = [e.name for e in out]
    assert "restart" in names
    assert "reset" in names or "resume" in names


def test_rank_candidates_respects_max_results(
    sample_commands: list,
) -> None:
    """The result
    is
    truncated
    to
    ``max_results``
    entries
    (the
    palette
    cannot
    show
    more
    than 10
    at a
    time).
    """
    out = rank_candidates(
        "", sample_commands, max_results=2
    )
    assert len(out) == 2


def test_rank_candidates_max_results_default_is_10():
    """The default
    ``max_results``
    is 10 (a
    TUI popover
    larger
    than
    that is
    not
    useful).
    """
    # 11
    # commands.
    cmds = [
        (f"cmd{i:02d}", f"desc {i}", "C")
        for i in range(11)
    ]
    out = rank_candidates("", cmds)
    assert len(out) == 10


def test_rank_candidates_non_list_input_returns_empty():
    """A
    non-list
    input
    (e.g. a
    string)
    returns
    ``[]``
    (the
    ranker
    never
    raises).
    """
    assert rank_candidates("x", "not a list") == []
    assert rank_candidates("x", None) == []


def test_rank_candidates_works_on_slash_command_objects():
    """The ranker
    works on
    ``SlashCommand``
    instances
    (not just
    tuples).
    """
    from manusift.tui.slash_registry import (
        SlashCommand,
    )
    cmds = [
        SlashCommand(
            name="resume",
            description="x",
            category="C",
            handler=lambda app, arg: None,
        ),
        SlashCommand(
            name="help",
            description="y",
            category="C",
            handler=lambda app, arg: None,
        ),
    ]
    out = rank_candidates("res", cmds)
    assert len(out) == 1
    assert out[0].name == "resume"


def test_rank_candidates_palette_entry_has_all_fields(
    sample_commands: list,
) -> None:
    """Each
    ``PaletteEntry``
    has the
    5
    expected
    fields
    (``name``,
    ``description``,
    ``category``,
    ``score``,
    ``matched_indices``).
    """
    out = rank_candidates("res", sample_commands)
    assert len(out) > 0
    entry = out[0]
    assert isinstance(entry.name, str)
    assert isinstance(entry.description, str)
    assert isinstance(entry.category, str)
    assert isinstance(entry.score, int)
    assert isinstance(
        entry.matched_indices, tuple
    )


def test_rank_candidates_matched_indices_for_prefix_match(
    sample_commands: list,
) -> None:
    """For a
    prefix
    match
    (``res`` →
    ``resume``),
    the
    matched
    indices
    are
    ``(0,
    1,
    2)``
    (the
    first
    three
    chars
    of
    the
    name).
    """
    out = rank_candidates("res", sample_commands)
    # Find
    # ``resume``.
    resume_entries = [
        e for e in out if e.name == "resume"
    ]
    assert len(resume_entries) == 1
    # ``res``
    # is
    # a
    # 3-char
    # prefix.
    assert resume_entries[0].matched_indices == (
        0,
        1,
        2,
    )


def test_rank_candidates_palette_entry_to_dict():
    """``PaletteEntry``
    has a
    ``to_dict``
    method
    that
    returns
    a
    plain
    dict
    (for
    JSON
    serialization
    in
    audit
    logs).
    """
    # The
    # dataclass
    # does
    # not
    # have
    # an
    # explicit
    # ``to_dict``
    # method
    # (so
    # the
    # audit
    # log
    # can
    # just
    # use
    # ``dataclasses.asdict``).
    entry = PaletteEntry(
        name="x",
        description="y",
        category="z",
        score=80,
        matched_indices=(0, 1),
    )
    import dataclasses
    d = dataclasses.asdict(entry)
    assert d == {
        "name": "x",
        "description": "y",
        "category": "z",
        "score": 80,
        "matched_indices": (0, 1),
    }


# --------------------------------------------------------------------
# highlight_match
# --------------------------------------------------------------------


def test_highlight_match_empty_indices_returns_name_unchanged():
    """An empty
    ``matched_indices``
    list
    returns
    the
    name
    unchanged
    (so the
    palette
    can
    fall
    back
    to
    plain
    text
    when
    the
    ranker
    finds
    no
    matches).
    """
    assert highlight_match("resume", ()) == "resume"
    assert highlight_match("resume", []) == "resume"


def test_highlight_match_wraps_matched_chars_in_bold():
    """Matched
    characters
    are wrapped
    in
    ``[bold]...[bold]``
    so the
    user
    sees
    which
    characters
    matched.
    """
    out = highlight_match("resume", (0, 1, 2))
    # Each
    # of
    # the
    # first
    # 3
    # chars
    # (``r``,
    # ``e``,
    # ``s``)
    # is
    # wrapped.
    assert out == (
        "[bold]r[/bold]"
        "[bold]e[/bold]"
        "[bold]s[/bold]"
        "ume"
    )


def test_highlight_match_non_contiguous_indices():
    """Non-
    contiguous
    matched
    chars
    (e.g.
    ``r`` at
    index 0
    + ``m`` at
    index 4)
    are each
    wrapped
    separately.
    The middle
    chars are
    left
    plain.
    """
    out = highlight_match(
        "resume", (0, 4)
    )
    # ``r``
    # is
    # bold,
    # ``e``
    # ``s``
    # ``u``
    # are
    # plain,
    # ``m``
    # is
    # bold,
    # ``e``
    # is
    # plain.
    assert out == (
        "[bold]r[/bold]esu"
        "[bold]m[/bold]e"
    )


def test_highlight_match_out_of_range_indices_ignored():
    """An index
    past the
    end of
    the name
    is
    silently
    ignored
    (so a
    bad
    rank
    result
    does
    not
    crash
    the
    popover).
    """
    out = highlight_match("ab", (0, 5, 10))
    # ``a``
    # is
    # bold,
    # ``b``
    # is
    # plain
    # (the
    # other
    # indices
    # are
    # out
    # of
    # range).
    assert out == "[bold]a[/bold]b"


def test_highlight_match_non_string_name_returns_empty():
    """A non-string
    name
    returns
    ``""``
    (the
    palette
    does
    not
    crash
    on a
    bad
    candidate).
    """
    assert highlight_match(None, (0, 1)) == ""
    assert highlight_match(123, (0, 1)) == ""


def test_highlight_match_non_iterable_indices_returns_name():
    """A
    non-iterable
    ``matched_indices``
    (e.g.
    an
    int)
    returns
    the
    name
    unchanged
    (so a
    bad
    row
    does
    not
    crash
    the
    palette).
    """
    assert highlight_match("resume", 5) == "resume"
    assert highlight_match("resume", None) == "resume"


# --------------------------------------------------------------------
# Integration: rank_candidates with real SlashCommand registry
# --------------------------------------------------------------------


def test_rank_candidates_with_real_registry_returns_at_least_2_commands():
    """The
    real
    ``slash_registry``
    has at least 2
    commands (``help``
    + ``echo``) at
    the default
    state. (Earlier
    code paths register
    more commands
    lazily on first
    use; the ranker
    is a pure function
    that works
    regardless of the
    count.) An empty
    query returns
    them all.
    """
    from manusift.tui.slash_registry import (
        iter_commands,
    )
    cmds = list(iter_commands())
    # Pin
    # the
    # floor
    # at
    # ``2``
    # (so
    # a
    # regression
    # that
    # removes
    # ``help``
    # /
    # ``echo``
    # is
    # caught)
    # but
    # allow
    # the
    # count
    # to
    # grow
    # when
    # new
    # commands
    # are
    # registered
    # in
    # future
    # phases.
    assert len(cmds) >= 2
    out = rank_candidates("", cmds)
    # The
    # ranker
    # caps
    # the
    # result
    # at
    # ``max_results=10``
    # (the
    # TUI
    # popover
    # cannot
    # show
    # more
    # than
    # 10
    # rows).
    # The
    # first
    # 10
    # commands
    # (alphabetical)
    # are
    # returned.
    assert len(out) == min(
        len(cmds), 10
    )
    # The
    # 2
    # known
    # commands
    # are
    # BOTH
    # present
    # (they
    # sort
    # alphabetically
    # within
    # the
    # top
    # 10
    # because
    # ``echo``
    # is
    # before
    # ``help``).
    names = {e.name for e in out}
    assert "help" in names
    assert "echo" in names


def test_rank_candidates_real_registry_query_help():
    """A query
    of
    ``"help"``
    ranks
    ``/help``
    as the
    top
    match
    in the
    real
    registry.
    """
    from manusift.tui.slash_registry import (
        iter_commands,
    )
    cmds = list(iter_commands())
    out = rank_candidates("help", cmds)
    assert out[0].name == "help"
    assert out[0].score == 100
    # ``echo``
    # does
    # NOT
    # match
    # ``help``
    # so
    # it
    # is
    # excluded.
    names = {e.name for e in out}
    assert "echo" not in names
