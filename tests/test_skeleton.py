"""Step-1 smoke tests + one end-to-end PDF roundtrip."""
from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest
from starlette.testclient import TestClient

from manusift.config import get_settings
from manusift.contracts import AnalysisResult, Finding, JobState, ParsedDoc
from manusift.web.app import create_app


# ---------- contract / smoke ----------

def test_health_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "version" in body


def test_index_serves_html() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "ManuSift" in resp.text


def test_contracts_importable() -> None:
    f = Finding.make("t1", "metadata", "low", "title", "evidence", "loc")
    assert f.trace_id == "t1"
    assert f.severity == "low"
    assert f.finding_id  # auto-generated

    job = JobState(trace_id="t1", status="queued")
    assert job.status == "queued"


# ---------- end-to-end ----------

def _build_synthetic_pdf(
    path: Path,
    *,
    producer: str = "Skia/PDF m117",
    embed_duplicate: bool = True,
) -> None:
    """Write a tiny 1-page PDF with a known producer and (optionally)
    the same image embedded twice -- guarantees the image_dup
    detector fires."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((40, 40), "Synthetic paper - ManuSift smoke test")

    # Build a non-degenerate PNG in memory and embed
    # it twice. The previous synthetic fixture used a
    # 16x16 solid-color square, which the
    # image_dup detector used to flag (every
    # solid-color icon hashed to all-zero and
    # matched every other one). The fix in
    # ``_compute_phash`` (R-audit, 2026-06)
    # filters solid-color / too-small images
    # out of pHashing, so the fixture now uses
    # a 64x64 image with enough detail (a few
    # rectangles + text) to register as a
    # non-degenerate pHash. Two identical
    # copies still produce one image_dup
    # finding as before.
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 64), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 32, 32], fill=(200, 50, 50))
    d.ellipse([36, 16, 60, 48], fill=(50, 100, 200))
    img_bytes_io = io.BytesIO()
    img.save(img_bytes_io, format="PNG")
    img_bytes = img_bytes_io.getvalue()

    page.insert_image(fitz.Rect(40, 80, 200, 240), stream=img_bytes)
    if embed_duplicate:
        page.insert_image(fitz.Rect(40, 260, 200, 420), stream=img_bytes)

    doc.set_metadata(
        {
            "title": "Synthetic",
            "author": "test",
            "producer": producer,
        }
    )
    doc.save(str(path))
    doc.close()


def test_upload_and_pipeline_runs(
    tmp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_workspace.parent / "synthetic.pdf"
    _build_synthetic_pdf(pdf_path)
    from manusift import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod,
        "_BUILTIN_DETECTOR_CLASS_NAMES",
        ["MetadataDetector", "ImageDuplicateDetector"],
    )

    app = create_app()
    with TestClient(app) as client:
        with open(pdf_path, "rb") as f:
            resp = client.post(
                "/api/upload",
                files={"file": ("synthetic.pdf", f, "application/pdf")},
            )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        tid = body["trace_id"]
        assert body["status"] == "queued"
        assert "X-ManuSift-Trace-Id" in resp.headers

        # Poll until done.
        for _ in range(40):
            r = client.get(f"/api/jobs/{tid}")
            assert r.status_code == 200
            j = r.json()
            if j["status"] in ("done", "failed"):
                break
            import time
            time.sleep(0.1)
        assert j["status"] == "done", j
        assert j["finding_count"] >= 1  # at least the image_dup

        # Findings JSON should be present and parse.
        fr = client.get(f"/api/jobs/{tid}/findings")
        assert fr.status_code == 200
        findings = fr.json()["findings"]
        assert any(f["detector"] == "image_dup" for f in findings)

        # Report HTML should render.
        rr = client.get(f"/api/jobs/{tid}/report")
        assert rr.status_code == 200
        assert "ManuSift report" in rr.text
        assert "Near-duplicate image detected" in rr.text


def test_upload_rejects_non_pdf(tmp_workspace: Path) -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/upload",
            files={"file": ("notes.txt", b"not a pdf", "text/plain")},
        )
        assert resp.status_code == 400


def test_settings_load(tmp_workspace: Path) -> None:
    s = get_settings()
    assert s.workspace_dir == tmp_workspace
    assert s.image_duplicate_hamming_threshold >= 0
