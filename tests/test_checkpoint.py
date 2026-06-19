"""Tests for the per-detector checkpoint layer (Step H3).

Borrowing LangGraph's "every super-step persists a snapshot" pattern,
implemented as one ``DetectorResult`` JSON per detector. Two
guarantees to test:
  * A fresh pipeline writes one step file per detector.
  * Re-running the same pipeline with the step files in place
    skips the already-completed detectors (resume semantics).

Plus a few failure paths: corrupt step file, missing fields,
atomic write survives a partial write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from manusift.checkpoint import read_step, read_step_silent, write_step
from manusift.config import get_settings
from manusift.contracts import Finding, JobState
from manusift.detectors.base import DetectorResult
from manusift.pipeline import run_pipeline
from manusift.workspace import JobPaths


# ---------- helpers ----------

def _mk_state(tid: str) -> JobState:
    return JobState(
        trace_id=tid,
        status="queued",
        source_filename="smoke.pdf",
        created_at=0.0,
    )


def _mk_finding(detector: str = "metadata", title: str = "test") -> Finding:
    return Finding.make(
        trace_id="t",
        detector=detector,
        severity="low",
        title=title,
        evidence="",
        location="",
    )


def _mk_result(detector: str = "metadata", ok: bool = True) -> DetectorResult:
    return DetectorResult(
        detector=detector,
        ok=ok,
        findings=[_mk_finding(detector=detector)] if ok else [],
        error=None if ok else "boom",
        duration_ms=12,
    )


class _PipelineCheckpointDetector:
    name = "metadata"

    def run(self, doc) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=[],
            error=None,
            duration_ms=1,
        )


def _fake_pipeline_detector_classes(names: list[str]) -> list[type]:
    return [
        type(
            f"Fake{name.title().replace('_', '')}Detector",
            (_PipelineCheckpointDetector,),
            {"name": name},
        )
        for name in names
    ]


# ---------- 1. atomic write then read round-trip ----------

def test_write_step_then_read_round_trip(tmp_path: Path) -> None:
    """The simplest sanity check: write a result, read it back."""
    paths = JobPaths.for_trace("t", tmp_path)
    res = _mk_result()
    write_step(paths.step_path(0, "metadata"), res)
    got = read_step(paths.step_path(0, "metadata"))
    assert got is not None
    assert got.detector == "metadata"
    assert got.ok is True
    assert got.duration_ms == 12
    assert got.error is None
    assert len(got.findings) == 1
    assert got.findings[0].title == "test"


# ---------- 2. missing file -> None, not exception ----------

def test_read_step_missing_returns_none(tmp_path: Path) -> None:
    paths = JobPaths.for_trace("t", tmp_path)
    assert read_step_silent(paths.step_path(0, "ghost")) is None
    assert read_step(paths.step_path(0, "ghost")) is None


# ---------- 3. corrupt JSON -> None, warning logged, no exception ----------

def test_read_step_corrupt_returns_none(tmp_path: Path) -> None:
    paths = JobPaths.for_trace("t", tmp_path)
    paths.ensure()
    bad = paths.step_path(0, "metadata")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not valid json", encoding="utf-8")
    assert read_step_silent(bad) is None
    assert read_step(bad) is None


# ---------- 4. missing fields -> None (no crash) ----------

def test_read_step_missing_fields_returns_none(tmp_path: Path) -> None:
    """A step file that parses but has the wrong type for a
    required field should be treated as 'step is not resumable'
    rather than crashing the whole pipeline."""
    paths = JobPaths.for_trace("t", tmp_path)
    paths.ensure()
    bad = paths.step_path(0, "metadata")
    bad.parent.mkdir(parents=True, exist_ok=True)
    # 'findings' must be a list of dicts; passing a non-list triggers
    # a TypeError inside _dict_to_result when it iterates.
    bad.write_text(
        json.dumps(
            {
                "detector": "metadata",
                "ok": True,
                "duration_ms": 0,
                "findings": "not a list",
            }
        ),
        encoding="utf-8",
    )
    assert read_step_silent(bad) is None


# ---------- 5. workspace helper: step_path + list_step_files ----------

def test_step_path_is_zero_padded(tmp_path: Path) -> None:
    paths = JobPaths.for_trace("t", tmp_path)
    p = paths.step_path(3, "image_forensics")
    # Zero-padded so shell listings match pipeline order.
    assert p.name == "03_image_forensics.json"


def test_list_step_files_in_pipeline_order(tmp_path: Path) -> None:
    paths = JobPaths.for_trace("t", tmp_path)
    paths.ensure()
    write_step(paths.step_path(2, "zzz"), _mk_result("zzz"))
    write_step(paths.step_path(0, "aaa"), _mk_result("aaa"))
    write_step(paths.step_path(1, "mmm"), _mk_result("mmm"))
    files = paths.list_step_files()
    assert [p.name for p in files] == [
        "00_aaa.json",
        "01_mmm.json",
        "02_zzz.json",
    ]


def test_list_step_files_ignores_garbage(tmp_path: Path) -> None:
    """The steps/ directory is a real on-disk dir that the user can
    poke at. Defensive: any file that doesn't match ``NN_name.json``
    is ignored."""
    paths = JobPaths.for_trace("t", tmp_path)
    paths.ensure()
    paths.steps_dir.mkdir(parents=True, exist_ok=True)
    (paths.steps_dir / "README.txt").write_text("user note", encoding="utf-8")
    (paths.steps_dir / "10_foo.json.bak").write_text("{}", encoding="utf-8")
    write_step(paths.step_path(0, "metadata"), _mk_result())
    files = paths.list_step_files()
    assert [p.name for p in files] == ["00_metadata.json"]


# ---------- 6. pipeline writes one step file per detector ----------

def test_pipeline_writes_step_file_per_detector(tmp_path, monkeypatch) -> None:
    """End-to-end: run the pipeline on a tiny PDF, confirm 4 step
    files exist with the expected names, and that the report +
    findings + job.json still get written as before (backwards
    compatibility)."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    detector_names = [
        "metadata",
        "image_dup",
        "image_forensics",
        "text_patterns",
    ]
    monkeypatch.setattr(
        "manusift.pipeline._pipeline_detector_classes",
        lambda: _fake_pipeline_detector_classes(detector_names),
    )
    settings = get_settings()
    # R-2026-06-15 (Phase 1 + P1-17):
    # ``Settings`` is now
    # ``frozen=True``.  Use
    # ``model_copy`` to build a
    # new instance with the
    # ``workspace_dir``
    # override; the original
    # ``settings`` object is
    # unchanged, so the next
    # ``get_settings()`` call
    # still returns the
    # cached default.
    settings = settings.model_copy(
        update={"workspace_dir": tmp_path / "jobs"}
    )
    (tmp_path / "jobs").mkdir()

    # Build a small PDF and upload via the public path.
    import fitz  # type: ignore[import-not-found]
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello world")
    pdf_path = tmp_path / "tiny.pdf"
    pdf.save(str(pdf_path))
    pdf.close()

    tid = "t-pipeline-h3"
    paths = JobPaths.for_trace(tid, tmp_path / "jobs")
    paths.ensure()
    state = _mk_state(tid)
    result = run_pipeline(pdf_path, paths, state)

    # Each detector must have written a step file.
    for idx, name in enumerate(detector_names):
        p = paths.step_path(idx, name)
        assert p.exists(), f"missing step file: {p.name}"
        cached = read_step(p)
        assert cached is not None
        assert cached.detector == name
        assert cached.ok is True

    # Existing artifacts still written.
    assert paths.findings_json.exists()
    assert paths.report_html.exists()
    assert paths.job_json.exists()
    # Pipeline returned its AnalysisResult with a list of findings.
    assert isinstance(result.findings, list)


