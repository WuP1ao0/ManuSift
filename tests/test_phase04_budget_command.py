"""Tests for the R-2026-06-15 (Phase 0.4)
``/budget`` slash command + budget
snapshot helper.

The contract:

  * ``render_budget_snapshot``
    is a pure function: no
    side effects, no imports
    of ``manusift.config``,
    deterministic output.
  * When given a settings
    object, the output lists
    each cap with the
    consumed counter.
  * When given only a
    ``consumed`` map, the
    output still shows the
    consumed values.
  * Unknown keys in
    ``consumed`` are
    tolerated (defensive: a
    stale snapshot from a
    previous version does
    not crash).
  * The chat TUI registers
    a ``/budget`` slash
    command in the
    ``SlashCommand``
    registry at class-body
    time.
  * ``ChatApp._cmd_budget``
    exists with no
    arguments.

Pattern follows the agent-infra-
iteration-engineer skill rule
I.4: pure helper + thin TUI
wiring, both tested.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from manusift.tui.budget import (
    render_budget_snapshot,
)


# A minimal settings shim
# with just the fields the
# helper reads.
@dataclass
class _FakeSettings:
    tool_calls_per_name_cap: int = 12
    tool_calls_per_turn_cap: int = 50
    bash_max_calls_per_turn: int = 30
    data_source_max_files: int = 100
    subagent_timeout_seconds: float = 60.0


# --------------------------------------------------------------------
# render_budget_snapshot (pure function)
# --------------------------------------------------------------------


def test_snapshot_with_no_args_renders_header():
    out = render_budget_snapshot()
    assert "=== Budget Snapshot ===" in out


def test_snapshot_lists_each_cap_with_consumed():
    s = _FakeSettings()
    out = render_budget_snapshot(
        consumed={
            "tool_calls_per_name_cap": 5,
            "tool_calls_per_turn_cap": 12,
            "bash_max_calls_per_turn": 3,
            "data_source_max_files": 2,
        },
        settings=s,
    )
    assert "tool_calls_per_name_cap: 5 / 12" in out
    assert "tool_calls_per_turn_cap: 12 / 50" in out
    assert "bash_max_calls_per_turn: 3 / 30" in out
    assert "data_source_max_files: 2 / 100" in out


def test_snapshot_skips_none_caps():
    """When a settings field is
    ``None`` (e.g. a new
    field that has not been
    wired into the chat TUI
    yet), the cap line is
    omitted entirely.
    """

    @dataclass
    class _PartialSettings:
        tool_calls_per_name_cap: int = 12
        # tool_calls_per_turn_cap
        # is intentionally not
        # defined.

    out = render_budget_snapshot(
        consumed={"tool_calls_per_name_cap": 1},
        settings=_PartialSettings(),
    )
    assert "tool_calls_per_name_cap: 1 / 12" in out
    assert "tool_calls_per_turn_cap" not in out


def test_snapshot_tolerates_unknown_consumed_keys():
    """A stale ``consumed`` map
    from a previous version
    is silenciously dropped
    when ``settings`` is
    provided, so the
    output is deterministic
    and stable.
    """
    s = _FakeSettings()
    out = render_budget_snapshot(
        consumed={
            "tool_calls_per_name_cap": 0,
            "future_cap_that_does_not_exist": 99,
        },
        settings=s,
    )
    # The known cap is
    # shown.
    assert (
        "tool_calls_per_name_cap: 0 / 12"
        in out
    )
    # The unknown key is
    # silently ignored
    # when settings are
    # provided.
    assert (
        "future_cap_that_does_not_exist" not in out
    )


def test_snapshot_shows_extras_when_settings_omitted():
    """When ``settings`` is
    not provided, all
    consumed keys are
    shown (the user wants
    the raw numbers even
    without caps).
    """
    out = render_budget_snapshot(
        consumed={"my_cap": 7},
    )
    assert "my_cap: 7" in out


# --------------------------------------------------------------------
# Slash command registration
# --------------------------------------------------------------------


def test_budget_slash_command_registered():
    """The chat TUI registers
    a ``/budget`` slash
    command in the
    ``SlashCommand``
    registry at class-body
    time.
    """
    # Importing the chat
    # app triggers the
    # registration.
    from manusift.tui import chat_app  # noqa: F401
    from manusift.tui.slash_registry import (
        find,
    )
    entry = find("budget")
    assert entry is not None
    assert entry.category == "Session"
    assert "budget" in entry.description.lower()


def test_cmd_budget_method_exists():
    """``ChatApp._cmd_budget``
    exists with no
    arguments.
    """
    from manusift.tui.chat_app import ChatApp
    method = getattr(
        ChatApp, "_cmd_budget", None
    )
    assert method is not None
    import inspect
    sig = inspect.signature(method)
    params = [
        p
        for p in sig.parameters.values()
        if p.name != "self"
    ]
    assert len(params) == 0
