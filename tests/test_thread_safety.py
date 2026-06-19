"""Tests for thread-safety hardening (Step G2).

G2 wraps the in-process counters and the
rate-limit hits dict in a single
``threading.Lock``. The lock guards
``read-modify-write`` sequences that
were racy under FastAPI's BackgroundTasks
worker pool. We assert three properties:

  1. ``_bump`` increments are atomic: a
     burst of concurrent calls produces
     exactly the expected count (no
     dropped increments).
  2. The rate-limit middleware reports a
     consistent count even under
     concurrent requests from the same
     client IP -- the limit is enforced
     exactly.
  3. ``InMemoryJobStore.set`` /
     ``InMemoryJobStore.get`` are safe
     under concurrent ``set`` and
     ``get`` calls. We do not need a
     hard invariant (the dict is the
     SoT for tests that want a per-test
     store), just that no read or write
     crashes or returns a partial
     state.
"""
from __future__ import annotations

import threading
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


def _bump_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a TestClient that exercises
    the in-process counter helpers."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.app import _bump, _METRICS, _METRICS_LOCK
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    return app, _bump, _METRICS, _METRICS_LOCK


# ---------- 1. _bump is atomic ----------

def test_bump_increments_are_atomic_under_threads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burst of 100 concurrent ``_bump``
    calls on a fresh counter produces
    exactly 100 (no dropped increments).
    Without the lock, a read-modify-write
    sequence (``x = x + 1``) can lose
    updates when two threads interleave.
    """
    _, _bump, _METRICS, _METRICS_LOCK = _bump_client(
        tmp_path, monkeypatch
    )
    _METRICS["burst_total"] = 0
    def worker() -> None:
        for _ in range(10):
            _bump("burst_total")
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 10 threads * 10 increments = 100.
    assert _METRICS["burst_total"] == 100


# ---------- 2. Rate limit is enforced exactly ----------

def test_rate_limit_enforced_under_concurrent_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``rate_limit_per_minute=5`` and
    20 concurrent POSTs from the same
    client IP, exactly 5 succeed and
    exactly 15 are rejected. Without the
    lock, two concurrent requests can
    both see ``len(window) < 5`` and
    both append, letting one extra
    request slip through."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv(
        "MANUSIFT_RATE_LIMIT_PER_MINUTE", "5"
    )
    if hasattr(getattr(__import__("manusift.config", fromlist=["get_settings"]), "get_settings"), "cache_clear"):
        __import__("manusift.config", fromlist=["get_settings"]).get_settings.cache_clear()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    # Need a real PDF body for the upload to
    # be valid. We use a minimal valid PDF.
    pdf_body = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
        b"xref\n0 1\n0000000000 65535 f\n"
        b"trailer<</Root 1 0 R>>\n"
        b"%%EOF"
    )
    create_app = _patch_upload_pipeline(monkeypatch)
    app = create_app()
    # The client preserves cookies across
    # requests in a single ``TestClient``,
    # but the rate limiter keys on
    # ``request.client.host``. ``TestClient``
    # uses ``testclient`` as the host.
    with TestClient(app) as client:
        client.app.state.reset_rate_limiter()
        # Reset the rate_limited_total counter
        # (we just bumped it via 429s in
        # earlier tests; we want a clean
        # baseline for the assertion below).
        from manusift.web.app import _METRICS, _METRICS_LOCK
        with _METRICS_LOCK:
            _METRICS["rate_limited_total"] = 0
        # Fire 20 concurrent POSTs.
        results: list[int] = []
        results_lock = threading.Lock()
        def fire() -> None:
            r = client.post(
                "/api/upload",
                files={"file": ("a.pdf", pdf_body, "application/pdf")},
            )
            with results_lock:
                results.append(r.status_code)
        threads = [threading.Thread(target=fire) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Exactly 5 accepted (200) and
        # 15 rejected (429). The lock is
        # what makes this exact.
        assert results.count(202) == 5
        assert results.count(429) == 15  # unchanged


# ---------- 3. InMemoryJobStore is thread-safe ----------

def test_inmemory_jobstore_concurrent_set_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """50 threads writing and reading the
    ``InMemoryJobStore`` simultaneously
    never raise. We do not assert a
    strong invariant on the result; we
    only assert no crash and a sane
    final state (one of the writes
    "wins" for each trace id)."""
    from manusift.contracts import JobState
    from manusift.web.jobs_db import InMemoryJobStore
    from manusift.tools import ToolContext
    store = InMemoryJobStore()
    n_writers = 5
    n_writes_per_writer = 10
    barrier = threading.Barrier(n_writers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    def writer(idx: int) -> None:
        try:
            barrier.wait(timeout=2.0)
            for j in range(n_writes_per_writer):
                tid = f"t-{idx}-{j}"
                store.set(JobState(
                    trace_id=tid,
                    status="queued",
                    source_filename=f"f-{idx}-{j}.pdf",
                ))
                # Read after write -- should
                # return the value we just set.
                got = store.get(tid)
                assert got is not None
                assert got.trace_id == tid
        except BaseException as e:  # noqa: BLE001
            with errors_lock:
                errors.append(e)
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # All trace_ids are present.
    all_jobs = store.all()
    assert len(all_jobs) == n_writers * n_writes_per_writer
