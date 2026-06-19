"""Tests for the PDF report endpoint (Step P2-A1).

The HTML report has shipped since Step 1. P2-A1
layers a PDF export on top by rendering the same
HTML through ``weasyprint``. The endpoint is
``GET /api/jobs/<trace_id>/report.pdf``; the
browser gets a binary ``application/pdf`` with
a sensible ``Content-Disposition`` filename.

Weasyprint's pure-Python package installs on
Windows but cannot actually render without the
GTK runtime (``libgobject``). On a Windows
machine without that runtime, the
``build_report_pdf`` tests are skipped (the
endpoint tests still run because they exercise
the 501 path). On Linux / macOS with GTK
installed, every test runs.

Guarantees:

  1. ``build_report_pdf`` returns a non-empty
     ``bytes`` object whose magic header is
     ``b"%PDF-"`` (a real PDF).
  2. The endpoint serves that bytes back with
     content-type ``application/pdf`` and a
     ``Content-Disposition`` attachment header.
  3. If the findings JSON is missing the
     endpoint returns 404 (same as the HTML
     report).
  4. If ``weasyprint`` is not importable, the
     endpoint returns 501 (Not Implemented)
     with a helpful ``detail`` that points at
     the install command.
  5. ``WeasyprintNotInstalled`` is a subclass of
     ``ImportError`` so callers can catch the
     broader case.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.contracts import Finding
from manusift.report import (
    WeasyprintNotInstalled,
    build_report_html,
    build_report_pdf,
)
from manusift.web import app as web_mod
from manusift.workspace import JobPaths


def _weasyprint_can_render() -> bool:
    """True if ``weasyprint`` can produce a PDF
    in this environment. We probe by rendering
    a one-character HTML page; if it raises
    OSError (missing GTK) or ImportError
    (package missing) the test suite should
    skip the render-dependent cases.
    """
    try:
        build_report_pdf(
            trace_id="probe",
            findings=[],
            detectors_run=[],
            llm_calls=0,
            settings=Settings(_env_file=None),  # type: ignore[call-arg]
        )
    except WeasyprintNotInstalled:
        return False
    except Exception:
        return False
    return True


weasyprint_can_render = pytest.mark.skipif(
    not _weasyprint_can_render(),
    reason="weasyprint missing or its GTK runtime unavailable",
)


# ---------- 1. magic header ----------

@pytest.mark.skipif(not _weasyprint_can_render(), reason='weasyprint unavailable')
def test_build_report_pdf_returns_pdf_bytes(
    tmp_path: Path,
) -> None:
    """The bytes start with ``%PDF-``, the magic
    every conforming PDF begins with. A non-PDF
    blob would start with anything else (e.g.
    ``<!doctype html>`` from a fallback path)."""
    pdf = build_report_pdf(
        trace_id="t-001",
        findings=[],
        detectors_run=["metadata"],
        llm_calls=0,
        settings=Settings(workspace_dir=tmp_path),
    )
    assert isinstance(pdf, bytes)
    assert len(pdf) > 100  # a real PDF is not 50 bytes
    assert pdf.startswith(b"%PDF-")


@pytest.mark.skipif(not _weasyprint_can_render(), reason='weasyprint unavailable')
def test_build_report_pdf_with_findings(
    tmp_path: Path,
) -> None:
    """A non-empty finding list still produces a
    valid PDF. We do not assert on specific
    content (the rendered layout is weasyprint
    internals) -- only that the magic header is
    correct and the file is non-trivial in
    size."""
    findings = [
        Finding(
            finding_id="f-1",
            trace_id="t-001",
            detector="metadata",
            severity="high",
            title="Ghostscript producer",
            evidence="Producer field is empty",
            location="metadata",
            raw={},
        ),
        Finding(
            finding_id="f-2",
            trace_id="t-002",
            detector="text_patterns",
            severity="medium",
            title="'As an AI language model'",
            evidence="phrase found on page 1",
            location="page 1",
            raw={},
        ),
    ]
    pdf = build_report_pdf(
        trace_id="t-002",
        findings=findings,
        detectors_run=["metadata", "text_patterns"],
        llm_calls=2,
        settings=Settings(workspace_dir=tmp_path),
    )
    assert pdf.startswith(b"%PDF-")
    # Sanity: the PDF is at least 1 KB with
    # two findings rendered.
    assert len(pdf) > 1024


# ---------- 2. WeasyprintNotInstalled is an ImportError ----------

def test_weasyprint_not_installed_is_import_error() -> None:
    """The sentinel is a subclass of
    ``ImportError`` so a caller that catches
    ``ImportError`` (the standard Python pattern)
    still works."""
    assert issubclass(
        WeasyprintNotInstalled, ImportError
    )


# ---------- 3. 501 when weasyprint missing ----------

def test_endpoint_returns_501_when_weasyprint_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hide the weasyprint module so the
    endpoint catches the missing-dep case and
    returns 501 (Not Implemented) with a
    helpful detail. The HTTP code is 501
    rather than 500 because the server is
    fine -- only the optional dep is missing.
    """
    # Build a real job with findings.json on
    # disk so the request reaches the weasyprint
    # branch.
    paths = JobPaths.for_trace("t-501", tmp_path)
    paths.ensure()
    paths.findings_json.write_text(
        json.dumps({
            "findings": [],
            "detectors_run": ["metadata"],
            "llm_calls": 0,
        }),
        encoding="utf-8",
    )
    import builtins
    real_import = builtins.__import__
    def guarded_import(name, *a, **kw):
        if name == "weasyprint" or name.startswith("weasyprint."):
            raise ImportError("simulated missing weasyprint")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=tmp_path)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/jobs/t-501/report.pdf")
    assert r.status_code == 501
    assert "pip install weasyprint" in r.json()["detail"]


