"""Tests for CORS + rate limit middleware (L3).

Two guarantees:

  1. CORS preflight (OPTIONS) from an allowed origin
     returns 200 with the right ``Access-Control-*``
     headers. A request from a non-allowed origin is
     still answered (CORS is a browser-side policy,
     not a server-side block) but without the
     ``Allow-Origin`` header.

  2. The rate limiter caps POSTs per IP per 60s. A
     burst of 11 requests returns 11th as 429. GETs
     are never limited.

The rate limiter reads ``Settings.rate_limit_per_minute``
on every request, so tests can lower the limit to
verify the 429 path without depending on the
production default.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz  # type: ignore[import-not-found]
import pytest
from starlette.testclient import TestClient

from manusift.config import Settings, get_settings
from manusift.web.app import create_app

# ---------- helpers ----------

def _client_with(
    *,
    workspace: Path,
    rate_limit: int = 0,
    cors_origins: str = "http://127.0.0.1:8765",
) -> TestClient:
    """A TestClient with explicit Settings passed to
    ``create_app``. The rate_limit default of 0 means
    the limiter is disabled unless a specific test
    re-enables it. CORS is set to a single loopback
    origin by default.

    L3 fix: we no longer rely on ``get_settings()``
    inside create_app -- that was the source of the
    test-interleaving env-leak bug. By constructing a
    fresh ``Settings(...)`` here we get the values
    the test wants, no matter what previous tests
    left in the environment. We also reset the
    in-process rate-limit counters so the previous
    test's POSTs do not bleed into this one."""
    settings = Settings(
        workspace_dir=workspace,
        rate_limit_per_minute=rate_limit,
        cors_allow_origins=cors_origins,
    )
    # raise_server_exceptions=False so 429s come back
    # as response objects rather than being re-raised.
    client = TestClient(
        create_app(settings=settings),
        raise_server_exceptions=False,
    )
    # Clear the rate-limit deque so this test starts
    # with a fresh window.
    if hasattr(client.app, "state") and hasattr(
        client.app.state, "reset_rate_limiter"
    ):
        client.app.state.reset_rate_limiter()
    return client

def _pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page(width=200, height=100)
    doc[0].insert_text((20, 20), "hi")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()

# ---------- 1. CORS preflight ----------

def test_cors_preflight_allowed_origin_returns_200(
    tmp_path: Path
) -> None:
    """An OPTIONS preflight from a configured origin
    gets 200 plus the right CORS headers."""
    client = _client_with(
        workspace=tmp_path, cors_origins="http://app.example.com"
    )
    resp = client.options(
        "/api/upload",
        headers={
            "Origin": "http://app.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://app.example.com"

def test_cors_preflight_unknown_origin_has_no_allow_header(
    tmp_path: Path
) -> None:
    """A preflight from an unconfigured origin still
    gets 200 (CORS is enforced by the browser, not
    the server) but lacks ``Access-Control-Allow-Origin``,
    so the browser will block the real request."""
    client = _client_with(
        workspace=tmp_path, cors_origins="http://app.example.com"
    )
    resp = client.options(
        "/api/upload",
        headers={
            "Origin": "http://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # Starlette CORSMiddleware rejects unknown origins
    # with 400 (the browser then blocks the real
    # request). The allow-origin header must not echo
    # the evil origin.
    assert resp.status_code == 400
    allow = resp.headers.get("access-control-allow-origin", "")
    assert "evil.example.com" not in allow

def test_cors_actual_get_responds_with_allow_origin(
    tmp_path: Path
) -> None:
    """A real GET from a configured origin is answered
    with the CORS allow-origin header set, so the
    browser lets the JS see the response body."""
    client = _client_with(
        workspace=tmp_path, cors_origins="http://app.example.com"
    )
    resp = client.get(
        "/api/health",
        headers={"Origin": "http://app.example.com"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://app.example.com"

# ---------- 2. Rate limiter ----------

def test_rate_limit_disabled_means_no_429(
    tmp_path: Path
) -> None:
    """With ``rate_limit_per_minute=0`` (the test
    default), 12 POSTs in a row all return their
    normal response (400 from L2 magic check, not
    429 from the limiter)."""
    client = _client_with(workspace=tmp_path, rate_limit=0)
    for _ in range(12):
        r = client.post(
            "/api/upload",
            files={"file": ("x.pdf", b"not pdf", "application/pdf")},
        )
        assert r.status_code != 429

def test_rate_limit_trips_at_threshold(
    tmp_path: Path
) -> None:
    """With ``rate_limit_per_minute=3``, the 4th
    POST in the same window returns 429."""
    client = _client_with(workspace=tmp_path, rate_limit=3)
    statuses: list[int] = []
    for _ in range(5):
        r = client.post(
            "/api/upload",
            files={"file": ("x.pdf", b"not pdf", "application/pdf")},
        )
        statuses.append(r.status_code)
    # First 3 are 400 (L2 magic check), 4th and 5th are 429.
    assert statuses[:3] == [400, 400, 400]
    assert statuses[3] == 429
    assert statuses[4] == 429

def test_rate_limit_response_includes_helpful_detail(
    tmp_path: Path
) -> None:
    """The 429 body explains the limit so a confused
    user can see what happened."""
    client = _client_with(workspace=tmp_path, rate_limit=1)
    client.post(
        "/api/upload",
        files={"file": ("x.pdf", b"not pdf", "application/pdf")},
    )
    r = client.post(
        "/api/upload",
        files={"file": ("x.pdf", b"not pdf", "application/pdf")},
    )
    assert r.status_code == 429
    detail = r.json()["detail"].lower()
    assert "rate limit" in detail

def test_get_requests_are_not_limited(
    tmp_path: Path
) -> None:
    """The limiter is POST-only. 20 GETs in a row
    against a tiny rate limit must all succeed."""
    client = _client_with(workspace=tmp_path, rate_limit=1)
    for _ in range(20):
        r = client.get("/api/health")
        assert r.status_code == 200

# ---------- 3. Settings knobs ----------

def test_settings_has_cors_and_rate_limit_fields() -> None:
    """Both new fields exist on Settings with the
    documented defaults."""
    s = get_settings()
    assert hasattr(s, "cors_allow_origins")
    assert "127.0.0.1:8765" in s.cors_allow_origins
    assert hasattr(s, "rate_limit_per_minute")
    # Default 10 -- the prod value documented in
    # config.py.
    assert s.rate_limit_per_minute == 10
