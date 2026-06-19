"""Tests for upload hardening (L2).

Two guarantees:

  1. Files larger than ``Settings.max_upload_mb`` are
     rejected with HTTP 413 before being written to
     disk.
  2. Files that do not start with the ``%PDF-`` magic
     number are rejected with HTTP 400, even if their
     filename ends in ``.pdf``.

Both checks run **after** the body has been read into
memory but **before** the bytes are written to the
job's ``original.pdf`` slot, so a rejected upload leaves
no trace on disk.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz  # type: ignore[import-not-found]
import pytest
from starlette.testclient import TestClient

from manusift.config import get_settings
from manusift.web.app import create_app


# ---------- helpers ----------

def _patch_upload_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _build_minimal_pdf() -> bytes:
    """A real, valid 1-page PDF as bytes. PyMuPDF
    produces output that starts with ``%PDF-`` and is
    small (<10 KB)."""
    doc = fitz.open()
    doc.new_page(width=300, height=200)
    doc[0].insert_text((40, 40), "hello")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------- 1. magic-number check ----------

def test_upload_rejects_non_pdf_with_pdf_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file whose bytes start with ``hello`` is
    not a PDF, even if the filename is ``evil.pdf``.
    The endpoint must reject it with HTTP 400."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _patch_upload_pipeline(monkeypatch)
    client = TestClient(create_app())
    resp = client.post(
        "/api/upload",
        files={"file": ("evil.pdf", b"hello world", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "magic number" in resp.json()["detail"].lower()
    # No job dir was created.
    assert list(workspace.iterdir()) == []


def test_upload_rejects_empty_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty file is also not a valid PDF."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _patch_upload_pipeline(monkeypatch)
    client = TestClient(create_app())
    resp = client.post(
        "/api/upload",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


def test_upload_accepts_real_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine PyMuPDF-generated PDF passes both
    checks and gets a trace_id back."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _patch_upload_pipeline(monkeypatch)
    client = TestClient(create_app())
    pdf_bytes = _build_minimal_pdf()
    # Sanity: it really starts with %PDF-.
    assert pdf_bytes.startswith(b"%PDF-")
    resp = client.post(
        "/api/upload",
        files={"file": ("real.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code in (200, 202)  # background-task endpoint
    body = resp.json()
    assert "trace_id" in body
    assert body["status"] == "queued"


# ---------- 2. size cap ----------

def test_upload_rejects_oversize_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file larger than ``max_upload_mb`` is rejected
    with HTTP 413. We set the cap to 1 MB and send a
    ~2 MB PDF (padded with a junk page, which is still
    a valid PDF, so the magic check passes)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_MAX_UPLOAD_MB", "1")
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    client = TestClient(create_app())
    # Build a ~2 MB PDF. PyMuPDF's flate compression
    # makes padding expensive to keep simple, so we
    # use raw uncompressed object streams.
    big = b"%PDF-1.4\n"
    # Each line in the object table contributes 1
    # KB; 3000 lines = ~3 MB.
    big += b"1 0 obj\n<< /Length 3000 >>\nstream\n"
    big += b"X" * 3000
    big += b"\nendstream endobj\n"
    # Pad to > 1 MB with a valid-ish trailer.
    big += b"X" * (1024 * 1024)
    big += b"\n%%EOF"
    assert len(big) > 1024 * 1024
    resp = client.post(
        "/api/upload",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert "too large" in body["detail"].lower()


def test_oversize_rejection_does_not_write_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The size check runs before the file is written;
    a rejected upload must leave no trace."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_MAX_UPLOAD_MB", "1")
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    client = TestClient(create_app())
    big = b"%PDF-1.4\n" + b"X" * (2 * 1024 * 1024)
    resp = client.post(
        "/api/upload",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert resp.status_code == 413
    # Workspace must be empty (no job dir created).
    assert list(workspace.iterdir()) == []


# ---------- 3. import sanity ----------

def test_settings_has_max_upload_mb_field() -> None:
    """The cap field exists on Settings and has a
    sensible default."""
    s = get_settings()
    assert hasattr(s, "max_upload_mb")
    # 50 MB is the default documented in config.py.
    assert s.max_upload_mb == 50
