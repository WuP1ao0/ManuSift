"""Tests for the idempotency-key store (Step G4).

G4 layers an ``Idempotency-Key`` header
on ``/api/upload`` so a client that
retries the same upload (e.g. after a
network blip) is served the cached
response instead of re-running the
analysis. The on-disk store is keyed
on ``Idempotency-Key`` + a body hash;
a reused key with a different body is
rejected as a 409.

Guarantees:

  1. ``record`` + ``lookup`` round-trip:
     after ``record`` returns, a
     subsequent ``lookup`` with the
     same key and same body returns
     the cached response.
  2. A ``lookup`` for a key that has
     never been recorded returns
     ``None`` (a miss).
  3. A ``lookup`` for a key that was
     recorded with a *different* body
     returns an
     ``IdempotencyKeyConflict`` -- the
     client reused a key for a
     different upload, and we reject
     the second one.
  4. Records older than the configured
     TTL are treated as missing.
  5. The store is on disk: a server
     restart (or a second
     ``TestClient`` instance) sees
     the same cached record.
  6. The HTTP integration: an
     ``Idempotency-Key`` header on
     ``/api/upload`` triggers the
     cache. A retry with the same key
     and same body returns the
     cached response; a retry with
     the same key but a different body
     returns 409.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up a fresh workspace and clear
    the settings cache so each test
    reads the same env."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    # Disable the rate limit so concurrent
    # tests do not trip a 429.
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "0")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()


def _pdf() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
        b"xref\n0 1\n0000000000 65535 f\n"
        b"trailer<</Root 1 0 R>>\n"
        b"%%EOF"
    )


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


# ---------- 1. record + lookup round trip ----------

def test_record_then_lookup_returns_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After ``record`` writes a response,
    a subsequent ``lookup`` with the
    same key and same body returns
    the cached record."""
    _env(tmp_path, monkeypatch)
    from manusift.idempotency import lookup, record
    key = "key-1"
    body = b"abc"
    record(
        key=key, body=body,
        status_code=202,
        response_body={"trace_id": "t-1", "status": "queued"},
        trace_id="t-1",
    )
    hit = lookup(key, body)
    assert hit is not None
    assert not isinstance(hit, Exception)
    assert hit.status_code == 202
    assert hit.body == {"trace_id": "t-1", "status": "queued"}


def test_lookup_miss_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``lookup`` for a key that has
    never been recorded returns
    ``None``."""
    _env(tmp_path, monkeypatch)
    from manusift.idempotency import lookup
    assert lookup("never-seen", b"abc") is None


# ---------- 2. Conflict on body mismatch ----------

def test_lookup_with_different_body_returns_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same ``Idempotency-Key`` with
    a different request body returns an
    ``IdempotencyKeyConflict``. We
    refuse to serve the first request's
    response in that case because the
    second payload would be silently
    dropped."""
    _env(tmp_path, monkeypatch)
    from manusift.idempotency import (
        IdempotencyKeyConflict,
        lookup,
        record,
    )
    key = "key-1"
    record(
        key=key, body=b"body-A",
        status_code=202,
        response_body={"trace_id": "t-1"},
        trace_id="t-1",
    )
    # Same key, different body.
    hit = lookup(key, b"body-B")
    assert isinstance(hit, IdempotencyKeyConflict)


# ---------- 3. TTL expiry ----------

def test_lookup_treats_expired_record_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A record older than
    ``settings.idempotency_ttl_seconds``
    is treated as missing. We set
    ``MANUSIFT_IDEMPOTENCY_TTL_SECONDS=0``
    so every existing record is
    immediately expired."""
    _env(tmp_path, monkeypatch)
    monkeypatch.setenv(
        "MANUSIFT_IDEMPOTENCY_TTL_SECONDS", "0"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.idempotency import lookup, record
    key = "key-1"
    body = b"abc"
    record(
        key=key, body=body,
        status_code=202,
        response_body={"trace_id": "t-1"},
        trace_id="t-1",
    )
    # Sleep just enough for the
    # monotonic-clock TTL to be 0 +
    # the time it took to write the
    # record, which is > 0 in
    # practice. We therefore wait
    # for a small positive delay
    # before the lookup.
    time.sleep(0.05)
    assert lookup(key, body) is None


# ---------- 4. On-disk persistence ----------

def test_lookup_after_settings_reload_finds_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store is on disk: a fresh
    settings cache (simulating a
    process restart) still finds the
    same record."""
    _env(tmp_path, monkeypatch)
    from manusift.config import get_settings
    from manusift.idempotency import lookup, record
    key = "key-1"
    body = b"abc"
    record(
        key=key, body=body,
        status_code=202,
        response_body={"trace_id": "t-1"},
        trace_id="t-1",
    )
    # Drop the settings cache and
    # re-read; the record is still
    # there because the on-disk file
    # is the source of truth.
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    hit = lookup(key, body)
    assert hit is not None
    assert hit.body["trace_id"] == "t-1"


# ---------- 5. HTTP integration ----------

def test_http_idempotency_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two ``POST /api/upload`` requests
    with the same ``Idempotency-Key``
    and the same body produce the
    cached response on the second
    call."""
    _env(tmp_path, monkeypatch)
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        pdf = _pdf()
        # First call: cache miss,
        # response is 202 with a new
        # trace_id.
        r1 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            headers={"Idempotency-Key": "k-http-1"},
        )
        assert r1.status_code == 202
        first_trace_id = r1.json()["trace_id"]
        # Second call: same key,
        # same body. Cached.
        r2 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            headers={"Idempotency-Key": "k-http-1"},
        )
        assert r2.status_code == 202
        # The cached response returns
        # the original trace_id; a
        # NEW trace_id would mean the
        # upload ran twice.
        assert r2.json()["trace_id"] == first_trace_id


def test_http_idempotency_conflict_on_body_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second request with the same
    ``Idempotency-Key`` but a
    *different* body returns 409."""
    _env(tmp_path, monkeypatch)
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        pdf = _pdf()
        # First call.
        r1 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
            headers={"Idempotency-Key": "k-http-2"},
        )
        assert r1.status_code == 202
        # Second call: same key, but
        # the file content is different.
        r2 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf + b"different", "application/pdf")},
            headers={"Idempotency-Key": "k-http-2"},
        )
        assert r2.status_code == 409


def test_http_no_idempotency_key_runs_each_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no ``Idempotency-Key``
    header is sent, two requests run
    independently and produce
    *different* trace_ids. This is
    the pre-G4 behavior and we keep
    it as a regression guard."""
    _env(tmp_path, monkeypatch)
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    with TestClient(app) as client:
        pdf = _pdf()
        r1 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
        r2 = client.post(
            "/api/upload",
            files={"file": ("a.pdf", pdf, "application/pdf")},
        )
        assert r1.status_code == 202
        assert r2.status_code == 202
        # No idempotency: each upload
        # got a unique trace id.
        assert r1.json()["trace_id"] != r2.json()["trace_id"]
