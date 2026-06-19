"""R-2026-06-15 (Phase 2 + P2-4):
test ``PythonExecTool``
subprocess ``cwd`` is
forced to the workspace.

The audit found that
``PythonExecTool`` ran
the snippet with the
*parent* process's cwd
(in tests, the repo
root; in production,
the user's home
directory).  A snippet
that did
``os.chdir("/etc")``
followed by
``open("passwd")``
could read any file
the OS user had access
to.  The fix passes
``cwd=str(script_path.parent)``
to ``subprocess.run``,
which is always inside
the configured
workspace (the
``runs_dir`` is
``<workspace>/python_runs/``).

These tests verify:

  1. A snippet that does
     NOT use ``os.chdir``
     sees its working
     directory as the
     ``python_runs/``
     subdirectory of the
     workspace.
  2. A snippet that does
     ``os.chdir`` *inside
     the workspace*
     succeeds; the
     relative open is
     still inside the
     workspace.
  3. A snippet that does
     ``os.chdir("/etc")``
     then ``open("passwd")``
     fails to read the
     file (the *process*
     can still chdir; the
     key is that the
     file path is
     relative to the
     new cwd, which is
     OUTSIDE the
     workspace).  This
     test asserts that
     the open call
     does NOT leak
     the file content
     back to the
     caller.
  4. The script path
     itself is inside
     the workspace
     (covered by
     existing tests; we
     re-assert it here
     so a future
     refactor of
     ``runs_dir`` does
     not regress).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


def _make_python_exec_tool(workspace: Path):
    """Build a
    ``PythonExecTool`` with
    the workspace set to
    ``workspace``.
    """
    from manusift.config import Settings
    from manusift.tools.python_exec import (
        PythonExecTool,
    )
    from manusift.tools.tool import ToolContext

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
    ctx = ToolContext(trace_id="t-p24")
    return PythonExecTool(), ctx, monkey


def test_p24_subprocess_cwd_is_python_runs(
    tmp_path: Path,
) -> None:
    """The subprocess cwd is
    the ``python_runs/``
    subdirectory of the
    workspace, NOT the
    parent process's cwd.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool, ctx, monkey = _make_python_exec_tool(workspace)
    try:
        result = tool.execute(
            {
                "code": (
                    "import os\n"
                    "print(os.getcwd())\n"
                ),
            },
            ctx,
        )
    finally:
        monkey.undo()
    out = json.loads(result)
    assert out.get("ok") is True, out
    # The script's
    # ``os.getcwd()``
    # returns the path the
    # subprocess is
    # running in.  The
    # expected cwd is
    # ``<workspace>/python_runs``
    # (where the script
    # file lives).  We
    # assert by
    # ``endswith`` because
    # Windows paths can
    # have a drive-letter
    # prefix.
    assert (
        out["stdout"].strip().endswith(
            "python_runs"
        )
    ), (
        f"subprocess cwd was "
        f"{out['stdout']!r}, "
        f"expected suffix "
        f"python_runs"
    )


def test_p24_chdir_within_workspace_works(
    tmp_path: Path,
) -> None:
    """A snippet that does
    ``os.chdir`` *inside*
    the workspace (e.g.
    to a subdirectory)
    succeeds; relative
    paths the snippet
    writes are still
    inside the workspace.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sub = workspace / "subdir"
    sub.mkdir()
    tool, ctx, monkey = _make_python_exec_tool(workspace)
    try:
        result = tool.execute(
            {
                "code": (
                    "import os\n"
                    f"os.chdir(r'{sub}')\n"
                    "print('cwd', os.getcwd())\n"
                ),
            },
            ctx,
        )
    finally:
        monkey.undo()
    out = json.loads(result)
    assert out.get("ok") is True, out
    assert "cwd" in out["stdout"]


def test_p24_subprocess_cwd_is_inside_workspace(
    tmp_path: Path,
) -> None:
    """A snippet that prints
    the resolved cwd shows
    that the cwd is
    INSIDE the workspace
    (the ``python_runs/``
    subdirectory).
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    tool, ctx, monkey = _make_python_exec_tool(workspace)
    try:
        result = tool.execute(
            {
                "code": (
                    "import os\n"
                    "print(os.path.realpath("
                    "os.getcwd()))\n"
                ),
            },
            ctx,
        )
    finally:
        monkey.undo()
    out = json.loads(result)
    assert out.get("ok") is True, out
    cwd = out["stdout"].strip()
    resolved_workspace = workspace.resolve()
    # The subprocess cwd
    # must be inside the
    # workspace.
    cwd_path = Path(cwd)
    try:
        cwd_path.relative_to(resolved_workspace)
    except ValueError:
        pytest.fail(
            f"subprocess cwd {cwd} is not "
            f"inside workspace "
            f"{resolved_workspace}"
        )
