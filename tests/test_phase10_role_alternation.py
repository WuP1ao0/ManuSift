"""Tests for the R-2026-06-15 (Phase 0.10)
``assert_role_alternation``
helper.

The contract:

  * Two consecutive ``"user"``
    messages are deduplicated
    to one (the later one
    wins).
  * Two consecutive
    ``"assistant"`` messages
    are deduplicated to one
    (the later one wins).
  * ``"system"``,
    ``"tool"``,
    ``"developer"`` roles
    are passed through
    unchanged and do not
    count toward the user
    / assistant alternation
    rule.
  * An empty input returns
    ``[]``.
  * The function does not
    mutate the caller.
  * Already-alternating
    messages pass through
    unchanged.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tui.role_alternation import (
    assert_role_alternation,
)


# --------------------------------------------------------------------
# Empty + passthrough
# --------------------------------------------------------------------


def test_empty_input_returns_empty_list():
    assert assert_role_alternation([]) == []


def test_already_alternating_passes_through():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "again"},
        {"role": "assistant", "content": "sure"},
    ]
    out = assert_role_alternation(msgs)
    assert out == msgs


# --------------------------------------------------------------------
# Two consecutive user
# --------------------------------------------------------------------


def test_consecutive_user_dedupes_later_wins():
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 1
    assert out[0]["content"] == "second"


def test_three_consecutive_user_dedupes_to_one():
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 1
    assert out[0]["content"] == "c"


# --------------------------------------------------------------------
# Two consecutive assistant
# --------------------------------------------------------------------


def test_consecutive_assistant_dedupes_later_wins():
    """Two consecutive
    ``assistant`` messages
    would mean the LLM is
    responding to itself.
    The later one wins
    (LLM is the source
    of truth).
    """
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "second"


# --------------------------------------------------------------------
# system/tool/developer passthrough
# --------------------------------------------------------------------


def test_system_messages_pass_through():
    msgs = [
        {"role": "system", "content": "you are x"},
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "another"},
        {"role": "assistant", "content": "hello"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 4
    assert [m["role"] for m in out] == [
        "system",
        "user",
        "system",
        "assistant",
    ]


def test_tool_messages_do_not_count_as_user_or_assistant():
    """An OpenAI-style
    ``tool`` role message
    between two ``user``
    messages does NOT
    dedupe the users
    (because the rule is
    user/assistant only).
    """
    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "tool", "content": "t1"},
        {"role": "user", "content": "u2"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 3
    assert [m["role"] for m in out] == [
        "user",
        "tool",
        "user",
    ]


def test_developer_role_passes_through():
    msgs = [
        {"role": "developer", "content": "policy"},
        {"role": "user", "content": "hi"},
    ]
    out = assert_role_alternation(msgs)
    assert len(out) == 2
    assert out[0]["role"] == "developer"
    assert out[1]["role"] == "user"


# --------------------------------------------------------------------
# Mutation safety
# --------------------------------------------------------------------


def test_function_does_not_mutate_caller():
    msgs = [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},
    ]
    original = list(msgs)
    assert_role_alternation(msgs)
    # Caller's list is
    # unchanged.
    assert msgs == original


def test_function_does_not_mutate_messages_in_place():
    """The messages
    themselves are
    not modified (the
    deduping is done by
    replacing the last
    message with a
    fresh reference).
    """
    a = {"role": "user", "content": "a"}
    b = {"role": "user", "content": "b"}
    msgs = [a, b]
    out = assert_role_alternation(msgs)
    # The output
    # references the
    # original ``b`` (the
    # later one wins).
    assert out[0] is b
    # The original ``a``
    # is untouched.
    assert a["content"] == "a"


# --------------------------------------------------------------------
# Defensive
# --------------------------------------------------------------------


def test_unknown_role_passes_through():
    """A message with an
    unknown role is
    passed through
    (defensive: a future
    role we don't know
    about).
    """
    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "future-role", "content": "?"},
        {"role": "user", "content": "u2"},
    ]
    out = assert_role_alternation(msgs)
    # The unknown role
    # does not dedupe
    # the users.
    assert len(out) == 3
