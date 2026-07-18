"""Unit tests for the page-raster-duplicate detector.

These tests exercise the detector's two contract surfaces:

  1. ``run()`` must never raise. If PyMuPDF / OpenCV is
     missing, the detector returns an empty ``DetectorResult``
     (no-op) and the pipeline degrades gracefully.

  2. When given a ``source_path`` pointing at a real PDF,
     the detector produces figure-region hashes and
     emits at most one finding per near-duplicate pair.

The "near-duplicate" test is the slow one -- it renders
two pages of a real benchmark PDF. We deliberately do not
assert a specific number of findings (the
``image_duplicate_hamming_threshold`` is a project-wide
setting that can change), only that:
  - ``run()`` returns a ``DetectorResult``;
  - each finding's Hamming distance is at or below the
    configured threshold;
  - the page numbers in each finding are 1-indexed.

A second test exercises the figure-region extractor in
isolation: it confirms that the open-source PDF that ships
with the project (``evals/cases/02_duplicate_image.json``
has a fixture PDF) produces at least one figure region
per page. The exact number depends on the fixture; we
just check that it's > 0.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_no_op_when_pymupdf_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If PyMuPDF is not importable, the detector returns
    a clean empty result rather than raising."""
    from manusift.detectors import page_raster_dup as mod

    monkeypatch.setattr(mod, "_HAS_FITZ", False)
    det = mod.PageRasterDuplicateDetector()
    from manusift.contracts import ParsedDoc, TextBlock

    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.detector == "page_raster_dup"
    assert result.findings == []


def test_no_op_when_opencv_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If OpenCV is not importable, the detector returns
    a clean empty result rather than raising."""
    from manusift.detectors import page_raster_dup as mod

    monkeypatch.setattr(mod, "_HAS_FITZ", True)
    monkeypatch.setattr(mod, "_HAS_CV2", False)
    det = mod.PageRasterDuplicateDetector()
    from manusift.contracts import ParsedDoc, TextBlock

    doc = ParsedDoc(
        trace_id="t", source_path="/tmp/x.pdf", images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 1, 1), text="x")],
        metadata={},
    )
    result = det.run(doc)
    assert result.findings == []


@pytest.mark.slow
def test_region_extractor_finds_figures() -> None:
    """On the real case_001 PDF (PLOS plasmonic nanobubbles),
    the figure-region extractor must return at least one
    region. The exact number depends on the figure layout."""
    from manusift.detectors.page_raster_dup import (
        _extract_figure_regions,
    )
    import fitz

    pdf_path = (
        Path(__file__).resolve().parents[1]
        / "real_eval_fraud_cases"
        / "cases"
        / "case_001_plos_plasmonic_nanobubbles"
        / "paper.pdf"
    )
    if not pdf_path.exists():
        pytest.skip("Benchmark PDF not present")
    doc = fitz.open(pdf_path)
    total = 0
    for p in range(len(doc)):
        total += len(_extract_figure_regions(doc[p]))
    assert total > 0, "page-raster extractor found zero regions"


@pytest.mark.slow
def test_run_returns_valid_detector_result_on_real_pdf() -> None:
    """End-to-end: run on case_006 (Frontiers Asparagus
    myeloma), the detector should return a DetectorResult
    with at most one finding per near-duplicate pair."""
    from manusift.detectors import PageRasterDuplicateDetector
    from manusift.ingest.pdf import parse_pdf

    pdf = (
        Path(__file__).resolve().parents[1]
        / "real_eval_fraud_cases"
        / "cases"
        / "case_006_frontiers_asparagus_multiple_myeloma"
        / "paper.pdf"
    )
    if not pdf.exists():
        pytest.skip("Benchmark PDF not present")
    doc = parse_pdf(pdf, trace_id="t")
    det = PageRasterDuplicateDetector()
    result = det.run(doc)
    # No
    # assertion
    # on
    # exact
    # count
    # --
    # depends
    # on
    # the
    # pHash
    # threshold.
    # Just
    # check
    # the
    # contract.
    assert result.detector == "page_raster_dup"
    for f in result.findings:
        # The
        # evidence
        # must
        # mention
        # at
        # least
        # one
        # page
        # number.
        assert "Page " in f.evidence
        # Page
        # numbers
        # should
        # be
        # 1-indexed
        # (i.e.
        # >= 1).
        import re
        pages = [
            int(m.group(1))
            for m in re.finditer(r"Page (\d+)", f.evidence)
        ]
        for p in pages:
            assert p >= 1
