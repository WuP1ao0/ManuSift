"""R-2026-06-19 (P1-B2):
enforce the
``block_protected_dir_reads``
setting in
``ReadFileTool``.

The ``is_protected_dir``
guard was added
in Phase A but
only surfaced a
``protected_dir``
hint; the
actual read
was not
blocked.
P1-B2 wires the
new
``block_protected_dir_reads=True``
default into
``ReadFileTool.execute``
so a path inside
``.git`` /
``.vscode`` /
``.manusift`` /
etc. returns
``error_kind: "permission_denied"``
instead of the
file content.
The user can
opt out via
``MANUSIFT_BLOCK_PROTECTED_DIR_READS=0``
in the env.

Borrowed from
Claude Code's
"always-deny
for config
dirs" policy
(``checkPermissions``):
even ``bypassPermissions``
mode respects
the protected
dirs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.config import get_settings  # noqa: E402
from manusift.tools.tool import ToolContext  # noqa: E402
from manusift.tools.direct_fs import ReadFileTool  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def protected_dir_setup(tmp_path, monkeypatch):
    """Create a ``.git`` subdir with a known file inside."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    target = git_dir / "config"
    target.write_text(
        "[core]\n"
        "  repositoryformatversion = 0\n"
    )
    # Also create a non-protected sibling file.
    safe = tmp_path / "notes.txt"
    safe.write_text("hello world")
    return tmp_path, target, safe


def _ctx(workspace):
    return ToolContext(
        trace_id="trace_b2",
        current_pdf="",
        metadata={"workspace_dir": str(workspace)},
    )


# ---------------------------------------------------------------------------
# Default behavior (block ON)
# ---------------------------------------------------------------------------


class TestProtectedDirBlockedByDefault:
    def test_git_config_read_returns_permission_denied(
        self, protected_dir_setup
    ):
        workspace, target, _ = protected_dir_setup
        tool = ReadFileTool()
        out = json.loads(
            tool.execute({"path": str(target)}, _ctx(workspace))
        )
        assert out["ok"] is False
        assert out["error_kind"] == "permission_denied"
        assert out["protected_dir"] == ".git"
        # The actual file content must NOT be in the response.
        assert "repositoryformatversion" not in out.get("error", "")

    def test_non_protected_file_still_reads(self, protected_dir_setup):
        workspace, _, safe = protected_dir_setup
        tool = ReadFileTool()
        out = json.loads(
            tool.execute({"path": str(safe)}, _ctx(workspace))
        )
        assert out["ok"] is True
        assert "hello world" in out["content"]

    def test_nested_protected_dir_also_blocked(self, tmp_path):
        # ``project/.vscode/settings.json`` -- nested.
        proj = tmp_path / "project"
        proj.mkdir()
        vscode = proj / ".vscode"
        vscode.mkdir()
        f = vscode / "settings.json"
        f.write_text('{"editor.tabSize": 2}')
        tool = ReadFileTool()
        out = json.loads(
            tool.execute({"path": str(f)}, _ctx(tmp_path))
        )
        assert out["ok"] is False
        assert out["protected_dir"] == ".vscode"
        assert "editor.tabSize" not in out.get("error", "")


# ---------------------------------------------------------------------------
# Opt-out: MANUSIFT_BLOCK_PROTECTED_DIR_READS=0
# ---------------------------------------------------------------------------


class TestProtectedDirOptOut:
    def test_opt_out_via_env_var(
        self, protected_dir_setup, monkeypatch
    ):
        workspace, target, _ = protected_dir_setup
        # Opt out: the user *really* wants to read .git/config.
        monkeypatch.setenv("MANUSIFT_BLOCK_PROTECTED_DIR_READS", "0")
        # Clear any cached settings from prior tests.
        from manusift import config as cfg_mod
        cfg_mod._settings_cache = None  # type: ignore[attr-defined]
        try:
            tool = ReadFileTool()
            out = json.loads(
                tool.execute({"path": str(target)}, _ctx(workspace))
            )
            # Now the read succeeds; the response
            # carries the ``protected_dir: ".git"``
            # hint but no error.
            assert out["ok"] is True
            assert "repositoryformatversion" in out["content"]
            assert out.get("protected_dir") == ".git"
        finally:
            cfg_mod._settings_cache = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Settings schema
# ---------------------------------------------------------------------------


class TestSettingsSchema:
    def test_default_is_true(self):
        # Fresh settings.
        from manusift import config as cfg_mod
        cfg_mod._settings_cache = None  # type: ignore[attr-defined]
        s = get_settings()
        assert s.block_protected_dir_reads is True
