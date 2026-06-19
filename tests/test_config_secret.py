"""Tests for Settings + SecretStr handling (L1).

Two guarantees:

  1. ``Settings.openai_api_key`` is a ``SecretStr`` when
     loaded from env, so it auto-masks in ``repr`` /
     ``str()`` / log output.
  2. ``Settings.has_openai`` returns the right boolean
     without unwrapping the SecretStr.
  3. ``Settings`` still tolerates the legacy ``str`` value
     (so existing tests that assign a raw string do not
     break).
  4. ``_unwrap_key()`` (in ``manusift.llm.client``) handles
     all three cases: None, SecretStr, str.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from manusift.config import Settings
from manusift.llm.client import _unwrap_key


# ---------- 1. default Settings loads with no keys ----------

def test_settings_default_keys_are_none() -> None:
    """A fresh Settings() with no env override has
    both API keys as None (not empty strings)."""
    # R-audit (2026-06-10):
    # ``test_bash_can_be_disabled_via_settings``
    # in ``test_agent_tools.py`` flips
    # ``MANUSIFT_ALLOW_SHELL`` and calls
    # ``get_settings.cache_clear()``. The env var
    # is popped in the test's ``finally`` block,
    # but other env vars
    # (``MANUSIFT_TAVILY_API_KEY``,
    # ``MANUSIFT_BRAVE_API_KEY``) might
    # have leaked from a previous run. We clear
    # all ``MANUSIFT_*`` env vars to make this
    # test order-independent.
    import os as _os
    for k in list(_os.environ):
        if k.startswith("MANUSIFT_"):
            _os.environ.pop(k, None)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.openai_api_key is None
    assert s.anthropic_api_key is None
    assert s.tavily_api_key is None
    assert s.brave_api_key is None
    assert s.has_openai is False
    assert s.has_anthropic is False
    assert s.has_any_llm is False


# ---------- 2. env var promotion to SecretStr ----------

def test_env_string_promotes_to_secret_str(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """When the env var is a plain string, pydantic-settings
    wraps it in SecretStr. This is the whole point of L1."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-test-123")
    monkeypatch.setenv("MANUSIFT_ANTHROPIC_API_KEY", "sk-ant-test-456")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    # Type: SecretStr (not str).
    assert isinstance(s.openai_api_key, SecretStr)
    assert isinstance(s.anthropic_api_key, SecretStr)
    # repr auto-masks.
    r = repr(s.openai_api_key)
    assert "sk-test-123" not in r
    # The unwrap still returns the original string.
    assert s.openai_api_key.get_secret_value() == "sk-test-123"
    # has_* stays correct.
    assert s.has_openai is True
    assert s.has_anthropic is True


# ---------- 3. legacy str assignment still works ----------

def test_legacy_str_assignment_tolerated() -> None:
    """Old test code did
    ``s.openai_api_key = "sk-x"``
    (direct attribute
    assignment, plain str).

    R-2026-06-15 (Phase 1 + P1-17):
    ``Settings`` is now
    ``frozen=True``, so
    direct assignment after
    construction raises
    ``ValidationError``.  The
    fix is to use
    ``model_copy`` to build a
    new instance with the
    override.  This is the
    same pattern recommended
    in the ``Settings`` class
    docstring.

    The unwrap helper still
    handles plain str, so
    legacy code that *reads*
    the value continues to
    work.  The change is only
    in the *write* path: you
    can no longer silently
    mutate the shared
    Settings object; you
    must build a new one.
    """
    with pytest.raises(Exception) as excinfo:
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        s.openai_api_key = "sk-legacy"  # type: ignore[assignment]
    # Direct assignment
    # raises (frozen).
    err_cls = type(excinfo.value).__name__
    assert err_cls in (
        "ValidationError",
        "FrozenInstanceError",
    ), f"unexpected error class: {err_cls}"
    # The correct pattern is
    # ``model_copy``.
    s2 = Settings(_env_file=None).model_copy(  # type: ignore[call-arg]
        update={"openai_api_key": "sk-legacy"}
    )
    assert s2.openai_api_key == "sk-legacy"
    assert s2.has_openai is True
    assert _unwrap_key(s2.openai_api_key) == "sk-legacy"


# ---------- 4. _unwrap_key handles all 3 cases ----------

def test_unwrap_key_none() -> None:
    """None in -> None out. Crucial because LLM clients
    call ``_unwrap_key`` before checking ``is_available``;
    a None here must propagate, not become ''."""
    assert _unwrap_key(None) is None


def test_unwrap_key_secret_str() -> None:
    """SecretStr in -> plain str out."""
    s = SecretStr("sk-secret-value")
    assert _unwrap_key(s) == "sk-secret-value"


def test_unwrap_key_legacy_str() -> None:
    """str in -> str out (idempotent)."""
    assert _unwrap_key("sk-legacy") == "sk-legacy"


# ---------- 5. env value never leaks into repr ----------

def test_settings_repr_does_not_leak_key(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """The whole point: a leaked API key in a log line
    is a security incident. After L1, ``repr(settings)``
    must not contain the secret value."""
    monkeypatch.setenv("MANUSIFT_OPENAI_API_KEY", "sk-supersecret-XYZ")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    r = repr(s)
    # The actual secret must not appear.
    assert "sk-supersecret-XYZ" not in r
    # str() too.
    assert "sk-supersecret-XYZ" not in str(s)
    # model_dump() (the way settings get persisted to
    # job.json in some code paths) must also mask.
    dumped = s.model_dump()
    # SecretStr is dumped as a SecretStr object; we
    # check the value-side.
    if dumped["openai_api_key"] is not None:
        assert "sk-supersecret-XYZ" not in str(dumped["openai_api_key"])
