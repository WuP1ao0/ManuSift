"""Tests for the R-2026-06-14 P1.2 unified slash
command registry.

The contract:

  * ``SlashCommand`` is a frozen dataclass
    with ``name`` / ``description`` /
    ``category`` / ``handler`` / ``aliases``.
  * ``register(cmd)`` appends a command.
    Duplicate ``name`` is rejected unless
    ``replace=True`` (test affordance).
  * ``find("/foo")`` and ``find("foo")`` both
    work; aliases resolve to the same command.
  * ``by_category()`` returns a dict
    preserving registration order, with
    one entry per category.
  * ``/help`` is a registered command whose
    handler can be invoked without raising
    even on a no-op app (handler is robust
    to missing ``app._append_status_line``).

Pattern follows the
``agent-infra-iteration-engineer`` skill
rule I.2: add a new tool by appending, not
by rewriting the dispatcher.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tui.slash_registry import (
    SlashCommand,
    all_names,
    by_category,
    categories,
    clear,
    find,
    iter_commands,
    register,
    reset_to_defaults,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot + restore the registry
    around every test so test isolation
    does not require each test to call
    ``reset_to_defaults()`` itself.
    """
    saved = list(iter_commands())
    clear()
    reset_to_defaults()
    yield
    clear()
    for c in saved:
        register(c)


# --------------------------------------------------------------------
# Basic register / find
# --------------------------------------------------------------------


def test_register_appends_command():
    cmd = SlashCommand(
        name="test-foo",
        description="test",
        category="T",
        handler=lambda app, arg: None,
    )
    register(cmd)
    assert find("test-foo") is cmd
    assert find("/test-foo") is cmd


def test_find_returns_none_for_unknown():
    assert find("nope") is None
    assert find("/nope") is None


def test_register_does_not_replace_by_default():
    cmd_a = SlashCommand(
        name="dup",
        description="a",
        category="T",
        handler=lambda app, arg: None,
    )
    cmd_b = SlashCommand(
        name="dup",
        description="b",
        category="T",
        handler=lambda app, arg: None,
    )
    register(cmd_a)
    register(cmd_b)
    # Both are in the registry. The first
    # one wins dispatch (the registry is
    # append-only by default).
    assert find("dup") is cmd_a


def test_register_replace_replaces_existing():
    cmd_a = SlashCommand(
        name="dup2",
        description="a",
        category="T",
        handler=lambda app, arg: None,
    )
    cmd_b = SlashCommand(
        name="dup2",
        description="b",
        category="T",
        handler=lambda app, arg: None,
    )
    register(cmd_a)
    register(cmd_b, replace=True)
    assert find("dup2") is cmd_b


# --------------------------------------------------------------------
# Aliases
# --------------------------------------------------------------------


def test_alias_resolves_to_command():
    cmd = SlashCommand(
        name="quit",
        description="exit the chat",
        category="Session",
        handler=lambda app, arg: None,
        aliases=("q", "exit"),
    )
    register(cmd)
    assert find("q") is cmd
    assert find("/q") is cmd
    assert find("exit") is cmd
    assert find("quit") is cmd


def test_all_names_includes_aliases():
    cmd = SlashCommand(
        name="foo",
        description="x",
        category="T",
        handler=lambda app, arg: None,
        aliases=("f", "F"),
    )
    register(cmd)
    names = all_names()
    assert "foo" in names
    assert "f" in names
    assert "F" in names


# --------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------


def test_categories_returns_distinct_in_order():
    register(SlashCommand(
        name="a", description="a", category="Z",
        handler=lambda app, arg: None,
    ))
    register(SlashCommand(
        name="b", description="b", category="A",
        handler=lambda app, arg: None,
    ))
    register(SlashCommand(
        name="c", description="c", category="Z",
        handler=lambda app, arg: None,
    ))
    cats = categories()
    # Distinct and in registration order.
    # "Z" appears first because it is the
    # first user category registered after
    # the autouse fixture's built-ins.
    assert cats.index("Z") < cats.index("A")
    # No duplicates.
    assert len(cats) == len(set(cats))


def test_by_category_groups_correctly():
    register(SlashCommand(
        name="x", description="x", category="X",
        handler=lambda app, arg: None,
    ))
    register(SlashCommand(
        name="y", description="y", category="Y",
        handler=lambda app, arg: None,
    ))
    register(SlashCommand(
        name="z", description="z", category="X",
        handler=lambda app, arg: None,
    ))
    by_cat = by_category()
    assert "X" in by_cat
    assert "Y" in by_cat
    assert [c.name for c in by_cat["X"]] == ["x", "z"]


# --------------------------------------------------------------------
# /help is registered by default
# --------------------------------------------------------------------


def test_help_command_is_registered_by_default():
    found = find("help")
    assert found is not None
    assert found.name == "help"
    assert found.category == "Help"


def test_help_handler_robust_to_no_op_app():
    """The default ``/help`` handler
    does not raise when ``app`` has no
    ``_append_status_line`` (e.g. in
    unit tests that pass a sentinel).
    """
    found = find("help")
    # No app at all: should be a no-op.
    found.handler(None, "")
    # Sentinel with no method.
    class _S:
        pass
    found.handler(_S(), "")


# --------------------------------------------------------------------
# iter_commands is a tuple snapshot
# --------------------------------------------------------------------


def test_iter_commands_returns_snapshot():
    """``iter_commands`` returns a
    tuple so the caller can iterate
    without race conditions if
    another thread is registering.
    """
    snap = iter_commands()
    assert isinstance(snap, tuple)
    assert len(snap) >= 2  # /help and /echo


# --------------------------------------------------------------------
# clear() test hook
# --------------------------------------------------------------------


def test_clear_drops_everything():
    clear()
    assert len(iter_commands()) == 0
    reset_to_defaults()
    # Now the built-ins are back.
    assert find("help") is not None


# --------------------------------------------------------------------
# /help output includes all categories
# --------------------------------------------------------------------


class _RecordingApp:
    """A minimal app that records what
    ``/help`` would write.
    """
    def __init__(self) -> None:
        self.lines: list[str] = []

    def _append_status_line(self, line: str) -> None:
        self.lines.append(line)


def test_help_handler_writes_grouped_list():
    register(SlashCommand(
        name="ping",
        description="say pong",
        category="Fun",
        handler=lambda app, arg: None,
    ))
    app = _RecordingApp()
    help_cmd = find("help")
    help_cmd.handler(app, "")
    text = "\n".join(app.lines)
    assert "# Commands" in text
    assert "## Help" in text
    assert "## Fun" in text
    assert "/help" in text
    assert "/ping" in text
    assert "say pong" in text
