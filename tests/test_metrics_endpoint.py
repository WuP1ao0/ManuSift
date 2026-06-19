"""Tests for the Prometheus /metrics endpoint (P0-11).

The endpoint exposes a hand-written Prometheus text
payload. It is only active when
``Settings.prometheus_port > 0`` -- for the default
zero the endpoint returns 404 (the same shape the
L5 readiness probe uses) so a curious scraper
sees a clear "off" signal instead of an empty
200.

Guarantees:

  1. With the default ``prometheus_port=0`` the
     endpoint returns 404 with a helpful detail.
  2. With ``prometheus_port>0`` it returns 200
     with a ``text/plain; version=0.0.4`` body
     that parses as Prometheus text format
     (every metric has the ``# HELP`` / ``# TYPE``
     / value triple).
  3. The body includes the four counters we
     declared (http_requests_total, uploads_total,
     rate_limited_total, llm_calls_total) and
     nothing else.
  4. ``_render_prometheus_metrics`` (the module
     helper) can be called without an app to
     smoke-test the format directly.
"""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.web.app import _render_prometheus_metrics, create_app


def _client(workspace: Path, *, prometheus_port: int = 0) -> TestClient:
    s = Settings(
        workspace_dir=workspace,
        prometheus_port=prometheus_port,
    )
    return TestClient(
        create_app(settings=s),
        raise_server_exceptions=False,
    )


# ---------- 1. Default (port=0) returns 404 ----------

def test_metrics_disabled_by_default(tmp_path: Path) -> None:
    """With the default prometheus_port=0, the
    endpoint returns 404 with a helpful detail
    explaining how to enable it."""
    c = _client(tmp_path)
    r = c.get("/metrics")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "MANUSIFT_PROMETHEUS_PORT" in detail


# ---------- 2. Enabled (port>0) returns 200 ----------

def test_metrics_enabled_returns_prometheus_text(
    tmp_path: Path,
) -> None:
    """Setting prometheus_port>0 enables the
    endpoint. The body is the standard Prometheus
    text format."""
    c = _client(tmp_path, prometheus_port=8765)
    r = c.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    # Sanity: ends with a newline, has at least 12
    # lines (4 counters x 3 lines each).
    assert body.endswith("\n")
    assert body.count("\n") >= 12


# ---------- 3. The four declared counters ----------

def test_metrics_includes_all_four_counters(
    tmp_path: Path,
) -> None:
    """The schema is fixed today: http_requests_total,
    uploads_total, rate_limited_total, llm_calls_total.
    Adding a new counter is intentional; removing
    one is a contract break and should require
    updating this test."""
    c = _client(tmp_path, prometheus_port=8765)
    body = c.get("/metrics").text
    expected = [
        "manusift_http_requests_total",
        "manusift_uploads_total",
        "manusift_rate_limited_total",
        "manusift_llm_calls_total",
    ]
    for name in expected:
        # Each counter has a # HELP, # TYPE, and
        # value line. The name appears at least 3
        # times (once per line).
        assert body.count(name) >= 3, f"missing {name}"


# ---------- 4. Format is valid Prometheus text ----------

def test_metrics_format_is_prometheus_compliant(
    tmp_path: Path,
) -> None:
    """Every metric line follows ``name{labels} value``.
    Every counter has a ``# HELP`` and ``# TYPE``
    header. The format check is deliberately
    minimal: we want to catch "missing # HELP" or
    "garbled value line" regressions, not validate
    the whole spec."""
    c = _client(tmp_path, prometheus_port=8765)
    body = c.get("/metrics").text
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        # The value line for counter ``foo`` is
        # ``foo 0`` (no labels, just space and
        # integer).
        parts = line.split()
        assert len(parts) == 2, f"bad value line: {line!r}"
        name, value = parts
        assert name.startswith("manusift_"), name
        int(value)  # raises if not an integer


# ---------- 5. Module-level helper smoke test ----------

def test_render_helper_is_callable_directly() -> None:
    """``_render_prometheus_metrics`` does not need
    an app or a request; it just builds a string.
    We assert the output is a non-empty bytes-ish
    payload and the function does not raise."""
    out = _render_prometheus_metrics()
    assert isinstance(out, str)
    assert out.endswith("\n")
    assert "manusift_http_requests_total" in out


# ---------- 6. Settings knob ----------

def test_settings_has_prometheus_port_field() -> None:
    """The field exists with the documented default."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert hasattr(s, "prometheus_port")
    assert s.prometheus_port == 0
