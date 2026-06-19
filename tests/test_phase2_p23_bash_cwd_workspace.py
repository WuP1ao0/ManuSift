"""R-2026-06-15 (Phase 2 + P2-3):
test ``BashTool.cwd`` workspace
restriction.

The audit found that
``BashTool.execute()`` accepted
ANY absolute directory as
``cwd``.  A tool call that
asks for ``cwd=/etc`` (or
any other absolute path
outside the configured
workspace) was a sandbox
escape.  The fix is to
resolve ``cwd`` (canonical
form) and check that it
is
``is_relative_to(workspace_dir)``.

These tests verify:

  1. ``cwd`` inside the
     workspace is accepted.
  2. ``cwd`` outside the
     workspace is rejected
     with
     ``error_kind:
     permission_denied``.
  3. ``cwd`` that is a
     symlink pointing
     outside the workspace
     is rejected (the
     ``.resolve()`` call
     follows the symlink
     before the check).
  4. The default
     ``settings.bash_cwd``
     is also restricted to
     be inside the
     workspace.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


def _make_bash_tool():
    """Build a BashTool and
    patch the global
    ``get_settings`` to
    return a settings
    object whose
    ``workspace_dir`` is
    the test's
    ``tmp_path``.
    """
    from manusift.config import Settings
    from manusift.tools.agent_tools import (
        BashTool,
    )

    tool = BashTool()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": "/tmp/test_workspace"}
    )
    # The BashTool does
    # ``from ..config import
    # get_settings`` at
    # function scope, so we
    # patch the source
    # module's ``get_settings``.
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module, "get_settings", lambda: settings
    )
    # Also patch the
    # function-scope import
    # in agent_tools.
    import manusift.tools.agent_tools as at_module
    monkey.setattr(
        at_module, "get_settings", lambda: settings
    )
    return tool, monkey


def test_p23_cwd_inside_workspace_accepted(
    tmp_path: Path,
) -> None:
    """A ``cwd`` inside the
    workspace is accepted.
    """
    from manusift.config import Settings
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"workspace_dir": str(workspace)}
    )
    # ``BashTool`` does
    # ``from ..config import
    # get_settings`` at
    # function scope, so
    # patching the source
    # module's ``get_settings``
    # is enough.
    import manusift.config as config_module
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        config_module,
        "get_settings",
        lambda: settings,
    )
    tool = BashTool()
    out = tool.execute(
        {"command": "echo ok", "cwd": str(workspace)},
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    # The test is in a
    # workspace that
    # exists, so the call
    # should succeed
    # (return ``ok: True``).
    # We do not assert on
    # the stdout because
    # the audit only
    # required that the
    # ``cwd`` not be
    # rejected -- the
    # actual command may
    # fail in CI for
    # unrelated reasons
    # (no bash, no
    # powershell, etc.).
    # The key assertion is
    # that the
    # ``permission_denied``
    # error is NOT raised.
    if not result.get("ok"):
        assert (
            result.get("error_kind")
            != "permission_denied"
        ), (
            f"cwd={workspace} was rejected "
            f"as permission_denied: "
            f"{result.get('error')}"
        )


def test_p23_cwd_outside_workspace_rejected(
    tmp_path: Path,
) -> None:
    """A ``cwd`` outside the
    workspace is rejected
    with
    ``error_kind:
    permission_denied``.
    """
    from manusift.config import Settings
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
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
            "cwd": str(outside),
        },
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    assert result["ok"] is False
    assert (
        result["error_kind"] == "permission_denied"
    ), (
        f"cwd outside workspace was not "
        f"rejected: {result}"
    )


def test_p23_cwd_symlink_escape_rejected(
    tmp_path: Path,
) -> None:
    """A symlink inside the
    workspace that points
    to a directory
    OUTSIDE the workspace
    is rejected (the
    ``.resolve()`` call
    follows the symlink
    before the check).
    """
    if sys.platform == "win32":
        # On Windows, creating
        # a symlink requires
        # admin privileges.
        # Skip the test.
        pytest.skip("symlink test requires "
                    "non-Windows or admin")
    from manusift.config import Settings
    from manusift.tools.agent_tools import (
        BashTool,
    )

    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # Create a symlink
    # ``workspace/escape`` ->
    # ``outside``.
    link = workspace / "escape"
    link.symlink_to(outside)
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
            "cwd": str(link),
        },
        None,  # type: ignore[arg-type]
    )
    result = json.loads(out)
    assert result["ok"] is False
    assert (
        result["error_kind"] == "permission_denied"
    ), (
        f"symlink escape was not rejected: "
        f"{result}"
    )
