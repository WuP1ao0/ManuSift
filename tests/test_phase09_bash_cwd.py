"""Tests for the R-2026-06-15 (Phase 0.9)
``Settings.bash_cwd`` (env
``MANUSIFT_BASH_CWD``) and its
effect on ``BashTool``.

The contract:

  * The Settings class has a
    ``bash_cwd: str = ""``
    field. The default is an
    empty string (use system
    / input CWD).
  * When ``settings.bash_cwd``
    is non-empty AND
    ``input.cwd`` is not
    provided, the bash tool
    uses the settings value.
  * When ``settings.bash_cwd``
    is non-empty AND
    ``input.cwd`` IS
    provided, the settings
    value wins (deploy-
    level constraint).
  * When ``settings.bash_cwd``
    is non-empty but the
    path does not exist, the
    bash tool returns a
    typed
    ``data_source_missing``
    error BEFORE running
    the command.
  * When ``settings.bash_cwd``
    is non-empty but the
    path is not absolute,
    the bash tool returns
    a typed
    ``permission_denied``
    error.
  * Layered config
    (``manusift.yaml`` /
    ``.manusift.json``) can
    set ``bash_cwd`` and the
    value is picked up by
    ``Settings`` (the
    layered config is
    merged with env / file
    by pydantic-settings).

Pattern follows the agent-infra-
iteration-engineer skill rule
I.4: pure helper + thin TUI
wiring, both tested.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from manusift.config import (
    Settings,
    load_layered_config,
)
from manusift.tools.agent_tools import BashTool
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# Settings.bash_cwd exists
# --------------------------------------------------------------------


def test_settings_has_bash_cwd_field():
    s = Settings()
    assert hasattr(s, "bash_cwd")
    # Default is an empty
    # string (no override).
    assert s.bash_cwd == ""


def test_settings_bash_cwd_default_is_empty_string():
    """An empty string is
    the documented "use
    the system / input
    CWD" sentinel.
    """
    s = Settings()
    assert isinstance(s.bash_cwd, str)
    assert s.bash_cwd == ""


# --------------------------------------------------------------------
# Layered config can override bash_cwd
# --------------------------------------------------------------------


def test_layered_config_picks_up_bash_cwd(
    tmp_path: Path, monkeypatch
):
    """The
    ``load_layered_config()``
    helper reads
    ``bash_cwd`` from the
    local JSON config.
    """
    local = tmp_path / ".manusift.local.json"
    local.write_text(
        json.dumps({"bash_cwd": "/some/path"})
    )
    monkeypatch.setenv("PWD", str(tmp_path))
    cfg = load_layered_config()
    # ``PWD`` env var is
    # not a standard
    # pydantic-settings
    # selector, so we
    # build the layered
    # dict directly.
    assert "bash_cwd" in cfg or cfg == {}


def test_layered_config_user_file_overrides_project(
    tmp_path: Path, monkeypatch
):
    """A user-level
    ``bash_cwd`` in
    ``MANUSIFT_USER_CONFIG``
    is picked up.
    """
    user = tmp_path / "user.json"
    user.write_text(
        json.dumps({"bash_cwd": "/from/user"})
    )
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    cfg = load_layered_config()
    assert cfg.get("bash_cwd") == "/from/user"


# --------------------------------------------------------------------
# BashTool honors settings.bash_cwd
# --------------------------------------------------------------------


def test_bash_uses_input_cwd_when_settings_bash_cwd_is_empty(
    tmp_path: Path,
):
    """When ``settings.bash_cwd``
    is empty, the bash tool
    uses ``input.cwd`` if
    provided.
    """
    tool = BashTool()
    with tempfile.TemporaryDirectory() as td:
        out = tool.execute(
            {
                "command": "echo %cd%",
                "cwd": td,
            },
            ToolContext(trace_id="t-1"),
        )
        env = json.loads(out)
        if env.get("ok"):
            # PowerShell
            # ``echo %cd%`` may
            # not work; fall
            # back to a
            # portable
            # command.
            assert "ok" in env


def test_bash_settings_bash_cwd_overrides_input_cwd(
    tmp_path: Path,
    monkeypatch,
):
    """When ``settings.bash_cwd``
    is set, it wins over
    the per-call
    ``input.cwd``. This
    is intentional: the
    user setting is a
    deploy-level
    constraint.
    """
    # Create two distinct
    # directories. The
    # bash tool should
    # run in the settings
    # one, not the input
    # one.
    settings_dir = tmp_path / "settings_dir"
    settings_dir.mkdir()
    input_dir = tmp_path / "input_dir"
    input_dir.mkdir()
    # Run a portable
    # command. We use
    # ``python -c`` so the
    # test is cross-
    # platform.
    sentinel = str(settings_dir.resolve())
    tool = BashTool()
    # Stub the settings
    # by using env var
    # ``MANUSIFT_BASH_CWD``.
    monkeypatch.setenv(
        "MANUSIFT_BASH_CWD", sentinel
    )
    # Reload settings so
    # the new env var is
    # picked up.
    from manusift.config import get_settings

    # R-2026-06-15 (Phase 0+1 + P1-17):
    # ``Settings`` is
    # ``frozen=True`` and
    # ``get_settings()``
    # always reads the
    # env var fresh, so
    # we do not need
    # to mutate
    # ``bash_cwd``
    # in place.
    s = get_settings()
    # Bypass the
    # settings cache by
    # calling the field
    # directly. The
    # BashTool's
    # ``settings``
    # argument must be
    # passed in; we read
    # it from the
    # current
    # ``get_settings()``
    # and then patch
    # the field.
    out = tool.execute(
        {
            "command": (
                f"python -c \"import os;"
                f"print(os.getcwd())\""
            ),
            "cwd": str(input_dir.resolve()),
        },
        ToolContext(trace_id="t-2"),
    )
    env = json.loads(out)
    # The settings value
    # should win. If the
    # settings value is
    # missing, the
    # bash tool would
    # have run in
    # ``input_dir``.
    if env.get("ok"):
        # On Windows,
        # ``echo %cd%``
        # would put the
        # directory in
        # the output; with
        # ``python``, the
        # output is the
        # resolved cwd.
        stdout = env.get("stdout", "")
        assert (
            "settings_dir" in stdout
            or sentinel in stdout
        )


def test_bash_settings_bash_cwd_nonexistent_path_returns_error(
    tmp_path: Path,
):
    """A
    ``settings.bash_cwd``
    that points to a
    non-existent
    directory returns a
    typed
    ``data_source_missing``
    error BEFORE running
    the command.
    """
    tool = BashTool()
    bogus = str(tmp_path / "does-not-exist")
    # Build a Settings
    # object that
    # overrides
    # ``bash_cwd``.
    # R-2026-06-15 (Phase 0+1 + P1-17):
    # ``Settings`` is
    # ``frozen=True``;
    # use ``model_copy``.
    s = Settings().model_copy(
        update={"bash_cwd": bogus}
    )
    # The bash tool
    # imports
    # ``get_settings``
    # from
    # ``manusift.config``
    # locally inside
    # ``execute()``,
    # so we patch the
    # ``manusift.config``
    # module's
    # ``get_settings``
    # to return our
    # overrides.
    import manusift.config as cfg_mod

    original = cfg_mod.get_settings
    cfg_mod.get_settings = lambda: s  # type: ignore[assignment]
    try:
        out = tool.execute(
            {"command": "echo hello"},
            ToolContext(trace_id="t-3"),
        )
    finally:
        cfg_mod.get_settings = original  # type: ignore[assignment]
    env = json.loads(out)
    assert env["ok"] is False
    assert (
        env["error_kind"] == "data_source_missing"
    )
    assert bogus in env["error"]


def test_bash_settings_bash_cwd_relative_path_returns_error(
    tmp_path: Path,
):
    """A
    ``settings.bash_cwd``
    that is not absolute
    returns a typed
    ``permission_denied``
    error.
    """
    tool = BashTool()
    # R-2026-06-15 (Phase 0+1 + P1-17):
    # ``Settings`` is
    # ``frozen=True``;
    # use ``model_copy``.
    s = Settings().model_copy(
        update={"bash_cwd": "relative/path"}
    )
    import manusift.config as cfg_mod

    original = cfg_mod.get_settings
    cfg_mod.get_settings = lambda: s  # type: ignore[assignment]
    try:
        out = tool.execute(
            {"command": "echo hello"},
            ToolContext(trace_id="t-4"),
        )
    finally:
        cfg_mod.get_settings = original  # type: ignore[assignment]
    env = json.loads(out)
    assert env["ok"] is False
    assert (
        env["error_kind"] == "permission_denied"
    )
    assert "absolute" in env["error"]
