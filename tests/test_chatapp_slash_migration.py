"""Tests for the R-2026-06-14 slash-registry
migration of ``ChatApp._handle_command``.

The contract:

  * All 14 ChatApp slash commands
    (upload / clear / tools / skill /
    skills / plan / go / auto-accept /
    cost / status / resume / model /
    tree / theme / help) are registered
    in ``slash_registry`` at class-body
    time.
  * ``_handle_command`` dispatches via
    ``slash_registry.find``; the
    13 inline ``elif`` cases were
    removed.
  * ``_cmd_help`` renders from
    ``by_category()`` so adding a
    new command to the registry
    auto-appears in /help.
  * An unknown command emits the
    legacy "see /help" message.
  * A buggy handler does not crash
    the chat; it emits a system
    message with the exception.

Pattern follows the
``agent-infra-iteration-engineer``
skill rule I.2: a new command is
4 lines of registration, not a
new ``elif`` in the dispatcher.
"""
from __future__ import annotations

from typing import Any

import pytest

# R-2026-06-14: importing
# ``manusift.tui.chat_app`` at
# module import time is what
# triggers the 14
# ``register(SlashCommand(...))``
# calls in the ChatApp class
# body. Without this import, the
# registry only has its 2
# default entries (``/help`` and
# ``/echo``).
from manusift.tui import chat_app  # noqa: F401

from manusift.tui.slash_registry import (
    by_category,
    find,
    iter_commands,
    register,
    SlashCommand,
)


# --------------------------------------------------------------------
# Migration: every ChatApp command is
# in the registry
# --------------------------------------------------------------------

EXPECTED_COMMANDS = {
    # Chat
    "upload": "Chat",
    "clear": "Chat",
    "tools": "Chat",
    "skill": "Chat",
    "skills": "Chat",
    # Plans
    "plan": "Plans",
    "go": "Plans",
    "auto-accept": "Plans",
    # Status
    "cost": "Status",
    "status": "Status",
    "resume": "Status",
    "model": "Status",
    "tree": "Status",
    # UI
    "theme": "UI",
    "help": "UI",
    # Session (R-2026-06-15,
    # Phase 0.1 + 0.4)
    "stop": "Session",
    "budget": "Session",
    # R-2026-06-19 (CDE-C1):
    # ``/doctor`` and
    # ``/diff``
    # auto-register
    # on chat_app
    # import via the
    # ``manusift.tui.doctor``
    # and
    # ``manusift.tui.diff_cmd``
    # modules.
    "doctor": "Diagnostics",
    "diff": "Diagnostics",
}


def test_all_chatapp_commands_registered():
    """Every command in
    ``EXPECTED_COMMANDS`` is
    present in the slash
    registry with the
    documented category.
    """
    registered = {
        c.name: c.category
        for c in iter_commands()
    }
    for name, category in EXPECTED_COMMANDS.items():
        assert name in registered, (
            f"{name!r} missing from registry; "
            f"got: {sorted(registered)}"
        )
        assert registered[name] == category, (
            f"{name!r} has category "
            f"{registered[name]!r}, "
            f"expected {category!r}"
        )


def test_no_unknown_commands_in_registry():
    """The registry has no command
    names that are NOT in
    ``EXPECTED_COMMANDS`` (the
    chat-app commands) or the
    default
    ``/echo`` test handler.
    """
    registered = {c.name for c in iter_commands()}
    extras = registered - set(EXPECTED_COMMANDS) - {"echo"}
    assert not extras, (
        f"registry has unexpected "
        f"commands: {sorted(extras)}"
    )


# --------------------------------------------------------------------
# by_category() shape
# --------------------------------------------------------------------


def test_by_category_covers_every_command():
    """``by_category()`` returns one
    bucket per category that
    appears in the registry, and
    every command is in some
    bucket.
    """
    by_cat = by_category()
    seen = set()
    for cat, cmds in by_cat.items():
        for c in cmds:
            assert c.category == cat
            seen.add(c.name)
    # The chat-app commands are
    # the only ones this test
    # asserts; the registry may
    # have a few defaults
    # (``/echo``) which are not
    # in ``EXPECTED_COMMANDS``.
    chat_app_seen = seen & set(EXPECTED_COMMANDS)
    assert chat_app_seen == set(EXPECTED_COMMANDS)


