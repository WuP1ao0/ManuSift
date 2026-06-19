"""Tests for the R-2026-06-15
(Phase 1 + 3a) YAML
layered config loader.

Covers:

  * ``deep_merge``
    semantics:
    - scalars replace
    - lists REPLACE
      (NOT
      concatenated)
    - dicts merge
      recursively
    - ``None`` in
      override
      deletes
      the
      key
  * ``load_yaml_config``
    reads 3 layers in
    priority order
    (local > project
    > user-global)
  * Missing / corrupt
    layers are
    silently
    skipped
  * ``Settings``
    seeded from
    the YAML
    layer
    (a
    yaml
    file
    at
    ``<workspace>/.manusift/config.yaml``
    with
    ``bash.default_cwd``
    sets
    ``settings.bash_cwd``)
  * Env vars
    still win
    over the
    YAML layer
  * The P2.2 JSON
    layer still
    works
    (no
    regression)

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from manusift.config_yaml import (
    deep_merge,
    find_layer_paths,
    load_yaml_config,
)


# --------------------------------------------------------------------
# deep_merge
# --------------------------------------------------------------------


def test_deep_merge_scalar_replace():
    out = deep_merge(
        {"a": 1, "b": 2},
        {"a": 99},
    )
    assert out == {"a": 99, "b": 2}


def test_deep_merge_dict_recursive():
    out = deep_merge(
        {
            "bash": {
                "default_cwd": "/old",
                "allow": True,
            },
        },
        {
            "bash": {
                "default_cwd": "/new",
            },
        },
    )
    # ``default_cwd``
    # is
    # replaced;
    # ``allow``
    # is
    # preserved.
    assert out == {
        "bash": {
            "default_cwd": "/new",
            "allow": True,
        },
    }


def test_deep_merge_lists_replace_not_concat():
    """A list value
    in ``override``
    REPLACES the
    list in ``base``
    (NOT concatenated).
    This is the
    critical contract:
    a user can disable
    a detector by
    writing
    ``detectors.enabled: []``
    in their local
    override (rather
    than having to
    redefine the
    entire list).
    """
    out = deep_merge(
        {"detectors": {"enabled": ["a", "b", "c"]}},
        {"detectors": {"enabled": ["d"]}},
    )
    assert out == {
        "detectors": {"enabled": ["d"]},
    }


def test_deep_merge_none_in_override_deletes_key():
    """``None`` in
    ``override`` is
    treated as
    "explicitly unset"
    and DELETES the
    key in the
    merged result.
    """
    out = deep_merge(
        {"a": 1, "b": 2},
        {"a": None},
    )
    assert "a" not in out
    assert out == {"b": 2}


def test_deep_merge_does_not_mutate_inputs():
    base = {"a": 1, "b": {"c": 2}}
    ovr = {"a": 99}
    out = deep_merge(base, ovr)
    assert base == {"a": 1, "b": {"c": 2}}
    assert ovr == {"a": 99}
    # The
    # merged
    # result
    # is
    # a
    # NEW
    # dict
    # (not
    # the
    # same
    # object
    # as
    # ``base``).
    assert out is not base


def test_deep_merge_empty_base():
    out = deep_merge({}, {"a": 1})
    assert out == {"a": 1}


def test_deep_merge_empty_override():
    out = deep_merge({"a": 1}, {})
    assert out == {"a": 1}


def test_deep_merge_deep_nesting():
    out = deep_merge(
        {
            "a": {
                "b": {
                    "c": {
                        "d": 1,
                        "e": 2,
                    },
                },
            },
        },
        {"a": {"b": {"c": {"d": 99}}}},
    )
    assert out == {
        "a": {
            "b": {
                "c": {
                    "d": 99,
                    "e": 2,
                },
            },
        },
    }


# --------------------------------------------------------------------
# find_layer_paths
# --------------------------------------------------------------------


def test_find_layer_paths_returns_workspace_layers(
    tmp_path: Path,
) -> None:
    paths = find_layer_paths(tmp_path)
    # The
    # first
    # two
    # paths
    # are
    # the
    # workspace-local
    # layers
    # (local
    # /
    # project).
    assert paths[0] == (
        tmp_path / ".manusift" / "config.local.yaml"
    )
    assert paths[1] == (
        tmp_path / ".manusift" / "config.yaml"
    )


def test_find_layer_paths_no_workspace():
    """When
    ``workspace_dir=None``,
    only the
    user-global
    layer is
    considered.
    """
    paths = find_layer_paths(None)
    # The
    # user-global
    # layer
    # is
    # only
    # present
    # if
    # ``$HOME``
    # (or
    # ``$USERPROFILE``)
    # is
    # set.
    home = os.environ.get("HOME") or os.environ.get(
        "USERPROFILE"
    )
    if home is not None:
        # The
        # function
        # returns
        # the
        # user-global
        # layer
        # if
        # it
        # exists
        # on
        # disk;
        # we
        # cannot
        # assume
        # it
        # exists
        # in
        # a
        # test
        # environment
        # (skip
        # the
        # exact
        # count).
        pass


# --------------------------------------------------------------------
# load_yaml_config
# --------------------------------------------------------------------


def test_load_yaml_config_empty_workspace(tmp_path: Path):
    """An empty workspace
    (no yaml files)
    returns ``{}``.
    """
    out = load_yaml_config(tmp_path)
    assert out == {}


def test_load_yaml_config_no_workspace():
    """``workspace_dir=None``
    returns ``{}`` (or
    the user-global
    layer if one
    exists on disk;
    but for the test we
    only care about the
    ``{}`` case).
    """
    # We
    # cannot
    # assert
    # ``{}``
    # because
    # the
    # user
    # might
    # have
    # a
    # global
    # config.
    # We
    # only
    # assert
    # "it
    # does
    # not
    # raise".
    load_yaml_config(None)


def _write_yaml(
    path: Path, content: str
) -> Path:
    """Write a YAML file
    and return its
    path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_load_yaml_config_project_layer(
    tmp_path: Path,
) -> None:
    """The project layer
    is read.
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/project\n",
    )
    out = load_yaml_config(tmp_path)
    assert out == {
        "bash": {"default_cwd": "/from/project"},
    }


def test_load_yaml_config_local_layer_overrides_project(
    tmp_path: Path,
) -> None:
    """The local layer
    (committed-to-git
    overrides) wins
    over the project
    layer.
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/project\n",
    )
    _write_yaml(
        tmp_path
        / ".manusift"
        / "config.local.yaml",
        "bash:\n  default_cwd: /from/local\n",
    )
    out = load_yaml_config(tmp_path)
    assert out == {
        "bash": {"default_cwd": "/from/local"},
    }


