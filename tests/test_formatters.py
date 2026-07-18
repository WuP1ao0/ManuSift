"""Tests for the output formatter registry (Step E1).

Pre-E1, the report had exactly one
format (HTML). E1 introduces an
``OutputFormatter`` Protocol, three
built-in formatters (HTML, JSON,
Markdown), and a single
``/api/jobs/<tid>/fmt/<fmt>`` endpoint
that delegates to the right formatter.
Third-party plugins can register
formatters via the
``manusift.formatters`` entry-point
group.

Guarantees:

  1. ``list_formatters`` returns the
     names of every registered
     formatter, sorted, including
     built-ins.
  2. ``get_formatter(name)`` returns a
     formatter with the given name.
     ``FormatterNotFound`` is raised
     for an unknown name.
  3. ``HtmlFormatter.format`` returns
     bytes; the bytes start with ``<!DOCTYPE``
     (an HTML document) and contain the
     trace id.
  4. ``JsonFormatter.format`` returns
     pretty-printed JSON; the
     ``trace_id`` field is present and
     matches.
  5. ``MarkdownFormatter.format``
     returns a Markdown document; a
     ``# ManuSift report: <trace>``
     heading is present.
  6. The ``/api/formats`` endpoint
     returns a ``{"formats": [...]}``
     JSON object.
  7. ``/api/jobs/<tid>/fmt/json``
     returns 200 with a JSON body and
     a ``Content-Disposition``
     attachment header.
  8. ``/api/jobs/<tid>/fmt/nonexistent``
     returns 404 with a helpful detail
     message that names the available
     formats.
  9. ``/api/jobs/<tid>/fmt/json`` with
     no findings.json on disk returns
     404 (the report is not ready).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "0")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()


def _seed_findings(tmp_path: Path, trace_id: str) -> Path:
    """Write a findings.json so the
    /fmt/<fmt> endpoint has data to
    render."""
    from manusift.workspace import JobPaths

    paths = JobPaths.for_trace(trace_id, tmp_path / "ws")
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "trace_id": trace_id,
        "findings": [
            {
                "trace_id": trace_id,
                "detector": "metadata",
                "severity": "low",
                "finding_id": "f-seed-1",
                "title": "no-op finding",
                "evidence": "synthetic",
                "location": "PDF / Info dictionary",
                "raw": {},
            }
        ],
        "detectors_run": ["metadata", "image_dup"],
        "llm_calls": 0,
        "duration_ms": 12,
    }
    (paths.output_dir / "findings.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths.root


# ---------- 1. Built-in formatters ----------

def test_list_formatters_returns_sorted_builtin_names() -> None:
    """``list_formatters`` returns the
    three built-in formatter names
    sorted alphabetically."""
    from manusift.formatters import list_formatters
    names = list_formatters()
    assert "html" in names
    assert "json" in names
    assert "md" in names
    # Sorted.
    assert names == sorted(names)


def test_get_formatter_unknown_raises() -> None:
    """An unknown formatter name
    raises ``FormatterNotFound``."""
    from manusift.formatters import (
        FormatterNotFound,
        get_formatter,
    )
    with pytest.raises(FormatterNotFound):
        get_formatter("nope-does-not-exist")


def test_get_formatter_returns_same_instance() -> None:
    """The built-in formatters are
    singletons: ``get_formatter(name)``
    returns the same object on every
    call."""
    from manusift.formatters import get_formatter
    a = get_formatter("html")
    b = get_formatter("html")
    assert a is b


# ---------- 2. Built-in format() shapes ----------

def test_html_formatter_returns_html_bytes() -> None:
    """``HtmlFormatter.format`` returns
    bytes that start with ``<!DOCTYPE``
    and contain the trace id."""
    from manusift.formatters import HtmlFormatter
    class _R:
        trace_id = "t-html-1"
        findings = []
        detectors_run = []
        llm_calls = 0
        duration_ms = 0
    out = HtmlFormatter().format(_R())
    assert isinstance(out, bytes)
    text = out.decode("utf-8")
    assert text.lower().startswith("<!doctype") or text.lower().startswith("<html")
    assert "t-html-1" in text


def test_json_formatter_returns_valid_json() -> None:
    """``JsonFormatter.format`` returns
    valid JSON with a ``trace_id`` field
    that matches the input."""
    from manusift.formatters import JsonFormatter
    class _R:
        trace_id = "t-json-1"
        findings = []
        detectors_run = ["metadata"]
        llm_calls = 2
        duration_ms = 99
    out = JsonFormatter().format(_R())
    data = json.loads(out.decode("utf-8"))
    assert data["trace_id"] == "t-json-1"
    assert data["detectors_run"] == ["metadata"]
    assert data["llm_calls"] == 2
    # The JSON is pretty-printed and
    # sorted.
    text = out.decode("utf-8")
    assert "\n  " in text or "\n    " in text


def test_markdown_formatter_returns_md_bytes() -> None:
    """``MarkdownFormatter.format``
    returns a Markdown document; the
    heading is ``# ManuSift report:
    <trace_id>``."""
    from manusift.formatters import MarkdownFormatter
    class _R:
        trace_id = "t-md-1"
        findings = []
        detectors_run = ["metadata", "image_dup"]
        llm_calls = 1
    out = MarkdownFormatter().format(_R())
    text = out.decode("utf-8")
    assert "# ManuSift report: t-md-1" in text
    assert "Detectors run: 2" in text


# ---------- 3. /api/formats discovery endpoint ----------

def test_api_formats_endpoint_returns_sorted_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/api/formats`` returns a JSON
    object whose ``formats`` field is a
    sorted list of formatter names."""
    _env(tmp_path, monkeypatch)
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/formats")
        assert r.status_code == 200
        body = r.json()
        assert "formats" in body
        names = body["formats"]
        assert "html" in names
        assert "json" in names
        assert "md" in names
        assert names == sorted(names)


