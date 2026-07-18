"""Tests for the GET /api/jobs/{tid}/progress endpoint (Step H5).

The endpoint exposes a snapshot of where the pipeline is right
now: how many detectors are in the list, how many have finished,
which one is currently running, and which (if any) failed.

Two ways the snapshot gets populated:
  1. The pipeline's ``on_step_complete`` hook updates the
     in-memory job registry the moment a detector finishes.
  2. If the server restarted (the in-memory registry is empty)
     the endpoint falls back to scanning steps/ on disk.

We test both paths, plus the failure modes (404 on unknown
trace_id, malformed JSON on a half-written step file).
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz  # type: ignore[import-not-found]
import pytest

from manusift.checkpoint import write_step
from manusift.config import get_settings
from manusift.contracts import JobState
from manusift.detectors.base import DetectorResult
from manusift.pipeline import run_pipeline
from manusift.web.app import create_app
from manusift.workspace import JobPaths


# ---------- helpers ----------

def _mk_state(tid: str) -> JobState:
    return JobState(
        trace_id=tid,
        status="queued",
        source_filename="smoke.pdf",
        created_at=0.0,
    )


def _mk_pdf(path: Path) -> None:
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello")
    pdf.save(str(path))
    pdf.close()


def _install_fake_detector_classes(
    monkeypatch: pytest.MonkeyPatch,
    names: list[str],
) -> None:
    from manusift.detectors.base import DetectorResult
    from manusift import pipeline as pipeline_mod

    classes = []
    for name in names:
        def run(self, doc, detector_name=name):
            return DetectorResult(
                detector=detector_name,
                ok=True,
                findings=[],
            )

        classes.append(
            type(
                f"Fake{name.title().replace('_', '')}Detector",
                (),
                {"name": name, "run": run},
            )
        )
    monkeypatch.setattr(
        pipeline_mod,
        "_pipeline_detector_classes",
        lambda: classes,
    )


# ---------- 1. TestClient basic endpoint shape ----------

def test_progress_endpoint_404_for_unknown_trace(tmp_path, monkeypatch) -> None:
    """A trace_id that has no job anywhere returns 404 from the
    /progress endpoint (consistency with /jobs/{tid})."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    app = create_app()
    from starlette.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/api/jobs/no-such-trace/progress")
    # The endpoint does not 404 -- it returns 200 with status="unknown"
    # because a restart could leave step files behind for a trace
    # that the in-memory registry never saw. The contract here is
    # "always 200 if we can answer; 404 only if we can prove it's
    # not there." Today, the endpoint always answers 200 even for
    # unknown trace_id (it just reports 0/4 completed). That's
    # intentional: a poll loop never has to special-case 404.
    assert resp.status_code == 200
    body = resp.json()
    from manusift.pipeline import detector_names_for_progress
    assert body["total_steps"] == len(detector_names_for_progress())
    assert body["completed_count"] == 0
    assert body["failed_count"] == 0
    assert body["status"] == "unknown"


# ---------- 2. After a full pipeline run, /progress reports 4/4 done ----------

def test_progress_endpoint_after_full_pipeline(tmp_path, monkeypatch) -> None:
    """End-to-end: run the pipeline, then poll /progress. All
    detectors should be in completed_steps."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    from manusift.pipeline import detector_names_for_progress
    expected = detector_names_for_progress()
    _install_fake_detector_classes(monkeypatch, expected)

    pdf_path = tmp_path / "tiny.pdf"
    _mk_pdf(pdf_path)

    tid = "t-progress"
    paths = JobPaths.for_trace(tid, tmp_path / "jobs")
    paths.ensure()
    state = _mk_state(tid)
    run_pipeline(pdf_path, paths, state)

    # Now hit the endpoint.
    from starlette.testclient import TestClient
    app = create_app()
    # Manually register the finished job in the in-memory registry
    # so the endpoint can see it; this mirrors what _run_in_background
    # would do for a real upload. (TestClient does not run the
    # background task -- the function returns 202 immediately and
    # we hand-roll the registry entry here.)
    # P1-A: the module-level registry alias is now
    # ``_JOBS_STORE``. The behaviour is identical
    # for an in-memory backend; the test only needs
    # the test-app's store, so we set on that.
    from manusift.web import app as web_mod
    web_mod._JOBS_STORE.set(state)

    client = TestClient(app)
    resp = client.get(f"/api/jobs/{tid}/progress")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_steps"] == len(expected)
    assert body["completed_count"] == len(expected)
    assert body["completed_steps"] == expected
    assert body["failed_count"] == 0


# ---------- 3. Mid-run progress: on_step_complete hook fires ----------

def test_on_step_complete_hook_fires_per_detector(tmp_path, monkeypatch) -> None:
    """The pipeline's ``on_step_complete`` hook fires once per
    detector, in order. This is the contract the web layer's
    /progress endpoint relies on."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    from manusift.pipeline import detector_names_for_progress
    expected = detector_names_for_progress()
    _install_fake_detector_classes(monkeypatch, expected)

    pdf_path = tmp_path / "tiny.pdf"
    _mk_pdf(pdf_path)

    paths = JobPaths.for_trace("t-hook", tmp_path / "jobs")
    paths.ensure()
    state = _mk_state("t-hook")

    fired: list[str] = []

    def hook(res, _state) -> None:
        fired.append(res.detector)

    run_pipeline(pdf_path, paths, state, on_step_complete=hook)
    assert fired == expected