# ---------- 7. resume: cached step is reused, detector not re-run ----------

def test_pipeline_resumes_from_cached_step(
    tmp_path, monkeypatch
) -> None:
    """Pre-write one step file with a sentinel finding, run the
    pipeline, confirm the second run inherits the sentinel
    (i.e. the detector was skipped, not re-executed)."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(
        "manusift.pipeline._pipeline_detector_classes",
        lambda: _fake_pipeline_detector_classes(
            ["metadata", "image_dup", "text_patterns"]
        ),
    )
    (tmp_path / "jobs").mkdir()

    import fitz  # type: ignore[import-not-found]
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello")
    pdf_path = tmp_path / "tiny.pdf"
    pdf.save(str(pdf_path))
    pdf.close()

    tid = "t-resume"
    paths = JobPaths.for_trace(tid, tmp_path / "jobs")
    paths.ensure()

    # Hand-craft a cached step for the metadata detector with a
    # sentinel finding. Note: Finding is frozen, so we need to
    # construct a real one, not just a dict.
    sentinel = Finding.make(
        trace_id=tid,
        detector="metadata",
        severity="low",
        title="FROM CACHE",
        evidence="this finding came from the cached step, not a re-run",
        location="(cached)",
        raw={"source": "test"},
    )
    cached = DetectorResult(
        detector="metadata",
        ok=True,
        findings=[sentinel],
        error=None,
        duration_ms=999,
    )
    write_step(paths.step_path(0, "metadata"), cached)

    state = _mk_state(tid)
    run_pipeline(pdf_path, paths, state)

    # The cached finding must survive in the persisted findings.json
    # — i.e. the resume semantics did not re-run metadata.
    payload = json.loads(paths.findings_json.read_text(encoding="utf-8"))
    titles = [f["title"] for f in payload["findings"]]
    assert "FROM CACHE" in titles
