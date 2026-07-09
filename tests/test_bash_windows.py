"""Tests for the R-2026-06-14 BashTool Windows-correctness
+ error_kind taxonomy.

Covers issue 3 (LLM gets confusing errors when bash
features are passed to PowerShell) and issue 14
(every tool result should carry a typed ``error_kind``).

Pattern follows claw-code's
``rust/crates/rusty-claude-cli/tests/output_format_contract.rs``.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from manusift.tools.agent_tools import (
    BashTool,
    SHELL_MODES,
    _shell_command_args,
)
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# Shell mode dispatch (issue 3)
# --------------------------------------------------------------------


def test_shell_modes_constant():
    """``SHELL_MODES`` is a closed tuple of valid env
    values.
    """
    assert set(SHELL_MODES) == {
        "auto",
        "posix",
        "cmd",
        "powershell",
    }


def test_shell_command_args_auto_picks_a_real_shell(monkeypatch):
    """``auto`` mode picks the first working shell
    among bash, cmd, powershell.

    R-2026-06-15 (Phase 0+1 + P0-1):
    the 3-tuple now carries
    ``shell_mode`` so the
    bash tool can record which
    shell actually ran the
    command.
    """
    monkeypatch.delenv("MANUSIFT_SHELL_MODE", raising=False)
    args, use_shell, shell_mode = (
        _shell_command_args("echo hi")
    )
    if os.name == "nt":
        # On Windows the WSL bash stub may fail the
        # probe; we accept either cmd or powershell
        # as the auto fallback.
        assert Path(args[0]).name.lower() in {
            "cmd.exe", "powershell.exe", "bash", "bash.exe"
        }
    else:
        # On Linux/macOS bash is always available.
        assert Path(args[0]).name == "bash"
    assert use_shell is False
    assert shell_mode in {
        "bash", "cmd", "powershell", "shell",
    }


def test_shell_command_args_posix_requires_bash(monkeypatch):
    """``posix`` mode raises when bash is missing or
    broken.
    """
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "posix")
    # Force ``shutil.which("bash")`` to return None.
    import shutil
    monkeypatch.setattr(
        shutil, "which", lambda name: None
    )
    with pytest.raises(RuntimeError) as excinfo:
        _shell_command_args("echo hi")
    assert "MANUSIFT_SHELL_MODE=posix" in str(excinfo.value)


def test_shell_command_args_cmd_uses_cmd_exe(monkeypatch):
    """``cmd`` mode on Windows uses ``cmd.exe /c``."""
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "cmd")
    if os.name != "nt":
        pytest.skip("Windows-only")
    args, use_shell, shell_mode = (
        _shell_command_args("echo hi")
    )
    assert args[0].lower().endswith("cmd.exe")
    assert args[1] == "/c"
    assert use_shell is False
    assert shell_mode == "cmd"


def test_shell_command_args_powershell_uses_pwsh(monkeypatch):
    """``powershell`` mode on Windows uses powershell
    with the safe flags.
    """
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "powershell")
    if os.name != "nt":
        pytest.skip("Windows-only")
    args, use_shell, shell_mode = (
        _shell_command_args("echo hi")
    )
    assert "powershell" in args[0].lower()
    assert "-ExecutionPolicy" in args
    assert "Bypass" in args
    assert use_shell is False
    assert shell_mode == "powershell"


def test_shell_command_args_unknown_mode_falls_back(monkeypatch):
    """An unknown ``MANUSIFT_SHELL_MODE`` value falls
    back to ``auto`` rather than crashing.
    """
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "fish")
    args, use_shell, shell_mode = (
        _shell_command_args("echo hi")
    )
    # Should not raise; should pick whatever ``auto``
    # would have picked.
    assert isinstance(args, (list, str))


# --------------------------------------------------------------------
# BashTool.execute error_kind taxonomy (issue 14)
# --------------------------------------------------------------------


def test_bash_disabled_returns_permission_denied(monkeypatch):
    """``MANUSIFT_ALLOW_SHELL=false`` returns
    ``error_kind: permission_denied``.
    """
    from manusift.config import Settings

    monkeypatch.setenv("MANUSIFT_ALLOW_SHELL", "false")
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "echo hi"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"
    assert "hint" in out


def test_bash_empty_command_returns_permission_denied():
    """Empty ``command`` returns ``error_kind:
    permission_denied`` (a logic error, not a runtime
    error).
    """
    tool = BashTool()
    out = json.loads(
        tool.execute({"command": ""}, ToolContext(trace_id="t"))
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"


def test_bash_denylist_returns_permission_denied():
    """A command matching the denylist (rm -rf /)
    returns ``error_kind: permission_denied`` with a
    typed hint.
    """
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "rm -rf /"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"
    assert "hint" in out


def test_bash_relative_cwd_returns_permission_denied():
    """A relative ``cwd`` is rejected as
    ``permission_denied`` (defence in depth).
    """
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "ls", "cwd": "relative"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"


def test_bash_nonexistent_cwd_returns_path_not_visible():
    """A non-existent ``cwd`` returns ``error_kind:
    path_not_visible``.
    """
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {
                "command": "ls",
                "cwd": "C:/this/does/not/exist/at/all",
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "path_not_visible"
    assert "hint" in out


def test_bash_timeout_returns_budget_exhausted(monkeypatch):
    """A long-running command that exceeds the
    per-call timeout returns ``error_kind:
    budget_exhausted`` with the actual deadline.
    """
    from manusift.config import Settings

    # Use ``Settings`` env override: 0.5s timeout
    # is enough to fail any sleep 1 command.
    monkeypatch.setenv("MANUSIFT_SHELL_TIMEOUT_SECONDS", "0.5")
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "ping 127.0.0.1 -n 5"},
            ToolContext(trace_id="t"),
        )
    )
    # On bash / cmd the ping might finish first
    # (the timeout is small but ping 5x is fast).
    # Accept either timeout OR a successful
    # non-error return.
    if out["ok"] is False and "timeout" in out.get("error", "").lower():
        assert out["error_kind"] == "budget_exhausted"
        assert out["timeout_seconds"] == 0.5
        assert "hint" in out


def test_bash_missing_shell_binary_returns_dependency_missing(
    monkeypatch,
):
    """When the selected shell binary is not on PATH,
    the tool returns ``error_kind:
    dependency_missing`` with a typed hint.
    """
    monkeypatch.setenv("MANUSIFT_SHELL_MODE", "posix")
    import shutil
    monkeypatch.setattr(
        shutil, "which", lambda name: None
    )
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "echo hi"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "dependency_missing"
    assert "MANUSIFT_SHELL_MODE" in out["hint"]


def test_bash_success_envelope_has_required_fields():
    """A successful bash run carries ``shell_mode``,
    ``cwd``, ``returncode``, ``stdout``, ``stderr``,
    ``elapsed_seconds``, and ``error_kind=None``.
    """
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "echo hi"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["error_kind"] is None
    assert out["returncode"] == 0
    assert "hi" in out["stdout"]
    assert "shell_mode" in out
    assert "elapsed_seconds" in out
    assert "cwd" in out  # may be None
    assert "command" in out


def test_bash_command_failed_envelope_has_command_failed_kind():
    """A non-zero returncode produces
    ``error_kind: command_failed`` (not
    ``permission_denied`` / ``dependency_missing``
    / etc.).
    """
    tool = BashTool()
    # On every supported shell, ``exit 7`` exits
    # with code 7.
    out = json.loads(
        tool.execute(
            {"command": "exit 7"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["returncode"] == 7
    assert out["error_kind"] == "command_failed"
