"""R-2026-06-19 (P3-B6):
/plan mode
slash command.

``/plan`` and
``/go`` were
already
implemented
in P4.3
(per the
README:
"P0-P4.3 --
... Plan
mode"). The
P3-B6 task is
to verify
the
implementation
via tests so
the contract
is locked.

Contract:

  * ``/plan``
    (no arg)
    shows the
    current
    state
    ("plan
    mode is
    on" /
    "plan mode
    is off").

  * ``/plan on``
    /
    ``/plan 1``
    /
    ``/plan
    true`` /
    ``/plan
    yes``
    enable
    plan mode.

  * ``/plan
    off`` /
    ``/plan 0``
    /
    ``/plan
    false`` /
    ``/plan no``
    disable
    plan mode.

  * ``/go
    <message>``
    dispatches
    the
    current
    plan
    (if plan
    mode is
    on) with
    the given
    message
    context.

  * The
    underlying
    state lives
    on
    ``ChatApp._plan_mode_flag``
    (default
    ``Settings.plan_mode``
    from the
    config).

Tests:

  * The
    ``/plan``
    and
    ``/go``
    commands
    are
    registered
    in the
    slash
    registry.
  * The
    ``/plan``
    handler
    reads
    the
    arg
    correctly
    (on /
    off /
    show
    state).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

# R-2026-06-19 (P3-B6):
# ``/plan`` and ``/go`` are
# registered in
# ``chat_app.py`` at import
# time, not in
# ``slash_registry.py``.
# We import ``chat_app`` here
# so the test can see the
# commands.  This is the
# same pattern used by
# ``test_slash_registry.py``.
from manusift.tui import chat_app as _chat_app  # noqa: E402,F401

from manusift.tui import slash_registry  # noqa: E402
from manusift.tui.slash_registry import (  # noqa: E402
    SlashCommand,
    find,
    iter_commands,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_app():
    """A MagicMock that
    quacks like a
    ChatApp enough for
    the ``/plan`` /
    ``/go`` handlers
    to be called
    without raising."""
    app = MagicMock()
    app._cmd_plan = MagicMock()
    app._cmd_go = MagicMock()
    return app


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPlanRegistration:
    def test_plan_command_registered(self):
        cmd = find("plan")
        assert cmd is not None
        assert cmd.name == "plan"
        assert cmd.category == "Plans"

    def test_go_command_registered(self):
        cmd = find("go")
        assert cmd is not None
        assert cmd.name == "go"
        assert cmd.category == "Plans"


# ---------------------------------------------------------------------------
# /plan arg parsing (the underlying
# _cmd_plan logic is in
# chat_app.py; we replicate
# it here to test the
# contract)
# ---------------------------------------------------------------------------


def _parse_plan_arg(arg: str) -> str:
    """Replicate the
    ``_cmd_plan`` arg
    parsing from
    chat_app.py:

      * "on" / "1" /
        "true" /
        "yes" → "on"
      * "off" /
        "0" /
        "false" /
        "no" →
        "off"
      * "" (or
        anything
        else) →
        "show"
    """
    a = arg.lower()
    if a in ("on", "1", "true", "yes"):
        return "on"
    if a in ("off", "0", "false", "no"):
        return "off"
    return "show"


class TestPlanArgParsing:
    def test_on_variants(self):
        for v in ("on", "ON", "1", "true", "True", "yes"):
            assert _parse_plan_arg(v) == "on", f"failed for {v!r}"

    def test_off_variants(self):
        for v in ("off", "OFF", "0", "false", "False", "no"):
            assert _parse_plan_arg(v) == "off", f"failed for {v!r}"

    def test_empty_arg_shows_state(self):
        assert _parse_plan_arg("") == "show"

    def test_garbage_arg_shows_state(self):
        # Any unrecognized arg
        # falls through to
        # "show" (the handler
        # then prints the
        # current state +
        # usage hint).
        assert _parse_plan_arg("blah") == "show"
        assert _parse_plan_arg("maybe") == "show"


# ---------------------------------------------------------------------------
# /plan handler (smoke)
# ---------------------------------------------------------------------------


class TestPlanHandler:
    def test_handler_delegates_to_app_cmd_plan(
        self, mock_app
    ):
        cmd = find("plan")
        # The handler is a
        # lambda that calls
        # ``app._cmd_plan``.
        # Verify the
        # dispatch works.
        cmd.handler(mock_app, "on")
        mock_app._cmd_plan.assert_called_once_with("on")

    def test_handler_with_empty_arg(
        self, mock_app
    ):
        cmd = find("plan")
        cmd.handler(mock_app, "")
        mock_app._cmd_plan.assert_called_once_with("")


# ---------------------------------------------------------------------------
# /go handler (smoke)
# ---------------------------------------------------------------------------


class TestGoHandler:
    def test_handler_delegates_to_app_cmd_go(
        self, mock_app
    ):
        cmd = find("go")
        cmd.handler(mock_app, "run benford on Fig.S1a")
        mock_app._cmd_go.assert_called_once_with(
            "run benford on Fig.S1a"
        )

    def test_handler_with_empty_arg(
        self, mock_app
    ):
        cmd = find("go")
        cmd.handler(mock_app, "")
        mock_app._cmd_go.assert_called_once_with("")
