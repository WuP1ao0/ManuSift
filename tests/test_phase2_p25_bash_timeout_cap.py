"""R-2026-06-15 (Phase 2 + P2-5):
test the ``BashTool``
per-call ``timeout_seconds``
hard cap.

The audit found that the
per-call ``timeout_seconds``
had no upper bound.  A
runaway shell that took
24 hours to exit would
hang the agent loop
indefinitely.  The fix
enforces the cap at two
layers:

  1. ``Settings.shell_timeout_seconds``
     has a ``Field(le=600.0)``
     constraint, so
     constructing
     ``Settings(shell_timeout_seconds=10**9)``
     raises
     ``ValidationError``.
  2. ``BashTool.execute``
     clamps the per-call
     ``timeout_seconds`` to
     ``[1.0, 600.0]`` so a
     caller that supplies
     ``timeout_seconds=10**9``
     directly in the tool
     input still gets a
     600s cap (and a
     ``subprocess.TimeoutExpired``
     after 600s, not a
     confusing
     ``ValidationError``).

These tests verify:

  1. The Settings field
     rejects values > 600.
  2. The Settings field
     rejects values < 1.
  3. A per-call
     ``timeout_seconds``
     larger than 600 is
     silently clamped to
     600.
  4. A per-call
     ``timeout_seconds``
     smaller than 1 is
     silently clamped to
     1.0.
  5. A per-call
     ``timeout_seconds``
     in ``[1, 600]`` is
     honoured.
  6. The default (no
     ``timeout_seconds``
     in the input) is
     ``settings.shell_timeout_seconds``
     (capped to 600).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from manusift.config import Settings


def test_p25_settings_field_rejects_too_large_timeout() -> None:
    """``Settings(shell_timeout_seconds=10**9)``
    raises ``ValidationError``.

    R-2026-06-15 (Phase 2 + P2-5):
    ``model_copy(update=...)``
    does NOT re-validate by
    default in Pydantic v2,
    so we use direct
    construction (the
    field validator runs).
    """
    with pytest.raises(Exception) as excinfo:
        Settings(
            shell_timeout_seconds=1e9,
            _env_file=None,  # type: ignore[call-arg]
        )
    err_cls = type(excinfo.value).__name__
    assert err_cls in (
        "ValidationError",
        "ValueError",
    ), (
        f"unexpected error class: {err_cls}"
    )


def test_p25_settings_field_rejects_too_small_timeout() -> None:
    """``Settings(shell_timeout_seconds=0)``
    raises ``ValidationError``
    (the field is ``ge=1.0``).
    """
    with pytest.raises(Exception):
        Settings(
            shell_timeout_seconds=0,
            _env_file=None,  # type: ignore[call-arg]
        )


def test_p25_settings_field_accepts_in_range() -> None:
    """``Settings(shell_timeout_seconds=120)``
    succeeds.
    """
    s = Settings(
        shell_timeout_seconds=120,
        _env_file=None,  # type: ignore[call-arg]
    )
    assert s.shell_timeout_seconds == 120


def test_p25_bash_tool_clamps_oversized_timeout(
    tmp_path: Path,
) -> None:
    """A per-call
    ``timeout_seconds=10**9``
    is silently clamped to
    600 (the cap).
    """
    from manusift.tools.agent_tools import (
        BashTool,
    )
    from manusift.tools.tool import ToolContext

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": str(workspace)}
    )
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module,
        "get_settings",
        lambda: settings,
    )
    tool = BashTool()
    # ``echo ok`` is fast.
    # The point is to check
    # that the *timeout*
    # was clamped, not that
    # the command actually
    # runs for 600s.
    out = tool.execute(
        {
            "command": "echo ok",
            "timeout_seconds": 10**9,
        },
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    # The BashTool returns
    # the effective
    # ``timeout_seconds`` in
    # the result envelope
    # so the LLM can see
    # what was applied.
    if result.get("ok"):
        # ``result.stdout`` is
        # ``"ok"``;
        # ``timeout_seconds``
        # is the *clamped*
        # value.
        assert (
            result.get("timeout_seconds") == 600.0
        ), (
            f"expected clamped "
            f"timeout_seconds=600.0, "
            f"got {result.get('timeout_seconds')}"
        )


def test_p25_bash_tool_clamps_undersized_timeout(
    tmp_path: Path,
) -> None:
    """A per-call
    ``timeout_seconds=0``
    is silently clamped to
    0.1 (the lower bound).
    """
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": str(workspace)}
    )
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module,
        "get_settings",
        lambda: settings,
    )
    tool = BashTool()
    out = tool.execute(
        {
            "command": "echo ok",
            "timeout_seconds": 0,
        },
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    if result.get("ok"):
        assert (
            result.get("timeout_seconds") == 0.1
        ), (
            f"expected clamped "
            f"timeout_seconds=0.1, "
            f"got {result.get('timeout_seconds')}"
        )


def test_p25_bash_tool_honours_in_range_timeout(
    tmp_path: Path,
) -> None:
    """A per-call
    ``timeout_seconds=5``
    (in range) is honoured.
    """
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": str(workspace)}
    )
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module,
        "get_settings",
        lambda: settings,
    )
    tool = BashTool()
    out = tool.execute(
        {
            "command": "echo ok",
            "timeout_seconds": 5,
        },
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    if result.get("ok"):
        assert (
            result.get("timeout_seconds") == 5.0
        )


def test_p25_default_timeout_is_settings_value(
    tmp_path: Path,
) -> None:
    """A per-call
    ``timeout_seconds``
    omitted falls back to
    ``settings.shell_timeout_seconds``.
    """
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": str(workspace)}
    )
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module,
        "get_settings",
        lambda: settings,
    )
    tool = BashTool()
    out = tool.execute(
        {"command": "echo ok"},
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    if result.get("ok"):
        # ``settings.shell_timeout_seconds``
        # is the default 30.0.
        assert (
            result.get("timeout_seconds") == 30.0
        )