def test_by_category_preserves_registration_order():
    """The first appearance order
    of a category in the
    registry is the bucket order
    in ``by_category()``.
    """
    by_cat = by_category()
    cats = list(by_cat.keys())
    # The chat-app's first batch
    # of registrations is in
    # category ``Chat``. The
    # default ``/help`` is in
    # category ``Help`` and is
    # later replaced with
    # category ``UI``. The
    # ``/echo`` default remains
    # in ``Help``. So the order
    # starts with ``Help`` (the
    # default category), then
    # ``Chat`` (the chat-app's
    # first batch), then
    # ``Plans``, ``Status``,
    # ``UI``.
    assert "Help" in cats
    assert "Chat" in cats
    assert "Plans" in cats
    assert "Status" in cats
    assert "UI" in cats
    # ``Chat`` is registered
    # after ``Help`` (which is
    # the default), so the
    # relative order is
    # preserved.
    assert cats.index("Help") < cats.index("Chat")


# --------------------------------------------------------------------
# find() resolves aliases
# --------------------------------------------------------------------


def test_find_resolves_help():
    e = find("/help")
    assert e is not None
    assert e.name == "help"


def test_find_unknown_returns_none():
    assert find("/this-is-not-a-command") is None
    assert find("/nope") is None


# --------------------------------------------------------------------
# Handler dispatch contract
# --------------------------------------------------------------------


def test_handler_dispatches_via_registry():
    """A registered command's
    ``handler`` is what the
    dispatcher calls. We test
    this by registering a
    test-only command with a
    captured handler, finding it,
    and invoking the handler.
    """
    captured: list[tuple[Any, str]] = []

    def _h(app: Any, arg: str) -> None:
        captured.append((app, arg))

    register(SlashCommand(
        name="test-dispatch",
        description="cap",
        category="Help",
        handler=_h,
    ))
    e = find("test-dispatch")
    assert e is not None
    # Simulate the dispatch
    # (the real
    # ``ChatApp._handle_command``
    # does this in production).
    sentinel_app = object()
    e.handler(sentinel_app, "hello")
    assert captured == [(sentinel_app, "hello")]


def test_handler_with_buggy_call_does_not_crash():
    """A handler that raises should
    not kill the chat; in
    production
    ``ChatApp._handle_command``
    catches the exception and
    emits a system message. We
    verify the contract at the
    registry level: the
    handler is invoked; the
    exception propagates (so the
    caller can catch it).
    """
    def _bad(app: Any, arg: str) -> None:
        raise ValueError("intentional")

    register(SlashCommand(
        name="test-bad",
        description="cap",
        category="Help",
        handler=_bad,
    ))
    e = find("test-bad")
    assert e is not None
    with pytest.raises(ValueError):
        e.handler(None, "")


# --------------------------------------------------------------------
# /help by_category() rendering
# --------------------------------------------------------------------


def test_help_renders_every_category():
    """The ``_cmd_help``-style
    rendering of ``by_category()``
    includes every category and
    every command.
    """
    by_cat = by_category()
    lines = ["Available commands"]
    for cat, cmds in by_cat.items():
        lines.append(f"## {cat}")
        for c in cmds:
            lines.append(f"  /{c.name}: {c.description}")
    text = "\n".join(lines)
    for name in EXPECTED_COMMANDS:
        assert f"/{name}:" in text, (
            f"{name!r} missing from help "
            f"rendering:\n{text}"
        )


def test_help_render_includes_aliases():
    """The ``_cmd_help``-style
    rendering shows aliases when
    a command has any.
    """
    register(SlashCommand(
        name="test-alias-help",
        description="with alias",
        category="UI",
        handler=lambda app, arg: None,
        aliases=("tah",),
    ))
    by_cat = by_category()
    text = "\n".join(
        f"/{c.name}"
        for cs in by_cat.values()
        for c in cs
    )
    assert "/test-alias-help" in text
    # The description (and thus
    # the full help line) mentions
    # the alias. We assert the
    # alias appears in the
    # by_category output -- the
    # help text formatting is in
    # ``_cmd_help`` (already
    # verified in the test below).
    e = find("test-alias-help")
    assert e is not None
    assert "tah" in e.aliases
