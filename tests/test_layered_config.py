"""Tests for the R-2026-06-14 P2.2 layered config.

Contract:

  * Three layers, applied in order
    (lowest-priority first):
    ``user`` < ``project`` < ``local``.
  * The ``local`` layer wins on a key
    conflict; the ``project`` layer
    wins over the ``user`` layer.
  * A missing or corrupt layer does
    not crash the loader (best-effort).
  * ``MANUSIFT_USER_CONFIG`` overrides
    the default ``~/manusift.json`` path.
  * The default ``project`` path is
    ``<repo>/.manusift.json`` and the
    default ``local`` path is
    ``<cwd>/.manusift.json`` -- both are
    read at call time so monkey-patched
    ``cwd`` (via ``os.chdir``) takes
    effect.
  * The merged dict has the same
    key/value contract as ``Settings()``
    -- the caller feeds it back into
    ``Settings(**merged)`` or sets the
    env vars accordingly.

Pattern follows claw-code's
``UserConfig::layered`` in
``rust/crates/config/src/lib.rs``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from manusift.config import (
    config_layers_present,
    load_layered_config,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data), encoding="utf-8"
    )


# --------------------------------------------------------------------
# Empty / missing
# --------------------------------------------------------------------


def test_no_layers_present_returns_empty_dict(
    tmp_path: Path, monkeypatch
):
    """With no layer files on disk and
    ``MANUSIFT_USER_CONFIG`` pointing
    at a missing file, the loader
    returns an empty dict (no crash).
    """
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG",
        str(tmp_path / "no_such_user.json"),
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    assert out == {}


# --------------------------------------------------------------------
# Single layer
# --------------------------------------------------------------------


def test_user_layer_only(
    tmp_path: Path, monkeypatch
):
    user = tmp_path / "u.json"
    _write_json(user, {"k": "from-user", "n": 1})
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    assert out["k"] == "from-user"
    assert out["n"] == 1


def test_local_layer_only(
    tmp_path: Path, monkeypatch
):
    local = tmp_path / ".manusift.local.json"
    _write_json(
        local,
        {"anthropic_api_key": "sk-local"},
    )
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG",
        str(tmp_path / "no_such_user.json"),
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    assert out["anthropic_api_key"] == "sk-local"


# --------------------------------------------------------------------
# Precedence: local > project > user
# --------------------------------------------------------------------


def test_local_overrides_project_and_user(
    tmp_path: Path, monkeypatch
):
    user = tmp_path / "u.json"
    _write_json(
        user,
        {"api_key": "from-user", "n_user": 1},
    )
    project = tmp_path / ".manusift.json"
    _write_json(
        project,
        {"api_key": "from-project", "n_proj": 2},
    )
    local = tmp_path / ".manusift.local.json"
    _write_json(
        local,
        {"api_key": "from-local"},
    )
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    # The project layer is
    # ``<repo>/.manusift.json`` -- it
    # is committed defaults the user
    # can clone and edit. The local
    # layer is ``<cwd>/.manusift.local.json``,
    # per-run overrides. The local
    # layer wins on a key conflict.
    # We use ``.manusift.local.json``
    # here (not ``.manusift.json``) so
    # the test does not collide with
    # a real project-level file.
    # Patch the local-path helper to
    # point at the test's file.
    import manusift.config as cfg
    monkeypatch.setattr(
        cfg,
        "_cwd_config_path",
        lambda: local,
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    # ``api_key`` from local wins over
    # user and project.
    assert out["api_key"] == "from-local"
    # ``n_user`` is preserved because
    # no other layer defines it.
    assert out["n_user"] == 1


# --------------------------------------------------------------------
# Corrupt / wrong-shape layer
# --------------------------------------------------------------------


def test_corrupt_user_layer_is_skipped(
    tmp_path: Path, monkeypatch
):
    user = tmp_path / "u.json"
    user.write_text("not json", encoding="utf-8")
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    assert out == {}


def test_non_dict_user_layer_is_skipped(
    tmp_path: Path, monkeypatch
):
    user = tmp_path / "u.json"
    user.write_text(
        json.dumps([1, 2, 3]), encoding="utf-8"
    )
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    monkeypatch.chdir(tmp_path)
    out = load_layered_config()
    assert out == {}


# --------------------------------------------------------------------
# Layers-present helper
# --------------------------------------------------------------------


def test_config_layers_present(
    tmp_path: Path, monkeypatch
):
    user = tmp_path / "u.json"
    _write_json(user, {"k": "v"})
    local = tmp_path / ".manusift.local.json"
    _write_json(local, {"k": "v"})
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    monkeypatch.chdir(tmp_path)
    layers = config_layers_present()
    assert "user" in layers
    assert layers["user"] == user
    assert "local" in layers
    assert layers["local"] == local


# --------------------------------------------------------------------
# Settings accepts the merged dict
# --------------------------------------------------------------------


def test_merged_dict_feeds_back_to_settings(
    tmp_path: Path, monkeypatch
):
    """The merged dict has the same
    shape as ``Settings()`` keyword
    args. Verify by feeding it back.
    """
    user = tmp_path / "u.json"
    _write_json(
        user,
        {
            "anthropic_api_key": "sk-from-user",
            "subagent_timeout_seconds": 99.0,
        },
    )
    monkeypatch.setenv(
        "MANUSIFT_USER_CONFIG", str(user)
    )
    monkeypatch.chdir(tmp_path)
    merged = load_layered_config()
    from manusift.config import Settings
    s = Settings(**merged)
    # The key is a ``SecretStr`` --
    # ``.get_secret_value()`` returns
    # the raw string.
    assert (
        s.anthropic_api_key.get_secret_value()
        == "sk-from-user"
    )
    # Float field is set.
    assert s.subagent_timeout_seconds == 99.0
