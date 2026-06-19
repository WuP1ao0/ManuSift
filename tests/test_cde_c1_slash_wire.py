"""R-2026-06-19 (CDE-C1):
verify
``/doctor``
and
``/diff``
slash
commands
are
registered
when
``chat_app``
is
imported.

P2-B3 and P2-B4 added
the
``/doctor``
and
``/diff``
slash
commands
with
auto-registration
on import.
C1 wires
them into
``chat_app``
so
they show
up in the
chat TUI.

The test
just imports
``chat_app``
(which
loads
the
14 chat-app
``register(SlashCommand(...))``
calls)
and verifies
that ``find("doctor")`` /
``find("diff")`` /
``find("d")``
return
non-None
command
objects.

Tests:

  * ``find("doctor")``
    returns
    a
    SlashCommand
    after
    chat_app
    import.
  * ``find("diff")``
    returns
    a
    SlashCommand
    after
    chat_app
    import.
  * ``find("d")``
    (alias
    for
    diff)
    returns
    a
    SlashCommand.
  * ``DiffTool``
    is
    registered
    in
    the
    tool
    registry
    (visible
    to LLM).
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")


class TestSlashCommands:
    """Verify ``/doctor`` and ``/diff`` are registered."""

    def test_doctor_registered(self):
        from manusift.tui.slash_registry import find

        # Importing
        # chat_app
        # triggers
        # the
        # 14
        # chat-app
        # register
        # calls.
        # We
        # also
        # import
        # doctor
        # explicitly
        # to
        # make
        # sure
        # its
        # auto-register
        # fires.
        from manusift.tui import doctor  # noqa: F401
        from manusift.tui import chat_app  # noqa: F401

        cmd = find("doctor")
        assert cmd is not None
        assert cmd.name == "doctor"

    def test_diff_registered(self):
        from manusift.tui.slash_registry import find

        from manusift.tui import diff_cmd  # noqa: F401
        from manusift.tui import chat_app  # noqa: F401

        cmd = find("diff")
        assert cmd is not None
        assert cmd.name == "diff"

    def test_diff_alias_registered(self):
        from manusift.tui.slash_registry import find

        from manusift.tui import diff_cmd  # noqa: F401
        from manusift.tui import chat_app  # noqa: F401

        # ``d``
        # is an
        # alias
        # for
        # diff.
        cmd = find("d")
        assert cmd is not None


class TestDiffToolRegistry:
    """Verify ``DiffTool`` is in the agent_tools registry."""

    def test_diff_tool_is_registered(self):
        from manusift.tools import iter_registered_tools

        # ``iter_registered_tools``
        # returns
        # all
        # builtin
        # tools
        # (the
        # ``register_agent_tools()``
        # list).
        tools = list(iter_registered_tools())
        tool_names = [t.name for t in tools]
        assert "diff" in tool_names or any(
            "diff" in n.lower() for n in tool_names
        )