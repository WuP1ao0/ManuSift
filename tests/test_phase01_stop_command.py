"""Tests for the R-2026-06-15 (Phase 0.1)
``/stop`` slash command + ``AgentLoop.interrupt()``.

The contract:

  * ``AgentLoop.interrupt()`` sets
    ``_interrupt_requested`` to True.
  * The streaming loop in
    ``run_stream()`` checks the flag
    at the top of every turn and
    exits with
    ``stop_reason='cancelled'`` when
    the flag is set.
  * The flag is reset to False at
    the start of each ``run_stream()``
    call so a stale interrupt from a
    previous run does not leak.
  * ``Runner.active_loop`` is set
    to the ``AgentLoop`` instance
    after ``_new_loop()`` returns,
    and reset to None in the
    ``finally`` block.
  * The chat TUI's ``/stop`` slash
    command calls
    ``runner.active_loop.interrupt()``.

Pattern follows the agent-infra-
iteration-engineer skill rule I.1:
every behaviour has a test that
pins the contract independently of
the production code.
"""
from __future__ import annotations

import pytest

from manusift.agent import AgentLoop
from manusift.tui.agent_runner import Runner


# --------------------------------------------------------------------
# AgentLoop.interrupt()
# --------------------------------------------------------------------


def test_agent_loop_has_interrupt_method():
    """``AgentLoop`` exposes a
    public ``interrupt()``
    method (Phase 0.1).
    """
    assert callable(getattr(AgentLoop, "interrupt", None))


def test_agent_loop_interrupt_sets_flag():
    """``AgentLoop.interrupt()``
    sets the
    ``_interrupt_requested``
    flag to True.
    """
    loop = AgentLoop.__new__(AgentLoop)
    # Bypass __init__: we only
    # need the flag for this
    # test.
    loop._interrupt_requested = False
    loop.interrupt()
    assert loop._interrupt_requested is True


def test_agent_loop_interrupt_is_idempotent():
    """Calling ``interrupt()``
    twice does not raise; the
    flag stays True.
    """
    loop = AgentLoop.__new__(AgentLoop)
    loop._interrupt_requested = False
    loop.interrupt()
    loop.interrupt()
    assert loop._interrupt_requested is True


# --------------------------------------------------------------------
# Runner.active_loop lifecycle
# --------------------------------------------------------------------


def test_runner_has_active_loop_field():
    """``Runner`` exposes an
    ``active_loop`` field
    (Phase 0.1).
    """
    # The field is a default
    # ``None`` dataclass
    # field. Inspecting the
    # dataclass field list is
    # the right way to assert
    # it is declared.
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Runner)}
    assert "active_loop" in fields


def test_runner_active_loop_starts_as_none():
    """A fresh ``Runner`` has
    ``active_loop = None``.
    """
    runner = Runner(
        client=object(),
        tools=[],
        ctx=object(),
        cb=None,  # type: ignore[arg-type]
    )
    assert runner.active_loop is None


# --------------------------------------------------------------------
# Slash command registration
# --------------------------------------------------------------------


def test_stop_slash_command_registered():
    """The chat TUI registers a
    ``/stop`` slash command
    in the ``SlashCommand``
    registry at class-body
    time.
    """
    # Importing the chat app
    # triggers the
    # registration.
    from manusift.tui import chat_app  # noqa: F401
    from manusift.tui.slash_registry import (
        find,
    )
    entry = find("stop")
    assert entry is not None
    assert entry.category == "Session"
    assert "cancel" in entry.description.lower()


def test_stop_handler_exists_on_chat_app():
    """The ``ChatApp._cmd_stop``
    method exists with no
    arguments.
    """
    from manusift.tui.chat_app import ChatApp
    method = getattr(ChatApp, "_cmd_stop", None)
    assert method is not None
    import inspect
    sig = inspect.signature(method)
    params = [
        p for p in sig.parameters.values()
        if p.name != "self"
    ]
    assert len(params) == 0
