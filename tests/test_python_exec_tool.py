"""Tests for ``manusift.tools.python_exec`` (R-2026-06-14).

Covers issue 9 (no canonical Python interpreter the
agent can rely on) and issue 10 (no safe way to run
Python snippets in the TUI; LLM was forced to write
shell scripts with broken quoting).

Pattern follows claw-code's
``rust/crates/rusty-claude-cli/tests/output_format_contract.rs``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from manusift.config import Settings
from manusift.tools.python_exec import (
    PythonExecTool,
    _MAX_OUT,
    _SOFT_DENY_IMPORTS,
)
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# Settings: python_executable default
# --------------------------------------------------------------------


def test_settings_python_executable_defaults_to_sys_executable():
    """``Settings.python_executable`` is
    ``sys.executable`` at instantiation time when no
    env var is set.
    """
    s = Settings()
    assert s.python_executable == sys.executable
    assert Path(s.python_executable).exists()


def test_settings_python_executable_respects_env(monkeypatch):
    """``MANUSIFT_PYTHON_EXECUTABLE`` overrides the
    default.
    """
    monkeypatch.setenv(
        "MANUSIFT_PYTHON_EXECUTABLE", r"C:\Python311\python.exe"
    )
    s = Settings()
    assert s.python_executable == r"C:\Python311\python.exe"


# --------------------------------------------------------------------
# python_exec: end-to-end
# --------------------------------------------------------------------


def test_python_exec_runs_simple_expression(tmp_path, monkeypatch):
    """A trivial ``print(1+1)`` snippet returns ok=True
    with ``2`` in stdout.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {"code": "print(1 + 1)"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert "2" in out["stdout"]
    assert out["returncode"] == 0
    assert out["error_kind"] is None
    assert Path(out["script_path"]).exists()


def test_python_exec_uses_manusift_imports(tmp_path, monkeypatch):
    """``from manusift.ingest.xlsx import parse_data_file``
    works because the script uses the same Python +
    same ``sys.path`` as the parent process.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {
                "code": (
                    "from manusift.ingest.xlsx "
                    "import parse_data_file\n"
                    "print(parse_data_file.__name__)"
                )
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert "parse_data_file" in out["stdout"]


def test_python_exec_returns_error_kind_for_exception(
    tmp_path, monkeypatch
):
    """A snippet that raises returns
    ``error_kind: "command_failed"`` (not
    ``permission_denied``) with the traceback in
    stderr.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {
                "code": "raise ValueError('boom')"
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "command_failed"
    assert "boom" in out["stderr"]


def test_python_exec_missing_code_is_permission_denied(
    tmp_path, monkeypatch
):
    """An empty ``code`` is rejected with
    ``error_kind: permission_denied``.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute({"code": ""}, ToolContext(trace_id="t"))
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"


def test_python_exec_timeout_returns_budget_exhausted(
    tmp_path, monkeypatch
):
    """A snippet that exceeds the timeout returns
    ``error_kind: budget_exhausted`` with the
    actual deadline.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {
                "code": "import time; time.sleep(5)",
                "timeout_seconds": 0.3,
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "budget_exhausted"
    assert out["timeout_seconds"] == 0.3


def test_python_exec_soft_deny_emits_hint_not_block(
    tmp_path, monkeypatch
):
    """A snippet that imports ``subprocess`` is
    allowed but the result envelope carries a
    "consider using bash" hint.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {
                "code": (
                    "import subprocess\n"
                    "print('allowed')"
                )
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert "subprocess" in (out.get("hint") or "")


def test_python_exec_output_truncation_caps_at_30kb(
    tmp_path, monkeypatch
):
    """Stdout > 30 KB is truncated; the envelope
    reports ``stdout_truncated=True``.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    big = 31_000  # 31 KB > 30 KB cap
    out = json.loads(
        tool.execute(
            {
                "code": (
                    f"print('x' * {big})"
                )
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["stdout_truncated"] is True
    assert len(out["stdout"]) <= _MAX_OUT + 100


def test_python_exec_writes_script_under_workspace(
    tmp_path, monkeypatch
):
    """The script is written to
    ``<workspace>/python_runs/<id>.py`` and is
    discoverable after the run.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path)
    )
    tool = PythonExecTool()
    out = json.loads(
        tool.execute(
            {"code": "print('hi')"},
            ToolContext(trace_id="t"),
        )
    )
    script = Path(out["script_path"])
    assert script.exists()
    assert script.parent.name == "python_runs"
    assert out["script_size_bytes"] > 0
    # The script header records the trace_id so
    # audits can correlate.
    body = script.read_text(encoding="utf-8")
    assert "trace_id: t" in body


def test_python_exec_in_registry():
    """The new tool is auto-registered.
    """
    from manusift.tools import tool_names
    names = tool_names()
    assert "python_exec" in names


# --------------------------------------------------------------------
# soft-deny import list
# --------------------------------------------------------------------


def test_soft_deny_imports_includes_subprocess():
    assert "subprocess" in _SOFT_DENY_IMPORTS
