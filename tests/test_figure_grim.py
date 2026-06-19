"""Unit tests for the figure-body GRIM consistency detector.

The detector combines EasyOCR (slow) with a pure-Python
GRIM test (fast). The tests use a mock reader so they
do not need to OCR anything -- we just feed fake
"recognised text" + confidences through the detector's
internal pipeline.

Coverage:

  1. ``_grim_check`` correctly accepts / rejects known
     percentages.
  2. ``_PCT_PATTERN`` correctly extracts percentages.
  3. The detector returns a valid ``DetectorResult`` on
     a real PDF (case_004 -- the target case).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_grim_check_accepts_consistent_percentages() -> None:
    """Known-consistent percentages must NOT trigger."""
    from manusift.detectors.figure_grim import _grim_check

    # 95%
    # of
    # 20
    # samples
    # is
    # 19
    # --
    # an
    # integer.
    assert _grim_check(95.0, 20, range(3, 101)) is None
    # 50%
    # of
    # 10
    # is
    # 5.
    assert _grim_check(50.0, 10, range(3, 101)) is None
    # 7.5%
    # of
    # 40
    # is
    # 3.0.
    assert _grim_check(7.5, 40, range(3, 101)) is None
    # 100%
    # of
    # 20
    # is
    # 20.
    assert _grim_check(100.0, 20, range(3, 101)) is None


def test_grim_check_rejects_inconsistent_percentages() -> None:
    """Known-inconsistent percentages must trigger."""
    from manusift.detectors.figure_grim import _grim_check

    # 7.9%
    # of
    # 20
    # is
    # 1.58
    # --
    # not
    # an
    # integer.
    n, count = _grim_check(7.9, 20, range(3, 101))
    assert n == 20
    assert abs(count - 1.58) < 0.01


def test_grim_check_sweep_without_n() -> None:
    """When n is None, the detector sweeps a range
    and reports the first N that fails."""
    from manusift.detectors.figure_grim import _grim_check

    # 7.9%
    # cannot
    # be
    # reconciled
    # with
    # any
    # N
    # in
    # [3, 100]
    # because
    # 0.079*N
    # is
    # never
    # an
    # integer
    # for
    # small
    # N.
    n, _count = _grim_check(7.9, None, range(3, 101))
    assert n is not None


def test_pct_pattern_extracts_correctly() -> None:
    """``_PCT_PATTERN`` must extract the percentage
    strings the detector cares about.

    R-2026-06-12: the pattern was relaxed to also
    accept integer percentages ("50%", "100%")
    because Frontiers papers use those in figure
    axes much more often than decimal percentages."""
    from manusift.detectors.figure_grim import _PCT_PATTERN

    text = "95.0% and 7.9% and 100% and 1.5% and 50%"
    matches = _PCT_PATTERN.findall(text)
    assert "95.0" in matches
    assert "7.9" in matches
    assert "100" in matches  # integer -- now accepted
    assert "1.5" in matches
    assert "50" in matches


def test_no_op_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.detectors import figure_grim as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", False)
    det = mod.FigureGRIMDetector()
    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


def test_no_op_when_easyocr_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.detectors import figure_grim as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", True)
    monkeypatch.setattr(mod, "_HAS_EASYOCR", False)
    det = mod.FigureGRIMDetector()
    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


@pytest.mark.slow
@pytest.mark.real_ocr
def test_run_on_real_case_004() -> None:
    """End-to-end: run on case_004 (PLOS trophoblast
    stem cells) which has many percentage labels in
    its figures. The detector should return a valid
    DetectorResult; we don't pin the count because
    EasyOCR is non-deterministic."""
    from manusift.detectors import FigureGRIMDetector
    from manusift.ingest.pdf import parse_pdf

    pdf = Path(r"C:\Users\22509\Desktop\ManuSift1\real_eval_fraud_cases\cases\case_004_plos_trophoblastic_stem_cells_parkinsonian_rats\paper.pdf")
    if not pdf.exists():
        pytest.skip("Benchmark PDF not present")
    doc = parse_pdf(pdf, trace_id="t")
    det = FigureGRIMDetector()
    result = det.run(doc)
    assert result.detector == "figure_grim"