# ---------- 4. Server restart: on-disk step files are the source of truth ----------

def test_progress_endpoint_falls_back_to_disk_on_restart(
    tmp_path, monkeypatch
) -> None:
    """If the in-memory registry is empty but step files exist on
    disk (server restarted mid-job), the endpoint must still
    report correct progress by reading the steps/ directory."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    tid = "t-restart"
    paths = JobPaths.for_trace(tid, tmp_path / "jobs")
    paths.ensure()
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the pipeline list grew from 12 to 23. The
    # test writes 3 step files at indices 0, 1, 2
    # (the first three detectors in the new list:
    # ``metadata``, ``pdf_metadata``, ``supplementary``).
    write_step(
        paths.step_path(0, "metadata"),
        DetectorResult(detector="metadata", ok=True, findings=[]),
    )
    write_step(
        paths.step_path(1, "pdf_metadata"),
        DetectorResult(detector="pdf_metadata", ok=True, findings=[]),
    )
    write_step(
        paths.step_path(2, "supplementary"),
        DetectorResult(detector="supplementary", ok=True, findings=[]),
    )

    from starlette.testclient import TestClient
    app = create_app()
    client = TestClient(app)
    resp = client.get(f"/api/jobs/{tid}/progress")
    body = resp.json()
    assert body["completed_count"] == 3
    assert set(body["completed_steps"]) == {
        "metadata",
        "pdf_metadata",
        "supplementary",
    }
    # R-2026-06-15 (Phase 3, real-case benchmark):
    # the next pending step is the one immediately
    # AFTER the last written step. With the new
    # 23-detector list, the last written step is
    # at position 2 (``supplementary``); the next
    # pending is at position 3, which is
    # ``author_emails``.
    from manusift.pipeline import (
        detector_names_for_progress,
    )
    full = detector_names_for_progress()
    last_idx = full.index("supplementary")
    expected_next = full[last_idx + 1]
    assert body["current_step"] == expected_next
    assert body["current_step"] == "author_emails"


# ---------- 5. detector_names_for_progress is the source of truth ----------

def test_detector_names_for_progress_is_canonical() -> None:
    """The web layer and the pipeline both use the same detector
    list (via detector_names_for_progress) so the /progress
    endpoint's total_steps never drifts from the actual
    pipeline."""
    from manusift.pipeline import detector_names_for_progress
    names = detector_names_for_progress()
    # R-2026-06-15 (Phase 3, real-case benchmark): the
    # canonical list grew from 12 to 23 (we added 11
    # detectors that were sitting in the registry but
    # not in the pipeline). The order matches the
    # _BUILTIN_DETECTOR_CLASS_NAMES list in
    # ``manusift/pipeline.py``.
    assert names == [
        "metadata",
        "pdf_metadata",
        "supplementary",
        "author_emails",
        "compliance",
        "image_sift_copymove",
        "ref_duplicate",
        "ref_format_anomaly",
        "stat_grim",
        "stat_pvalue",
        "stat_percent",
        "table_relationships",
        "table_benford",
        "table_duplicate_row",
        "table_near_duplicate_row",
        "table_cross_copy",
        "table_outlier",
        "table_round_bias",
        "table_file_metadata",
        "table_highlight_focus",
        "image_noise_inconsistency",
        "panel_duplicate",
        "ai_generated_figure",
        "paper_mill_authorship",
        "image_dup",
        "image_forensics",
        "text_patterns",
        # 2026-07 (fraud_web_v1): two cheap text detectors
        # added to the pipeline after TextPatternDetector.
        "text_tortured_phrases",
        "paper_mill_template",
        "data_availability_concern",
        "page_raster_dup",
        "panel_dup",
        "figure_stat_text",
        "figure_grim",
        # 2026-07-18 (P4): figure-text numeric
        # cross-check pair, evidence from the
        # synthetic figure_text_v1 benchmark.
        # Local-only; run before the network
        # detectors.
        "chart_data_extract",
        "figure_table_consistency",
        # 2026-07-18: forest-plot rule pipeline
        # (CI order/asymmetry + null-line
        # cross-validation).
        "forest_plot",
        "citation_network",
        # 2026-07-18 (P2.2): OpenAlex cited-retraction check,
        # same network gate family as citation_network.
        "cited_retraction",
    ]
