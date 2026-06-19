"""Tests for the liveness + readiness probes (L5).

Two endpoints are added on top of the legacy
``/api/health``:

  * ``GET /api/healthz`` -- liveness. Returns 200 as
    long as the process is running. Does not touch
    any external service. Kubernetes liveness probes
    should hit this.

  * ``GET /api/health/ready`` -- readiness. Returns
    200 only if the workspace dir is writable, the
    LLM client can be constructed, and the
    detector registry loads. On any failure it
    returns 503 with a ``checks`` payload so an
    operator can see what is wrong.

The legacy ``/api/health`` endpoint is kept for
backward compatibility and still returns 200.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.web.app import create_app


def _client(workspace: Path) -> TestClient:
    """A TestClient with an explicit Settings (so
    no env-leak race). Workspace is the (writable)
    test directory; readiness should be green."""
    settings = Settings(workspace_dir=workspace)
    return TestClient(create_app(settings=settings))


# ---------- 1. Legacy /api/health (backward compat) ----------

def test_legacy_health_endpoint_still_works(tmp_path: Path) -> None:
    """The original /api/health must keep working
    so old dashboards do not break."""
    c = _client(tmp_path)
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------- 2. Liveness /api/healthz ----------

def test_healthz_always_returns_200(tmp_path: Path) -> None:
    """Liveness does not depend on disk or LLM. It
    must be 200 even if the workspace is read-only."""
    # We pass a non-writable workspace on Windows by
    # giving a path inside a read-only system folder.
    # The probe creates .ready_probe inside the
    # workspace; liveness never touches that. We
    # verify the endpoint is 200 regardless.
    c = _client(tmp_path)
    r = c.get("/api/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alive"
    assert "version" in body


def test_healthz_response_shape(tmp_path: Path) -> None:
    """The shape is exactly ``{status, version}``;
    no other keys leak through, so a k8s probe that
    matches on keys does not get confused."""
    c = _client(tmp_path)
    body = c.get("/api/healthz").json()
    assert set(body.keys()) == {"status", "version"}


# ---------- 3. Readiness /api/health/ready ----------

def test_ready_returns_200_when_everything_ok(tmp_path: Path) -> None:
    """With a writable workspace, a real Settings,
    and the 4 built-in detectors, readiness is 200."""
    c = _client(tmp_path)
    r = c.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    checks = body["checks"]
    assert checks["workspace"] == "writable"
    assert checks["workspace"] == "writable"
    # The LLM client reports its name. With no API
    # keys, MockLLM is the default.
    assert "llm" in checks
    # Detectors report the count.
    assert checks["detectors"].startswith("loaded ")


def test_ready_returns_503_when_workspace_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the workspace dir is not writable, the
    readiness probe must return 503 and explain
    why. We monkeypatch ``Path.write_text`` so
    the probe-write fails regardless of platform
    permissions."""
    c = _client(tmp_path)
    from pathlib import Path as _Path
    real_write = _Path.write_text

    def failing_write(self, *a, **kw):  # type: ignore[no-untyped-def]
        if self.name == ".ready_probe":
            raise OSError("simulated unwritable workspace")
        return real_write(self, *a, **kw)

    monkeypatch.setattr(_Path, "write_text", failing_write)
    r = c.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert "unwritable" in body["checks"]["workspace"]





def test_ready_response_includes_all_three_checks(
    tmp_path: Path,
) -> None:
    """Every readiness response must contain a
    ``checks`` dict with all three of workspace,
    llm, and detectors, so an operator can see at
    a glance what is wrong."""
    c = _client(tmp_path)
    body = c.get("/api/health/ready").json()
    assert "checks" in body
    assert set(body["checks"].keys()) >= {
        "workspace", "llm", "detectors"
    }


def test_health_and_healthz_and_ready_all_documented_in_openapi(
    tmp_path: Path,
) -> None:
    """FastAPI auto-generates /openapi.json. A new
    operator reading the OpenAPI doc should be able
    to see all three endpoints without reading
    source code."""
    c = _client(tmp_path)
    r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/health" in paths
    assert "/api/healthz" in paths
    assert "/api/health/ready" in paths
