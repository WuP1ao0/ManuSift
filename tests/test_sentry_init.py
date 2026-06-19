"""Tests for the Sentry integration (P0-10).

Three guarantees:

  1. With no DSN (the default), ``_init_sentry``
     is a no-op. It does not attempt to import
     sentry_sdk, and it does not raise.

  2. With a DSN but sentry-sdk not installed
     (the local dev case), ``_init_sentry``
     logs a warning and does not raise. The app
     keeps starting.

  3. With a DSN and sentry-sdk installed (the
     production case), ``sentry_sdk.init`` is
     called with our settings. We verify by
     monkeypatching sentry_sdk and inspecting the
     call.

The integration is opt-in: it is silently a
no-op unless ``MANUSIFT_SENTRY_DSN`` is set in
the environment or passed via ``Settings(sentry_dsn=...)``.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.web.app import _init_sentry, create_app


# ---------- 1. No DSN is a no-op ----------

def test_init_sentry_no_dsn_is_noop(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The default Settings have ``sentry_dsn=''``,
    so ``_init_sentry`` must return immediately,
    import nothing, and not raise. The caplog
    assertion is the safety net: if sentry was
    somehow touched, it would log."""
    s = Settings(workspace_dir=tmp_path, sentry_dsn="")
    with caplog.at_level(logging.WARNING):
        _init_sentry(s)
    # Nothing logged at WARN by _init_sentry.
    warns = [r for r in caplog.records if r.name == "manusift.web.app"]
    assert warns == []


def test_create_app_with_no_sentry_dsn_starts(
    tmp_path: Path,
) -> None:
    """An app created with the default (empty) Sentry
    DSN starts cleanly. This is the dev / CI
    default -- we must not regress it."""
    s = Settings(workspace_dir=tmp_path)
    client = TestClient(
        create_app(settings=s),
        raise_server_exceptions=False,
    )
    r = client.get("/api/healthz")
    assert r.status_code == 200


# ---------- 2. DSN set but sentry-sdk missing ----------

def test_init_sentry_dsn_set_sdk_missing_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the operator sets MANUSIFT_SENTRY_DSN but
    did not ``pip install sentry-sdk``, we log a
    warning explaining the missing dep instead of
    crashing. The app must still start."""
    s = Settings(workspace_dir=tmp_path, sentry_dsn="https://fake@sentry/123")
    # Make sure the import fails inside _init_sentry
    # by hiding sentry_sdk + its integrations.
    import builtins
    real_import = builtins.__import__

    def guarded_import(name, *a, **kw):  # type: ignore[no-untyped-def]
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ImportError("simulated missing sentry_sdk")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with caplog.at_level(logging.WARNING):
        # Must not raise.
        _init_sentry(s)
    # The warning must mention the install command
    # so the operator knows what to do.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("sentry-sdk" in m and "pip install" in m for m in msgs)


# ---------- 3. DSN set and sentry-sdk present ----------

def test_init_sentry_dsn_set_sdk_present_calls_init(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both DSN and sentry-sdk are present,
    ``sentry_sdk.init`` is called with our DSN,
    integrations, and the no-PII flag."""
    import types
    fake_module = types.ModuleType("sentry_sdk")

    captured: dict[str, Any] = {}
    def fake_init(*, dsn, integrations, send_default_pii, traces_sample_rate):
        captured["dsn"] = dsn
        captured["integrations"] = integrations
        captured["send_default_pii"] = send_default_pii
        captured["traces_sample_rate"] = traces_sample_rate
    fake_module.init = fake_init

    class _NoOp:
        def __init__(self, *a, **kw):
            pass

    fastapi_integration_module = types.ModuleType("sentry_sdk.integrations.fastapi")
    fastapi_integration_module.FastApiIntegration = _NoOp
    starlette_integration_module = types.ModuleType("sentry_sdk.integrations.starlette")
    starlette_integration_module.StarletteIntegration = _NoOp

    import sys
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_module)
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.fastapi",
        fastapi_integration_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "sentry_sdk.integrations.starlette",
        starlette_integration_module,
    )

    s = Settings(workspace_dir=tmp_path, sentry_dsn="https://real@sentry/9")
    _init_sentry(s)

    assert captured["dsn"] == "https://real@sentry/9"
    assert captured["send_default_pii"] is False
    assert captured["traces_sample_rate"] == 0.1
    # Two integrations: FastAPI + Starlette.
    assert len(captured["integrations"]) == 2




def test_settings_has_sentry_dsn_field() -> None:
    """The field exists with the documented default."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert hasattr(s, "sentry_dsn")
    assert s.sentry_dsn == ""
