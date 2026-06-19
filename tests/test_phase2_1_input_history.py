"""Tests for the R-2026-06-15
(Phase 2 + #1) input-box
UX helpers.

Covers:

  * ``filter_slash_candidates``
    - matching rules
      (name prefix +
      text prefix)
    - case insensitivity
    - sort order
      (shortest first,
      then alphabetical)
    - tolerance
      (non-string input,
      non-list commands)
  * ``render_completion_hint``
    - max rows
    - "and N more" line
    - empty candidates
      returns ``""``
  * ``InputHistory``
    - append /
      de-dup
    - recall_prev
      /
      recall_next
    - reset_cursor
    - save / load
    - bounded deque
      (maxlen)
  * ``is_multiline``
    - newline detection
    - Windows ``\r\n``
    - non-string
      tolerance

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from manusift.tui.input_history import (
    InputHistory,
    SlashCandidate,
    filter_slash_candidates,
    is_multiline,
    render_completion_hint,
)


# --------------------------------------------------------------------
# filter_slash_candidates
# --------------------------------------------------------------------


def test_filter_empty_text_returns_empty():
    assert (
        filter_slash_candidates(
            "", [("/help", "show help")]
        )
        == []
    )


def test_filter_text_without_slash_returns_empty():
    assert (
        filter_slash_candidates(
            "hello", [("/help", "show help")]
        )
        == []
    )


def test_filter_matches_name_prefix():
    out = filter_slash_candidates(
        "/re",
        [
            ("resume", "switch session"),
            ("help", "show help"),
        ],
    )
    assert [c.name for c in out] == ["resume"]


def test_filter_text_prefix_matches_command_name():
    """If the user
    has typed MORE
    than the
    command name
    (``text="/resume"``),
    the match still
    works (the user
    might have just
    typed the full
    command but no
    argument yet).
    """
    out = filter_slash_candidates(
        "/resume",
        [
            ("resume", "switch session"),
            ("help", "show help"),
        ],
    )
    assert [c.name for c in out] == ["resume"]


def test_filter_short_text_matches_longer_command():
    """``text="/resu"``
    matches
    ``resume``
    (the user
    has typed a
    prefix of
    the command).
    """
    out = filter_slash_candidates(
        "/resu",
        [("resume", "switch session")],
    )
    assert [c.name for c in out] == ["resume"]


def test_filter_is_case_insensitive():
    out = filter_slash_candidates(
        "/RE",
        [("resume", "switch session")],
    )
    assert [c.name for c in out] == ["resume"]


def test_filter_sorts_by_length_then_alphabetically():
    out = filter_slash_candidates(
        "/",
        [
            ("zzz", "long"),
            ("a", "short"),
            ("b", "short"),
        ],
    )
    # ``a``
    # and
    # ``b``
    # are
    # tied
    # on
    # length
    # so
    # alphabetical
    # tiebreaker.
    names = [c.name for c in out]
    assert names == ["a", "b", "zzz"]


def test_filter_passes_through_description():
    out = filter_slash_candidates(
        "/help",
        [("help", "show help text")],
    )
    assert len(out) == 1
    assert out[0].description == "show help text"


def test_filter_non_string_text_returns_empty():
    assert filter_slash_candidates(
        None, [("help", "x")]
    ) == []
    assert filter_slash_candidates(
        123, [("help", "x")]
    ) == []


def test_filter_non_list_commands_returns_empty():
    assert filter_slash_candidates(
        "/help", "not a list"
    ) == []
    assert filter_slash_candidates(
        "/help", None
    ) == []


def test_filter_skips_malformed_command_tuples():
    """A command entry
    that is not a
    ``(name, ...)``
    tuple (e.g. just
    a string) is
    silently skipped
    rather than
    raising.
    """
    out = filter_slash_candidates(
        "/help",
        [
            "not a tuple",
            ("help", "x"),
            (123, "x"),
        ],
    )
    assert [c.name for c in out] == ["help"]


def test_filter_candidate_to_pair():
    c = SlashCandidate(
        name="help", description="show help"
    )
    assert c.to_pair() == ("help", "show help")


def test_filter_handles_missing_description():
    """A command tuple
    with no
    description
    element
    defaults to
    ``""``.
    """
    out = filter_slash_candidates(
        "/help", [("help",)]
    )
    assert len(out) == 1
    assert out[0].description == ""


# --------------------------------------------------------------------
# render_completion_hint
# --------------------------------------------------------------------


def test_render_empty_candidates_returns_empty_string():
    assert render_completion_hint([]) == ""


def test_render_single_candidate():
    out = render_completion_hint(
        [
            SlashCandidate(
                name="help",
                description="show help",
            ),
        ]
    )
    assert "/help" in out
    assert "show help" in out


def test_render_max_rows_truncates():
    cands = [
        SlashCandidate(
            name=f"cmd{i}",
            description=f"desc {i}",
        )
        for i in range(10)
    ]
    out = render_completion_hint(cands, max_rows=3)
    # 3
    # rows
    # +
    # 1
    # "and
    # N
    # more"
    # line.
    assert "and 7 more" in out
    # The
    # 4th
    # candidate
    # is
    # NOT
    # in
    # the
    # output.
    assert "cmd3" not in out


def test_render_no_truncation_when_under_max():
    cands = [
        SlashCandidate(
            name="a", description="x"
        ),
        SlashCandidate(
            name="b", description="y"
        ),
    ]
    out = render_completion_hint(
        cands, max_rows=5
    )
    assert "and" not in out
    assert "/a" in out
    assert "/b" in out


# --------------------------------------------------------------------
# InputHistory
# --------------------------------------------------------------------


def test_input_history_empty():
    h = InputHistory()
    assert len(h) == 0
    assert h.recall_prev() is None
    assert h.recall_next() is None


def test_input_history_append():
    h = InputHistory()
    h.append("first")
    h.append("second")
    assert len(h) == 2
    # The
    # most-recent
    # helper
    # returns
    # most-recent
    # first.
    assert h.most_recent() == ["second", "first"]


def test_input_history_empty_string_not_added():
    """An empty
    string is NOT
    added to the
    history (so
    blank ``Enter``
    presses do not
    pollute the
    history).
    """
    h = InputHistory()
    h.append("")
    assert len(h) == 0


def test_input_history_whitespace_only_not_added():
    """An all-whitespace
    string is also
    not added (the
    helper strips
    the text
    defensively, so
    a blank
    ``Enter`` press
    cannot pollute
    the history even
    if the caller
    forgets to
    strip).
    """
    h = InputHistory()
    h.append("   ")
    assert len(h) == 0


def test_input_history_dedup_consecutive_duplicates():
    """A user who
    submits the
    same command
    twice in a row
    does NOT see
    two copies
    in the
    history.
    """
    h = InputHistory()
    h.append("ls")
    h.append("ls")
    assert len(h) == 1


def test_input_history_dedup_with_other_in_between():
    """De-dup is
    only for
    CONSECUTIVE
    duplicates.
    ``ls``
    ->
    ``pwd``
    ->
    ``ls``
    results
    in 3
    entries
    (a
    non-consecutive
    duplicate
    is fine).
    """
    h = InputHistory()
    h.append("ls")
    h.append("pwd")
    h.append("ls")
    assert len(h) == 3


def test_input_history_recall_prev_walks_backwards():
    h = InputHistory()
    h.append("first")
    h.append("second")
    h.append("third")
    # Most-recent
    # first.
    assert h.recall_prev() == "third"
    assert h.recall_prev() == "second"
    assert h.recall_prev() == "first"
    # At
    # the
    # oldest;
    # stay
    # put
    # (return
    # None).
    assert h.recall_prev() is None


def test_input_history_recall_prev_captures_pending_text():
    """The first
    ``recall_prev``
    after a
    submission
    captures the
    user's
    current text
    in
    ``_pending``
    so the user
    can return
    to it.
    """
    h = InputHistory()
    h.append("first")
    h.append("second")
    # The
    # user
    # was
    # typing
    # ``draft``
    # when
    # they
    # pressed
    # ``ctrl+p``.
    recalled = h.recall_prev("draft")
    # The
    # most-recent
    # entry
    # is
    # returned
    # (NOT
    # ``draft``).
    assert recalled == "second"


def test_input_history_recall_next_walks_forwards():
    h = InputHistory()
    h.append("first")
    h.append("second")
    h.append("third")
    # Walk
    # to
    # the
    # bottom
    # first
    # (most-recent
    # -> oldest).
    assert h.recall_prev() == "third"
    assert h.recall_prev() == "second"
    assert h.recall_prev() == "first"
    # Now
    # walk
    # forward
    # (oldest
    # -> most-recent).
    assert h.recall_next() == "second"
    assert h.recall_next() == "third"
    # Past
    # the
    # most-recent:
    # the
    # user
    # is
    # back
    # to
    # the
    # "fresh"
    # state
    # (no
    # pending
    # text
    # because
    # we
    # called
    # recall_prev
    # without
    # a
    # current_text
    # argument,
    # so
    # _pending
    # is
    # "").
    assert h.recall_next() == ""


def test_input_history_recall_next_returns_pending():
    """After walking
    all the way
    back to the
    most-recent
    entry, the
    next recall
    returns the
    ``_pending``
    text the user
    was typing
    before the
    walk.

    Recall the
    flow:

      * ``h.append("first")``
        +
        ``h.append("second")``
        ->
        cursor=-1,
        _pending=""
      * ``h.recall_prev("draft")``
        ->
        captures
        "draft"
        in
        _pending,
        cursor=1
        (most-recent),
        returns
        "second"
      * ``h.recall_next()``
        ->
        already
        at
        the
        most-recent
        (cursor=1
        ==
        len-1);
        returns
        _pending="draft"
        and
        resets
        cursor=-1
      * A
        second
        ``h.recall_next()``
        is
        a
        no-op
        (cursor=-1;
        returns
        ``None``).
    """
    h = InputHistory()
    h.append("first")
    h.append("second")
    # Walk
    # to
    # the
    # most-recent.
    assert h.recall_prev("draft") == "second"
    # Past
    # the
    # most-recent:
    # return
    # ``draft``.
    assert h.recall_next() == "draft"
    # The
    # cursor
    # is
    # reset;
    # the
    # NEXT
    # call
    # is
    # a
    # no-op
    # (returns
    # ``None``).
    assert h.recall_next() is None


def test_input_history_recall_prev_empty_history():
    h = InputHistory()
    assert h.recall_prev() is None


def test_input_history_recall_next_empty_history():
    h = InputHistory()
    assert h.recall_next() is None


def test_input_history_reset_cursor():
    h = InputHistory()
    h.append("a")
    h.append("b")
    # Walk
    # up
    h.recall_prev()  # -> "b"
    h.recall_prev()  # -> "a"
    # User
    # types
    # a
    # character
    h.reset_cursor()
    # Next
    # recall_prev
    # starts
    # from
    # the
    # most-recent.
    assert h.recall_prev() == "b"


def test_input_history_bounded():
    h = InputHistory(
        entries=__import__(
            "collections"
        ).deque(maxlen=3)
    )
    h.append("a")
    h.append("b")
    h.append("c")
    h.append("d")
    # The
    # oldest
    # entry
    # is
    # dropped.
    assert len(h) == 3
    assert h.most_recent() == ["d", "c", "b"]


# --------------------------------------------------------------------
# InputHistory: save / load
# --------------------------------------------------------------------


def test_input_history_save_load(
    tmp_path: Path,
) -> None:
    h = InputHistory()
    h.append("alpha")
    h.append("beta")
    h.append("gamma")
    p = tmp_path / "history.json"
    h.save(p)
    assert p.exists()
    # A
    # fresh
    # history
    # loads
    # the
    # saved
    # entries.
    h2 = InputHistory()
    h2.load(p)
    assert h2.most_recent() == [
        "gamma",
        "beta",
        "alpha",
    ]


def test_input_history_save_creates_parent_dir(
    tmp_path: Path,
) -> None:
    h = InputHistory()
    h.append("a")
    p = tmp_path / "nested" / "history.json"
    h.save(p)
    assert p.exists()


def test_input_history_load_missing_file_preserves_memory(
    tmp_path: Path,
) -> None:
    """A load from a
    missing file is
    a no-op: the
    in-memory
    history is
    preserved
    (the file just
    doesn't exist
    yet, so there's
    nothing to
    load).
    """
    h = InputHistory()
    h.append("preserved")
    h.load(tmp_path / "missing.json")
    assert len(h) == 1
    assert h.most_recent() == ["preserved"]


def test_input_history_load_corrupt_file_preserves_memory(
    tmp_path: Path,
) -> None:
    """A load from a
    CORRUPT file is
    a no-op: the
    in-memory
    history is
    preserved (a
    bad file is
    the user's
    problem; the
    loader does not
    silently
    truncate the
    memory).
    """
    p = tmp_path / "history.json"
    p.write_text(
        "not valid json", encoding="utf-8"
    )
    h = InputHistory()
    h.append("preserved")
    h.load(p)
    assert len(h) == 1
    assert h.most_recent() == ["preserved"]


def test_input_history_load_replaces_memory(
    tmp_path: Path,
) -> None:
    """A SUCCESSFUL
    load REPLACES
    the in-memory
    history (so
    a saved
    session's
    history does
    not bleed into
    a new session).
    """
    p = tmp_path / "history.json"
    p.write_text(
        json.dumps(["a", "b", "c"]),
        encoding="utf-8",
    )
    h = InputHistory()
    h.append("discarded")
    h.load(p)
    assert h.most_recent() == ["c", "b", "a"]


def test_input_history_load_non_list_file(
    tmp_path: Path,
) -> None:
    """A load from a
    non-list JSON
    file (e.g. an
    object) is a
    no-op: the
    in-memory
    history is
    preserved.
    """
    p = tmp_path / "history.json"
    p.write_text(
        json.dumps({"not": "a list"}),
        encoding="utf-8",
    )
    h = InputHistory()
    h.append("preserved")
    h.load(p)
    assert len(h) == 1


def test_input_history_round_trip_with_maxlen(
    tmp_path: Path,
) -> None:
    """A loaded
    history respects
    the maxlen bound.
    """
    h = InputHistory(
        entries=__import__(
            "collections"
        ).deque(maxlen=3)
    )
    p = tmp_path / "history.json"
    # 5
    # entries
    # on
    # disk.
    p.write_text(
        json.dumps(["a", "b", "c", "d", "e"]),
        encoding="utf-8",
    )
    h.load(p)
    # The
    # deque
    # maxlen
    # of
    # 3
    # keeps
    # the
    # last
    # 3.
    assert len(h) == 3
    assert h.most_recent() == ["e", "d", "c"]


# --------------------------------------------------------------------
# is_multiline
# --------------------------------------------------------------------


def test_is_multiline_single_line():
    assert is_multiline("hello") is False


def test_is_multiline_with_newline():
    assert is_multiline("hello\nworld") is True


def test_is_multiline_with_windows_line_endings():
    assert is_multiline("hello\r\nworld") is True


def test_is_multiline_empty_string():
    assert is_multiline("") is False


def test_is_multiline_only_newline():
    assert is_multiline("\n") is True


def test_is_multiline_non_string():
    assert is_multiline(None) is False
    assert is_multiline(123) is False
    assert is_multiline(["a", "b"]) is False
