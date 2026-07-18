"""Unit tests for the figure-body stat-text detector.

The detector is a *read-only* OCR pass over figure
regions. The tests cover:

  1. The no-op case when PyMuPDF / EasyOCR is missing.
  2. The ``_looks_like_stat`` filter (no PDF needed).
  3. The end-to-end run on a real PDF (case_004).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_no_op_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.detectors import figure_stat_text as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", False)
    det = mod.FigureStatTextDetector()
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
    from manusift.detectors import figure_stat_text as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", True)
    monkeypatch.setattr(mod, "_HAS_EASYOCR", False)
    det = mod.FigureStatTextDetector()
    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


def test_looks_like_stat_filters_correctly() -> None:
    """The stat-like-text filter must accept n=, p<0.05,
    mean+/-SD, and reject ordinary prose."""
    from manusift.detectors.figure_stat_text import _looks_like_stat

    positives = [
        "n=8",
        "N=12",
        "n = 6",
        "p<0.05",
        "p < 0.01",
        "P = 0.04",
        "95%",
        "7.9%",
        "0.3%",
        "***",
    ]
    for s in positives:
        assert _looks_like_stat(s), f"should accept: {s!r}"

    negatives = [
        "This is a paper about stem cells.",
        "Authors declare no conflict.",
        "Figure 1",
        "Western blot analysis showed...",
    ]
    for s in negatives:
        assert not _looks_like_stat(s), f"should reject: {s!r}"


@pytest.mark.slow
@pytest.mark.real_ocr
def test_run_on_real_case_004() -> None:
    """End-to-end: run on case_004 (PLOS trophoblast
    stem cells) which has many percentage labels in
    its figures. The detector should return a valid
    DetectorResult; we don't pin the exact count
    because EasyOCR is non-deterministic across
    runs."""
    from manusift.detectors import FigureStatTextDetector
    from manusift.ingest.pdf import parse_pdf

    pdf = (
        Path(__file__).resolve().parents[1]
        / "real_eval_fraud_cases"
        / "cases"
        / "case_004_plos_trophoblastic_stem_cells_parkinsonian_rats"
        / "paper.pdf"
    )
    if not pdf.exists():
        pytest.skip("Benchmark PDF not present")
    doc = parse_pdf(pdf, trace_id="t")
    det = FigureStatTextDetector()
    result = det.run(doc)
    assert result.detector == "figure_stat_text"
    for f in result.findings:
        # Page
        # numbers
        # are
        # 1-indexed.
        assert "Page " in f.evidence
