"""Tests for the R-2026-06-14 P1.5 tool-argument
redactor.

The contract:

  * ``redact_input`` and ``redact_output``
    return deep copies, never mutate the
    caller's dict.
  * Recognized secret shapes (API keys,
    bearer tokens, --password values, home
    paths, label=secret pairs) are replaced
    with a typed placeholder.
  * Dict keys in the always-redact set
    (``api_key``, ``token``, ``password``,
    etc.) are always replaced regardless
    of value shape.
  * The redactor is conservative: a
    non-secret value is preserved
    unchanged.
  * ``None`` input passes through.
"""
from __future__ import annotations

import copy

import pytest

from manusift.tools.redactor import (
    redact_input,
    redact_output,
)


# --------------------------------------------------------------------
# Identity / non-mutation
# --------------------------------------------------------------------


def test_redact_input_returns_deep_copy():
    """The redactor returns a deep copy.
    The caller's dict is not mutated.
    """
    raw = {"command": "echo hi", "x": 1}
    out = redact_input(raw)
    assert out is not raw
    # Mutate the redacted output and verify
    # the original is untouched.
    out["command"] = "mutated"
    assert raw["command"] == "echo hi"


def test_redact_input_none_returns_none():
    assert redact_input(None) is None


def test_redact_output_none_returns_none():
    assert redact_output(None) is None


# --------------------------------------------------------------------
# API key shapes
# --------------------------------------------------------------------


def test_redact_openai_api_key():
    raw = "the key is sk-abcdefghijklmnop1234"
    out = redact_output(raw)
    assert "sk-abcdefghijklmnop1234" not in out
    assert "redacted" in out


def test_redact_anthropic_api_key():
    raw = "key=sk-ant-abcdefghijklmnop1234-xyz"
    out = redact_output(raw)
    assert "sk-ant-abcdefghijklmnop1234-xyz" not in out
    assert "redacted" in out


def test_redact_github_token():
    raw = "GH_TOKEN=ghp_abcdefghijklmnop1234"
    out = redact_output(raw)
    assert "ghp_abcdefghijklmnop1234" not in out
    assert "redacted" in out


def test_redact_bearer_token():
    raw = "Authorization: Bearer abcdefghij1234567890"
    out = redact_output(raw)
    assert "abcdefghij1234567890" not in out
    assert "redacted" in out


# --------------------------------------------------------------------
# Password flags
# --------------------------------------------------------------------


def test_redact_p_flag():
    raw = "mysql -u root -p hunter2"
    out = redact_output(raw)
    assert "hunter2" not in out
    assert "redacted" in out


def test_redact_long_password_flag():
    raw = "curl --api-key mysupersecretkey1234"
    out = redact_output(raw)
    assert "mysupersecretkey1234" not in out


# --------------------------------------------------------------------
# KV secrets
# --------------------------------------------------------------------


def test_redact_labeled_kv_secret():
    raw = 'api_key="sk-1234567890abcdef"'
    out = redact_output(raw)
    assert "sk-1234567890abcdef" not in out


def test_redact_dict_with_secret_key_always_redacts():
    """A dict with a key named ``api_key``
    is always redacted, even if the value
    is short / non-secret-shaped.
    """
    raw = {"api_key": "anything-here", "tool": "bash"}
    out = redact_input(raw)
    assert out["api_key"] == "<redacted:secret_key>"
    assert out["tool"] == "bash"


def test_redact_dict_with_password_key():
    raw = {"password": "hunter2"}
    out = redact_input(raw)
    assert out["password"] == "<redacted:secret_key>"


# --------------------------------------------------------------------
# User home
# --------------------------------------------------------------------


def test_redact_user_home_path():
    raw = "config from C:/Users/alice/.manusift/config.toml"
    out = redact_output(raw)
    assert "alice" not in out
    assert "redacted" in out


def test_redact_user_home_posix():
    raw = "read /home/alice/.bashrc"
    out = redact_output(raw)
    assert "alice" not in out


# --------------------------------------------------------------------
# Non-secret values are preserved
# --------------------------------------------------------------------


def test_non_secret_value_passes_through():
    raw = "echo hello world"
    out = redact_output(raw)
    assert out == raw


def test_non_secret_dict_passes_through():
    raw = {"command": "ls", "cwd": "/tmp", "n": 5}
    out = redact_input(raw)
    assert out == raw


def test_non_secret_numeric_value_preserved():
    raw = {"count": 42, "ratio": 0.5, "ok": True}
    out = redact_input(raw)
    assert out == raw


# --------------------------------------------------------------------
# Recursion into nested structures
# --------------------------------------------------------------------


def test_redact_nested_dict():
    raw = {
        "config": {
            "auth": {
                "api_key": "sk-abcdefghijklmnop1234",
            },
        },
    }
    out = redact_input(raw)
    assert "sk-abcdefghijklmnop1234" not in str(out)
    # The non-secret keys are preserved.
    assert out["config"]["auth"]["api_key"] == (
        "<redacted:secret_key>"
    )


def test_redact_nested_list():
    raw = {
        "secrets": [
            "sk-abcdefghijklmnop1234",
            "ghp_zzzzzzzzzzzzzzzzzzzz",
        ],
        "tools": ["bash", "grep"],
    }
    out = redact_input(raw)
    # Both list items are redacted.
    assert "sk-abcdefghijklmnop1234" not in out["secrets"][0]
    assert "ghp_zzzzzzzzzzzzzzzzzzzz" not in (
        out["secrets"][1]
    )
    # The non-secret list passes through.
    assert out["tools"] == ["bash", "grep"]


# --------------------------------------------------------------------
# Output string form
# --------------------------------------------------------------------