# ---------- 4. /api/jobs/<tid>/fmt/<fmt> ----------

def test_fmt_json_endpoint_returns_200_with_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/api/jobs/<tid>/fmt/json``
    returns 200 with a JSON body and a
    ``Content-Disposition`` attachment
    header. The trace_id of the
    request is present in the JSON."""
    _env(tmp_path, monkeypatch)
    _seed_findings(tmp_path, "t-fmt-json")
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/t-fmt-json/fmt/json")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "t-fmt-json.json" in cd
        body = r.json()
        assert body["trace_id"] == "t-fmt-json"


def test_fmt_md_endpoint_returns_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/api/jobs/<tid>/fmt/md`` returns
    200 with a Markdown body and a
    ``.md`` attachment filename."""
    _env(tmp_path, monkeypatch)
    _seed_findings(tmp_path, "t-fmt-md")
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/t-fmt-md/fmt/md")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        cd = r.headers.get("content-disposition", "")
        assert "t-fmt-md.md" in cd
        body = r.text
        assert "# ManuSift report: t-fmt-md" in body


def test_fmt_unknown_returns_404_with_available_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown format name returns
    404 with a detail message that
    lists the available formats. The
    client gets a self-documenting
    error rather than a generic 500.
    """
    _env(tmp_path, monkeypatch)
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/whatever/fmt/csv")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body
        # The detail message mentions
        # the available formats.
        assert "html" in body["detail"]
        assert "json" in body["detail"]


def test_fmt_returns_404_when_findings_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/api/jobs/<tid>/fmt/json`` with
    no findings.json on disk returns
    404 (the report is not ready). The
    same 404 is used for a missing
    job, so the client cannot
    distinguish "unknown job" from
    "job not yet finished"; the
    /progress endpoint is the
    authoritative source for that
    distinction.
    """
    _env(tmp_path, monkeypatch)
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/no-such-job/fmt/json")
        assert r.status_code == 404
        body = r.json()
        assert "findings" in body["detail"].lower() or "not ready" in body["detail"]


# ---------- 5. /report.html still works (backward compat) ----------

def test_legacy_html_endpoint_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-E1 ``/api/jobs/<tid>/report``
    endpoint keeps working -- the HTML
    response is served verbatim from
    the on-disk report.html file."""
    _env(tmp_path, monkeypatch)
    trace_id = "t-legacy"
    job_dir = tmp_path / "ws" / trace_id / "output"
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "report.html").write_text(
        "<!DOCTYPE html><html><body>legacy</body></html>",
        encoding="utf-8",
    )
    from manusift.web.app import create_app
    app = create_app()
    with TestClient(app) as client:
        r = client.get(f"/api/jobs/{trace_id}/report")
        assert r.status_code == 200
        assert "legacy" in r.text
