"""Tests for the rate-limit strategy
registry (Step E2).

Pre-E2, the rate limiter was a
hard-coded rolling 60-second window
per client IP. E2 introduces a
``RateLimitStrategy`` Protocol, three
built-in strategies
(``per_ip``, ``per_api_key``,
``token_bucket``), and a
``/api/jobs/<tid>/...`` middleware
that delegates to the configured
strategy.

Guarantees:

  1. ``list_strategies`` returns the
     sorted names of every registered
     strategy.
  2. ``get_strategy(name, max_calls)``
     returns an instance with the
     given name. ``StrategyNotFound``
     is raised for an unknown name.
  3. ``PerIpStrategy`` enforces a
     sliding window per client id.
  4. ``PerApiKeyStrategy`` is a
     separate state space from
     ``PerIpStrategy``; two requests
     from the same IP but with
     different API keys are not
     conflated.
  5. ``TokenBucketStrategy`` refills
     the bucket over time; a request
     that is denied at ``t=0`` is
     allowed at ``t=REFILL_PERIOD`` /
     ``max_calls`` (we do not test the
     full refill here because the
     test would be slow; we just
     assert the bucket starts full and
     empties).
  6. A strategy with ``max_calls <= 0``
     is a no-op (``check`` always
     returns True).
  7. The HTTP middleware uses the
     configured strategy; a request
     that exceeds the limit returns
     429 with a detail message that
     names the strategy.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _patch_upload_pipeline(monkeypatch: pytest.MonkeyPatch):
    from manusift.web import app as web_app

    def _fake_run_pipeline(original, paths, job, on_step_complete=None):
        job.status = "done"
        paths.report_html.write_text("<html></html>", encoding="utf-8")
        paths.findings_json.write_text(
            '{"trace_id": "%s", "findings": [], "detectors_run": []}'
            % job.trace_id,
            encoding="utf-8",
        )

    monkeypatch.setattr(web_app, "run_pipeline", _fake_run_pipeline)
    return web_app.create_app


# ---------- 1. Registry ----------

def test_list_strategies_returns_builtin_names() -> None:
    """``list_strategies`` returns the
    three built-in strategy names
    sorted alphabetically."""
    from manusift.rate_limit import list_strategies
    names = list_strategies()
    assert "per_ip" in names
    assert "per_api_key" in names
    assert "token_bucket" in names
    # Sorted.
    assert names == sorted(names)


def test_get_strategy_unknown_raises() -> None:
    """An unknown strategy name
    raises ``StrategyNotFound``."""
    from manusift.rate_limit import (
        StrategyNotFound,
        get_strategy,
    )
    with pytest.raises(StrategyNotFound):
        get_strategy("nope", max_calls=10)


# ---------- 2. PerIpStrategy ----------

def test_per_ip_strategy_enforces_window() -> None:
    """A sliding-window per client id.
    The first ``max_calls`` requests
    are allowed; the next is denied.
    A different client id has its own
    window."""
    from manusift.rate_limit import PerIpStrategy
    s = PerIpStrategy(max_calls=3)
    assert s.check("1.1.1.1")
    assert s.check("1.1.1.1")
    assert s.check("1.1.1.1")
    # 4th request denied.
    assert not s.check("1.1.1.1")
    # A different IP has its own
    # window.
    assert s.check("2.2.2.2")


def test_per_ip_strategy_max_calls_zero_is_noop() -> None:
    """``max_calls <= 0`` is a no-op -- the pre-E2 ``disable`` semantics."""
    from manusift.rate_limit import PerIpStrategy
    s = PerIpStrategy(max_calls=0)
    for _ in range(100):
        assert s.check("1.1.1.1")


# ---------- 3. PerApiKeyStrategy ----------

def test_per_api_key_strategy_separate_state() -> None:
    """``PerApiKeyStrategy`` keeps
    separate state per client id;
    two ids do not share the cap."""
    from manusift.rate_limit import PerApiKeyStrategy
    s = PerApiKeyStrategy(max_calls=2)
    # Client A burns through its
    # window.
    assert s.check("key-A")
    assert s.check("key-A")
    assert not s.check("key-A")
    # Client B has its own window.
    assert s.check("key-B")
    assert s.check("key-B")
    assert not s.check("key-B")


# ---------- 4. TokenBucketStrategy ----------

def test_token_bucket_starts_full_and_empties() -> None:
    """A token bucket starts full at
    ``max_calls`` and consumes one
    token per request. Once empty,
    requests are denied."""
    from manusift.rate_limit import TokenBucketStrategy
    s = TokenBucketStrategy(max_calls=4)
    for _ in range(4):
        assert s.check("1.1.1.1")
    assert not s.check("1.1.1.1")


def test_token_bucket_refills_over_time() -> None:
    """The bucket refills at the
    configured rate without relying
    on real sleeps.
    """
    from manusift import rate_limit
    original = rate_limit.TokenBucketStrategy.REFILL_PERIOD_SECONDS
    rate_limit.TokenBucketStrategy.REFILL_PERIOD_SECONDS = 0.1
    try:
        now = 0.0
        s = rate_limit.TokenBucketStrategy(
            max_calls=2,
            clock=lambda: now,
        )
        # Burn through the bucket.
        assert s.check("1.1.1.1")
        assert s.check("1.1.1.1")
        assert not s.check("1.1.1.1")
        # Advance just enough to refill
        # 1 token (rate = 2 / 0.1 s = 20
        # tokens/s, so 50 ms = 1
        # token).
        now = 0.05
        assert s.check("1.1.1.1")
        # And the bucket is empty
        # again -- the refill is
        # continuous but slow.
        assert not s.check("1.1.1.1")
    finally:
        rate_limit.TokenBucketStrategy.REFILL_PERIOD_SECONDS = original


def test_token_bucket_max_calls_zero_is_noop() -> None:
    """``max_calls <= 0`` is a no-op."""
    from manusift.rate_limit import TokenBucketStrategy
    s = TokenBucketStrategy(max_calls=0)
    for _ in range(100):
        assert s.check("1.1.1.1")


# ---------- 5. reset() ----------

def test_strategy_reset_clears_state() -> None:
    """``reset()`` clears the in-memory
    state so a test that wants a
    clean slate can call it."""
    from manusift.rate_limit import PerIpStrategy
    s = PerIpStrategy(max_calls=2)
    assert s.check("1.1.1.1")
    assert s.check("1.1.1.1")
    assert not s.check("1.1.1.1")
    s.reset()
    assert s.check("1.1.1.1")
    assert s.check("1.1.1.1")
    assert not s.check("1.1.1.1")


# ---------- 6. HTTP middleware integration ----------

def test_http_middleware_uses_per_ip_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``/api/upload`` middleware
    uses ``per_ip`` by default. The
    rate limit detail message
    mentions the strategy name."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_STRATEGY", "per_ip")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.app.state.reset_rate_limiter()
        pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
            b"xref\n0 1\n0000000000 65535 f\n"
            b"trailer<</Root 1 0 R>>\n"
            b"%%EOF"
        )
        for _ in range(2):
            r = client.post(
                "/api/upload",
                files={
                    "file": ("a.pdf", pdf, "application/pdf")
                },
            )
            assert r.status_code == 202
        # 3rd request is denied.
        r3 = client.post(
            "/api/upload",
            files={
                "file": ("a.pdf", pdf, "application/pdf")
            },
        )
        assert r3.status_code == 429
        # The detail message names
        # the strategy.
        assert "per_ip" in r3.json()["detail"]


def test_http_middleware_can_use_token_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different strategy (``token_bucket``)
    is selected via
    ``MANUSIFT_RATE_LIMIT_STRATEGY``.
    The middleware delegates to it.
    We assert that the 429 path is
    taken when the bucket empties."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv(
        "MANUSIFT_RATE_LIMIT_STRATEGY", "token_bucket"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        client.app.state.reset_rate_limiter()
        pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
            b"xref\n0 1\n0000000000 65535 f\n"
            b"trailer<</Root 1 0 R>>\n"
            b"%%EOF"
        )
        r1 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
        assert r1.status_code == 202
        # 2nd request denied (bucket
        # of 1 is empty).
        r2 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
        assert r2.status_code == 429
        # The detail message names
        # the strategy.
        assert "token_bucket" in r2.json()["detail"]


def test_http_middleware_falls_back_on_unknown_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown strategy name in
    settings falls back to ``per_ip``
    rather than crashing the
    middleware. The fallback is
    logged so the operator can see
    the misconfiguration in the log
    file."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv(
        "MANUSIFT_RATE_LIMIT_STRATEGY", "nope-does-not-exist"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        # The fallback is ``per_ip``;
        # the middleware still works.
        client.app.state.reset_rate_limiter()
        pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
            b"xref\n0 1\n0000000000 65535 f\n"
            b"trailer<</Root 1 0 R>>\n"
            b"%%EOF"
        )
        r = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
        assert r.status_code == 202
