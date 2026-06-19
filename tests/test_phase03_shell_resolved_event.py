"""Tests for the R-2026-06-15 (Phase 0.3)
``bash.shell_resolved`` event.

The contract:

  * The first time ``BashTool.execute()``
    runs a shell command, the
    bus sees a ``bash.shell_resolved``
    event with ``shell_mode``
    ("cmd" / "powershell" / "bash"
    / "sh" / "shlex") and the
    command.
  * The event emission is best-
    effort: a missing or
    broken bus does not
    break the bash tool.
  * The LLM-visible result
    envelope carries the
    ``shell_mode`` (already
    shipped; this test pins
    that the event payload
    matches the envelope).
"""
from __future__ import annotations

import json

import pytest

from manusift.events import (
    Event,
    get_bus,
    reset_bus,
)
from manusift.tools.agent_tools import BashTool
from manusift.tools.tool import ToolContext


@pytest.fixture
def fresh_bus():
    """Reset the bus before each
    test.
    """
    reset_bus()
    yield
    reset_bus()


def test_bash_emits_shell_resolved_event(
    fresh_bus, monkeypatch
):
    """The bash tool emits a
    ``bash.shell_resolved``
    event before running the
    command.
    """
    seen: list[Event] = []
    bus = get_bus()
    bus.subscribe(
        type(
            "_L",
            (),
            {
                "on_event": lambda self, e: seen.append(e)
                if e.type == "bash.shell_resolved"
                else None
            },
        )()
    )
    try:
        tool = BashTool()
        out = tool.execute(
            {"command": "echo hello"},
            ToolContext(trace_id="t-1"),
        )
        # The bus sees the
        # event.
        assert any(
            e.type == "bash.shell_resolved"
            for e in seen
        ), f"missing event: {[e.type for e in seen]}"
        # And the event
        # payload carries
        # ``shell_mode``.
        ev = next(
            e for e in seen
            if e.type == "bash.shell_resolved"
        )
        assert "shell_mode" in ev.payload
        # The command was
        # actually run, so
        # the envelope's
        # shell_mode should
        # match the event's.
        env = json.loads(out)
        if env.get("ok"):
            assert env["shell_mode"] == (
                ev.payload["shell_mode"]
            )
    finally:
        # The listener is
        # auto-removed on
        # ``reset_bus()`` in
        # the fixture
        # teardown, but be
        # explicit.
        reset_bus()


def test_bash_event_payload_includes_command(
    fresh_bus, monkeypatch
):
    """The event payload
    includes the original
    command so the TUI can
    show what triggered the
    shell resolution.
    """
    seen: list[Event] = []
    bus = get_bus()
    bus.subscribe(
        type(
            "_L",
            (),
            {
                "on_event": lambda self, e: seen.append(e)
                if e.type == "bash.shell_resolved"
                else None
            },
        )()
    )
    try:
        tool = BashTool()
        tool.execute(
            {"command": "echo cmd-test"},
            ToolContext(trace_id="t-2"),
        )
        assert seen
        assert seen[0].payload["command"] == (
            "echo cmd-test"
        )
    finally:
        reset_bus()
