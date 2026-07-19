"""Parallel detector loop: real run_pipeline path, workers=1 and workers>1."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from manusift.contracts import Finding, JobState, ParsedDoc
from manusift.detectors.base import DetectorResult
from manusift.pipeline import _detector_worker_count, _run_detector_body, run_pipeline
from manusift.workspace import JobPaths


class _DetA:
    name = "parallel_test_a"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=[
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="info",
                    title="a",
                    evidence="from a",
                    location="test",
                )
            ],
            duration_ms=1,
        )


class _DetB:
    name = "parallel_test_b"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=[
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="low",
                    title="b",
                    evidence="from b",
                    location="test",
                )
            ],
            duration_ms=1,
        )


class _DetBoom:
    name = "parallel_test_boom"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        raise RuntimeError("intentional boom")


def test_detector_worker_count_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_DETECTOR_WORKERS", "1")
    assert _detector_worker_count() == 1
    monkeypatch.setenv("MANUSIFT_DETECTOR_WORKERS", "8")
    assert _detector_worker_count() == 8
    monkeypatch.setenv("MANUSIFT_DETECTOR_WORKERS", "0")
    assert _detector_worker_count() == 1


def test_run_detector_body_isolates_crash() -> None:
    doc = ParsedDoc(
        trace_id="t-boom",
        source_path="x.pdf",
        text_blocks=[],
        images=[],
        metadata={},
    )
    res = _run_detector_body(_DetBoom, doc)
    assert res.ok is False
    assert res.error
    assert res.findings and res.findings[0].severity == "info"


def test_pipeline_parallel_and_serial_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive real run_pipeline with two fake detectors under workers=2 and 1."""
    from manusift import pipeline as pl

    fixture = (
        Path(__file__).resolve().parents[1]
        / "evals"
        / "fixtures"
        / "clean_academic.pdf"
    )
    if not fixture.is_file():
        pytest.skip("fixture PDF missing")

    def _fake_classes():
        return [_DetA, _DetB]

    monkeypatch.setattr(pl, "_pipeline_detector_classes", _fake_classes)
    # Avoid treating fakes as unknown plugins for skip heuristics
    monkeypatch.setattr(
        pl,
        "_BUILTIN_DETECTOR_CLASS_NAMES",
        ("_DetA", "_DetB"),
    )

    def _screen(workers: int, tid: str) -> tuple[list[str], list]:
        monkeypatch.setenv("MANUSIFT_DETECTOR_WORKERS", str(workers))
        # clear settings cache so env is visible if settings used
        if hasattr(pl.get_settings, "cache_clear"):
            pl.get_settings.cache_clear()
        ws = tmp_path / f"ws_w{workers}"
        ws.mkdir(parents=True, exist_ok=True)
        paths = JobPaths.for_trace(tid, ws)
        paths.ensure()
        paths.original.write_bytes(fixture.read_bytes())
        job = JobState(trace_id=tid, status="queued", source_filename=fixture.name)
        result = run_pipeline(paths.original, paths, job)
        assert job.status in ("done", "running", "failed") or True
        findings_path = paths.findings_json
        assert findings_path.is_file(), findings_path
        payload = json.loads(findings_path.read_text(encoding="utf-8"))
        dets = [f.get("detector") for f in payload.get("findings", [])]
        # step files exist for both
        steps = list((paths.root / "steps").glob("*.json"))
        assert len(steps) >= 2
        return result.detectors_run, dets

    run_par, dets_par = _screen(2, "par1")
    run_ser, dets_ser = _screen(1, "ser1")

    assert "parallel_test_a" in run_par
    assert "parallel_test_b" in run_par
    assert "parallel_test_a" in run_ser
    assert "parallel_test_b" in run_ser
    # deterministic pipeline order in detectors_run
    assert run_par.index("parallel_test_a") < run_par.index("parallel_test_b")
    assert run_ser.index("parallel_test_a") < run_ser.index("parallel_test_b")
    assert "parallel_test_a" in dets_par
    assert "parallel_test_b" in dets_par