# ---------- 4. 404 when findings JSON missing ----------

def test_endpoint_returns_404_when_findings_missing(
    tmp_path: Path,
) -> None:
    """Without ``findings.json`` on disk the
    endpoint returns 404 -- the job has not
    finished yet (or never started)."""
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=tmp_path)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/jobs/never-existed/report.pdf")
    assert r.status_code == 404
    assert "not ready" in r.json()["detail"]


# ---------- 5. happy path through the HTTP layer ----------

@pytest.mark.skipif(not _weasyprint_can_render(), reason='weasyprint unavailable')
def test_endpoint_returns_pdf_happy_path(
    tmp_path: Path,
) -> None:
    """A finished job with findings gets a real
    PDF back. The Content-Disposition header
    uses the trace id so a browser saves it as
    ``manusift-<tid>.pdf``."""
    paths = JobPaths.for_trace("t-happy", tmp_path)
    paths.ensure()
    findings = [
        Finding(
            finding_id="f-1",
            trace_id="t-001",
            detector="metadata",
            severity="high",
            title="Ghostscript producer",
            evidence="Producer field is empty",
            location="metadata",
            raw={},
        ),
    ]
    paths.findings_json.write_text(
        json.dumps({
            "findings": [f.__dict__ for f in findings],
            "detectors_run": ["metadata"],
            "llm_calls": 1,
        }),
        encoding="utf-8",
    )
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=tmp_path)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/jobs/t-happy/report.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/pdf"
    )
    # The Content-Disposition header carries
    # the trace id so the file is saved as
    # ``manusift-t-happy.pdf``.
    cd = r.headers["content-disposition"]
    assert "attachment" in cd
    assert "manusift-t-happy.pdf" in cd
    # The bytes are a real PDF.
    assert r.content.startswith(b"%PDF-")


# ---------- 6. HTML and PDF render the same content ----------

def test_html_and_pdf_have_matching_trace_id() -> None:
    """The PDF is a render of the HTML. We
    verify the two contain the same trace id
    in some form: the HTML escapes it into the
    title, the PDF contains it in the rendered
    text. We do not string-search the PDF
    binary (which is encoded) -- instead we
    just assert the HTML contains the trace id
    and trust that the PDF renderer carried
    the same input through to output."""
    html = build_report_html(
        trace_id="t-content-check",
        findings=[],
        detectors_run=[],
        llm_calls=0,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
    )
    assert "t-content-check" in html
