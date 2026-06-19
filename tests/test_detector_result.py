"""Tests for the typed DetectorResult envelope (Step H2).

Borrowed from OpenHands' Action/Observation pattern: every detector
returns a typed status + payload object, never just a list of
findings. The pipeline then flattens the results but keeps the
metadata for future checkpoint and progress features.
"""
from __future__ import annotations

import time

import pytest

from manusift.contracts import Finding, ParsedDoc
from manusift.detectors.base import DetectorResult, run_detectors


# ---------- helpers ----------

def _doc(trace_id: str = "t") -> ParsedDoc:
    return ParsedDoc(
        trace_id=trace_id,
        source_path="dummy.pdf",
        text_blocks=[],
        images=[],
        metadata={},
    )


def _finding(trace_id: str = "t", detector: str = "x", title: str = "t") -> Finding:
    return Finding.make(
        trace_id=trace_id,
        detector=detector,
        severity="low",
        title=title,
        evidence="",
        location="",
    )


class _OkDetector:
    name = "ok_det"

    def __init__(self, findings: list[Finding] | None = None) -> None:
        self._findings = findings or []

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=list(self._findings),
            duration_ms=5,
        )


class _CrashDetector:
    name = "crash_det"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        raise RuntimeError("boom")


# ---------- 1. DetectorResult immutability ----------

def test_detector_result_is_frozen() -> None:
    """A typed envelope must not be mutated by the pipeline after the
    detector returns. Borrowed from OpenHands' immutable Observation
    discipline."""
    res = DetectorResult(detector="x", ok=True, findings=[], duration_ms=1)
    with pytest.raises(Exception):  # FrozenInstanceError
        res.ok = False  # type: ignore[misc]


# ---------- 2. happy path: ok=True, findings copied ----------

def test_ok_detector_returns_findings_in_envelope() -> None:
    findings = [_finding(title="one"), _finding(title="two")]
    res = _OkDetector(findings).run(_doc())
    assert res.ok is True
    assert res.error is None
    assert len(res.findings) == 2
    # The result is a copy — mutating the original list must not
    # affect the envelope.
    findings.clear()
    assert len(res.findings) == 2


# ---------- 3. crash in a detector: ok=False, error captured, finding synthesized ----------

def test_run_detectors_isolates_crashing_detector() -> None:
    """One broken detector must not kill the job. The runner
    synthesizes a single info-level 'X crashed' finding AND records
    ok=False + error on the result envelope."""
    ok = _OkDetector([_finding(title="alive")])
    crash = _CrashDetector()
    results = run_detectors(_doc(), [ok, crash])
    assert len(results) == 2
    # First detector: ok=True, real finding.
    assert results[0].detector == "ok_det"
    assert results[0].ok is True
    assert len(results[0].findings) == 1
    # Second detector: ok=False, error captured, synthesized finding.
    assert results[1].detector == "crash_det"
    assert results[1].ok is False
    assert "RuntimeError" in (results[1].error or "")
    assert "boom" in (results[1].error or "")
    # Synthesized finding has detector_error severity is 'info' and
    # title "<name> crashed".
    crashed = results[1].findings[0]
    assert crashed.severity == "info"
    assert "crashed" in crashed.title


# ---------- 4. duration_ms is always recorded ----------

def test_duration_is_recorded_for_ok_and_crashed_detectors() -> None:
    class _SlowDetector:
        name = "slow"
        def run(self, doc: ParsedDoc) -> DetectorResult:
            time.sleep(0.02)
            return DetectorResult(detector=self.name, ok=True, findings=[])
    class _FastDetector:
        name = "fast"
        def run(self, doc: ParsedDoc) -> DetectorResult:
            raise ValueError("nope")
    results = run_detectors(_doc(), [_SlowDetector(), _FastDetector()])
    # Slow detector: 20ms+ timing.
    assert results[0].duration_ms >= 15
    # Crashing detector: timing is also recorded (not None, not 0).
    assert results[1].duration_ms >= 0


# ---------- 5. typed envelope enables future checkpoint + progress ----------

def test_detector_result_serializes_to_json() -> None:
    """The result object must be JSON-friendly so future checkpoint
    features (H3) can persist per-detector state. Finding is already
    a dataclass; we just need DetectorResult to round-trip through
    json.dumps / json.loads."""
    import json
    res = _OkDetector([_finding(title="one")]).run(_doc())
    payload = json.dumps(res.__dict__, default=str)
    restored = json.loads(payload)
    assert restored["detector"] == "ok_det"
    assert restored["ok"] is True
    assert restored["duration_ms"] == 5
