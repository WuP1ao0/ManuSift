"""Tests for the R-2026-06-15 (Phase 0.6
+ 0.7) system-prompt rules.

The contract:

  * Phase 0.6 — "claim only if
    executed" is the
    ``## Honesty About Tool
    Use (HARD)`` rule. The
    prompt forbids claiming
    "I already ran X" without
    a tool result that
    actually came back OK.

  * Phase 0.7 — for source
    data with more than 10,000
    rows, prefer ``table_scan``
    or ``source_data_audit``
    over spawning a sub-agent.
    The threshold is a soft
    guideline.

Pattern follows the agent-infra-
iteration-engineer skill rule
I.7: every public-contract
section in the system prompt
has a test.
"""
from __future__ import annotations

import pytest

# Reuse the existing
# ``system_prompt_text`` fixture
# from ``test_system_prompt_rewrite``.
# pytest fixtures are
# automatically shared
# across test files in the
# same directory.
pytest_plugins = ["tests.test_system_prompt_rewrite"]


def test_honesty_about_tool_use_rule_present(
    system_prompt_text: str,
) -> None:
    """The ``## Honesty About
    Tool Use (HARD)`` section
    is in the system prompt.
    """
    assert "Honesty About Tool Use" in (
        system_prompt_text
    )


def test_honesty_rule_forbids_fabricated_tool_claims(
    system_prompt_text: str,
) -> None:
    """The honesty rule must
    forbid the LLM from
    claiming a tool was run
    when it was not.
    """
    lower = system_prompt_text.lower()
    # The prompt explicitly
    # names the
    # anti-pattern.
    assert (
        "do not claim" in lower
        or "do not say" in lower
        or "do not present" in lower
    )
    # And the specific
    # example: "I already
    # ran X".
    assert "i already ran" in lower


def test_honesty_rule_names_the_audit_signal(
    system_prompt_text: str,
) -> None:
    """The honesty rule
    explains how the LLM
    should verify a tool
    was actually run: the
    tool result must have
    come back OK in the
    conversation above.
    """
    # The exact phrasing
    # is "the tool result
    # actually came back
    # OK". A small tolerance
    # for rewording.
    lower = system_prompt_text.lower()
    assert (
        "tool result" in lower
        and "came back ok" in lower
    )


def test_try_first_push_last_threshold_rule(
    system_prompt_text: str,
) -> None:
    """For source data with
    more than 10,000 rows,
    prefer ``table_scan`` or
    ``source_data_audit``
    over spawning a
    sub-agent.
    """
    # Both tool names must
    # be present in the
    # prompt.
    assert "table_scan" in system_prompt_text
    assert (
        "source_data_audit" in system_prompt_text
    )
    # The 10K threshold is
    # named.
    assert "10,000" in system_prompt_text
    # The rule must steer
    # the LLM away from a
    # sub-agent for large
    # sources.
    lower = system_prompt_text.lower()
    assert "sub-agent" in lower or (
        "subagent" in lower
    )


def test_try_first_push_last_rule_present(
    system_prompt_text: str,
) -> None:
    """The existing
    ``## Try First, Push
    Last (HARD)`` rule is
    still present.
    """
    assert (
        "Try First, Push Last" in system_prompt_text
    )