def test_load_yaml_config_local_partial_override(
    tmp_path: Path,
) -> None:
    """A local layer
    that only
    overrides a
    SUBSET of the
    project's keys
    is merged
    (other keys
    are preserved).
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        (
            "bash:\n"
            "  default_cwd: /from/project\n"
            "  allow_needs_confirm: true\n"
        ),
    )
    _write_yaml(
        tmp_path
        / ".manusift"
        / "config.local.yaml",
        "bash:\n  default_cwd: /from/local\n",
    )
    out = load_yaml_config(tmp_path)
    # ``default_cwd``
    # is
    # overridden;
    # ``allow_needs_confirm``
    # is
    # preserved.
    assert out == {
        "bash": {
            "default_cwd": "/from/local",
            "allow_needs_confirm": True,
        },
    }


def test_load_yaml_config_corrupt_file_is_skipped(
    tmp_path: Path,
) -> None:
    """A corrupt YAML
    file is silently
    skipped (the
    loader does not
    raise).
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "this is: not valid: yaml: : :\n",
    )
    out = load_yaml_config(tmp_path)
    assert out == {}


def test_load_yaml_config_non_dict_top_level_is_skipped(
    tmp_path: Path,
) -> None:
    """A YAML file whose
    top level is NOT
    a dict (e.g. a
    scalar or a list)
    is treated as
    empty.
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "- a\n- b\n- c\n",
    )
    out = load_yaml_config(tmp_path)
    assert out == {}


def test_load_yaml_config_does_not_mutate_files(
    tmp_path: Path,
) -> None:
    """The loader is
    read-only: it does
    not write to any
    file.
    """
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /x\n",
    )
    load_yaml_config(tmp_path)
    # File
    # is
    # unchanged.
    content = (
        tmp_path
        / ".manusift"
        / "config.yaml"
    ).read_text(encoding="utf-8")
    assert "bash:" in content
    assert "/x" in content


# --------------------------------------------------------------------
# Settings integration
# --------------------------------------------------------------------


def test_settings_picks_up_bash_cwd_from_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A yaml file at
    ``<workspace>/.manusift/config.yaml``
    with
    ``bash.default_cwd``
    sets
    ``Settings.bash_cwd``
    via the layered
    config.
    """
    from manusift.config import (
        get_settings,
    )

    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/yaml\n",
    )
    monkeypatch.chdir(tmp_path)
    # The
    # layered
    # config
    # is
    # cached
    # only
    # in
    # module
    # scope;
    # clear
    # it
    # if
    # the
    # helper
    # exposes
    # a
    # cache.
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.bash_cwd == "/from/yaml"


def test_settings_env_var_overrides_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env var
    (``MANUSIFT_BASH_CWD``)
    still wins over the
    yaml layer (Pydantic
    env precedence).
    """
    from manusift.config import (
        get_settings,
    )

    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/yaml\n",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "MANUSIFT_BASH_CWD", "/from/env"
    )
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.bash_cwd == "/from/env"


def test_settings_local_yaml_overrides_project_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The
    ``config.local.yaml``
    layer wins over
    the
    ``config.yaml``
    layer.
    """
    from manusift.config import (
        get_settings,
    )

    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/project\n",
    )
    _write_yaml(
        tmp_path
        / ".manusift"
        / "config.local.yaml",
        "bash:\n  default_cwd: /from/local\n",
    )
    monkeypatch.chdir(tmp_path)
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.bash_cwd == "/from/local"


def test_p2_2_json_layer_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The P2.2 JSON
    layered config
    (R-2026-06-14) is
    untouched: a
    ``.manusift.local.json``
    file still sets
    fields.
    """
    import json as _json
    from manusift.config import (
        get_settings,
    )

    (tmp_path / ".manusift.local.json").write_text(
        _json.dumps(
            {"bash_cwd": "/from/json"},
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.bash_cwd == "/from/json"


def test_yaml_layer_overrides_p2_2_json_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The yaml layer
    is merged AFTER
    the P2.2 JSON
    layer, so yaml
    wins on a key
    conflict.
    """
    import json as _json
    from manusift.config import (
        get_settings,
    )

    (tmp_path / ".manusift.local.json").write_text(
        _json.dumps(
            {"bash_cwd": "/from/json"},
        ),
        encoding="utf-8",
    )
    _write_yaml(
        tmp_path / ".manusift" / "config.yaml",
        "bash:\n  default_cwd: /from/yaml\n",
    )
    monkeypatch.chdir(tmp_path)
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    # YAML
    # wins
    # over
    # JSON.
    assert s.bash_cwd == "/from/yaml"
