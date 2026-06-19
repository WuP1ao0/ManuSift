"""Regression tests for the alignment classification heuristics
in ``real_eval_fraud_cases_v2/scripts/build_alignment.py``.

Why this test exists:
  - The v1 build_alignment.py got to 100% coverage on the v1 10-case
    benchmark after several iterations (v9 added the smart
    figure-label-to-page matching).
  - The v2 alignment adds two new heuristics:
    1. Article-level targets with ``testable_from_public_materials=False``
       are forced to ``not_testable`` (case_011 / case_032 type).
    2. Article-level targets whose PDF exposes <= 1 image but whose
       expected category is image-only are forced to ``not_testable``
       rather than ``missed`` (case_059 type -- a paper that lost its
       figures to compression can still be retracted for image issues
       that we cannot see).
  - These tests pin both heuristics so future alignment changes cannot
    regress to the v1 behaviour where case_059 would be marked
    ``missed``.

Run with:
  .venv/Scripts/python.exe -m pytest tests/test_v2_alignment.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import sys

import pytest


REPO = Path(r"C:\Users\22509\Desktop\ManuSift1").resolve()
SCRIPTS = REPO / "real_eval_fraud_cases_v2" / "scripts"
BASE = REPO / "real_eval_fraud_cases_v2" / "cases"


@pytest.fixture(scope="module")
def alignment_module():
    sys.path.insert(0, str(SCRIPTS))
    import build_alignment  # type: ignore[import-not-found]
    return build_alignment


def _make_target(
    location: str = "all figures",
    description: str = "Concerns about image duplication",
    testable: bool = True,
) -> dict[str, Any]:
    return {
        "type": "article",
        "location": location,
        "description": description,
        "evidence_source": "retraction notice",
        "severity": "high",
        "testable_from_public_materials": testable,
        "limitations": [],
        "expected_evidence_type": "image_similarity",
    }


def _build(alignment_module, case_dir: Path) -> dict[str, Any]:
    return alignment_module.build_alignment(case_dir)


def test_case_011_is_not_testable(alignment_module) -> None:
    """AI-generated-figures case: testable=False in gold -> not_testable."""
    case_dir = BASE / "case_011_fcell_jak_stat_sscs"
    if not (case_dir / "manusift_run" / "findings.json").exists():
        pytest.skip("case_011 not yet run")
    align = _build(alignment_module, case_dir)
    rows = align["expected_targets"]
    assert rows[0]["manusift_detected"] == "not_testable"
    assert "testable_from_public_materials" in rows[0]
    assert rows[0]["testable_from_public_materials"] is False


def test_case_032_is_not_testable(alignment_module) -> None:
    """Peer-review-only case: article-level + no specific figures."""
    case_dir = BASE / "case_032_frontiers_peer_review"
    if not (case_dir / "manusift_run" / "findings.json").exists():
        pytest.skip("case_032 not yet run")
    align = _build(alignment_module, case_dir)
    rows = align["expected_targets"]
    # Should be not_testable (no specific figure named).
    assert rows[0]["manusift_detected"] in ("not_testable", "missed")
    # The testable_from_public_materials flag controls this.
    if not rows[0].get("testable_from_public_materials", True):
        assert rows[0]["manusift_detected"] == "not_testable"


def test_case_059_image_count_heuristic(alignment_module) -> None:
    """case_059 exposes only 1 image -> image-duplication target
    cannot be tested directly. The detector's behaviour depends
    on whether the paper-mill detector fires:

      - Before paper_mill_authorship (R-2026-06-13): target was
        ``not_testable`` (image-count heuristic).
      - After paper_mill_authorship: if the byline shows paper-mill
        co-authorship (>= 4 authors / few affiliations), the target
        becomes ``partial`` because the metadata signal is
        actionable even when the image signal is absent.

    This is the R-2026-06-13 expected outcome (P0-PEER detector
    fires on case_059).
    """
    case_dir = BASE / "case_059_plos_clin_hypox"
    if not (case_dir / "manusift_run" / "findings.json").exists():
        pytest.skip("case_059 not yet run")
    align = _build(alignment_module, case_dir)
    rows = align["expected_targets"]
    # Accept either not_testable (pre-paper-mill detector) or
    # partial (post-paper-mill detector fired). Both are
    # correct outcomes; the difference is whether the paper-mill
    # detector surfaces the byline signal.
    assert rows[0]["manusift_detected"] in ("not_testable", "partial"), (
        f"case_059 should be not_testable (image-only, no images) "
        f"or partial (paper-mill signal fired); got "
        f"{rows[0]['manusift_detected']}"
    )


def test_article_level_image_only_with_zero_images(
    alignment_module,
    tmp_path: Path,
) -> None:
    """Unit test of the article-level image-only / zero-images heuristic.

    Synthesises a fake case directory with:
      - paper.pdf with 0 images
      - official_gold.json with one article-level target whose
        description triggers the image keyword
      - findings.json with zero findings

    Expected: ``not_testable`` (not ``missed``)."""
    case_dir = tmp_path / "fake_case"
    case_dir.mkdir()
    run_dir = case_dir / "manusift_run"
    run_dir.mkdir()
    # Minimal paper.pdf (won't be parsed because pages_text will be
    # empty when parse_pdf is patched).
    (case_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    # official_gold.json with image-keyword description.
    (case_dir / "official_gold.json").write_text(json.dumps({
        "case_id": "fake_case",
        "title": "Fake",
        "doi": "",
        "doi_url": "",
        "official_source_url": "",
        "official_reason_category": "image_duplication",
        "expected_targets": [_make_target(
            location="all figures",
            description="image duplication concerns in this paper",
            testable=True,
        )],
        "expected_detector_categories": ["image_dup", "image_forensics"],
    }))
    (run_dir / "findings.json").write_text(json.dumps({
        "findings": [],
    }))

    # Patch parse_pdf to return a doc with 0 images.
    from manusift.ingest import pdf as _pdf_mod

    class _FakeDoc:
        text_blocks: list = []
        images: list = []
        tables: list = []

    original = _pdf_mod.parse_pdf
    _pdf_mod.parse_pdf = lambda *a, **kw: _FakeDoc()  # type: ignore[assignment]
    try:
        align = _build(alignment_module, case_dir)
    finally:
        _pdf_mod.parse_pdf = original  # type: ignore[assignment]

    rows = align["expected_targets"]
    assert rows[0]["manusift_detected"] == "not_testable"
    assert "unrendered" in rows[0]["reason"].lower() or \
        "cannot be tested" in rows[0]["reason"].lower() or \
        "1 image" in rows[0]["reason"]


def test_article_level_metadata_target_zero_images(
    alignment_module,
    tmp_path: Path,
) -> None:
    """Article-level metadata-only target (no image keyword in
    description) with zero images and zero findings: should be
    ``missed`` (the metadata detector SHOULD fire if metadata is
    actually concerning)."""
    case_dir = tmp_path / "fake_meta_case"
    case_dir.mkdir()
    run_dir = case_dir / "manusift_run"
    run_dir.mkdir()
    (case_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (case_dir / "official_gold.json").write_text(json.dumps({
        "case_id": "fake_meta_case",
        "title": "Fake meta",
        "doi": "",
        "doi_url": "",
        "official_source_url": "",
        "official_reason_category": "peer_review",
        "expected_targets": [_make_target(
            location="all figures",
            description=(
                "The paper was retracted for peer review "
                "concerns and authorship issues."
            ),
            testable=True,
        )],
        "expected_detector_categories": [
            "author_emails", "metadata", "ref_duplicate",
        ],
    }))
    (run_dir / "findings.json").write_text(json.dumps({"findings": []}))

    from manusift.ingest import pdf as _pdf_mod

    class _FakeDoc:
        text_blocks: list = []
        images: list = []
        tables: list = []

    original = _pdf_mod.parse_pdf
    _pdf_mod.parse_pdf = lambda *a, **kw: _FakeDoc()  # type: ignore[assignment]
    try:
        align = _build(alignment_module, case_dir)
    finally:
        _pdf_mod.parse_pdf = original  # type: ignore[assignment]

    rows = align["expected_targets"]
    # Metadata-only target -> the image-count heuristic does NOT
    # apply; the target is still genuinely missed.
    assert rows[0]["manusift_detected"] == "missed"


def test_figure_specific_target_with_findings(
    alignment_module,
    tmp_path: Path,
) -> None:
    """Figure-N specific target with a matching finding on the same
    page -> ``exact``."""
    case_dir = tmp_path / "fake_fig_case"
    case_dir.mkdir()
    run_dir = case_dir / "manusift_run"
    run_dir.mkdir()
    (case_dir / "paper.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (case_dir / "official_gold.json").write_text(json.dumps({
        "case_id": "fake_fig_case",
        "title": "Fake fig",
        "doi": "",
        "doi_url": "",
        "official_source_url": "",
        "official_reason_category": "image_duplication",
        "expected_targets": [{
            "type": "figure",
            "location": "Figure 3",
            "description": "Image duplication confirmed in Figure 3",
            "evidence_source": "retraction notice",
            "severity": "high",
            "testable_from_public_materials": True,
            "limitations": [],
            "expected_evidence_type": "image_similarity",
        }],
        "expected_detector_categories": ["image_forensics"],
    }))
    (run_dir / "findings.json").write_text(json.dumps({
        "findings": [{
            "detector": "image_forensics",
            "title": "Cross-page duplicate",
            "evidence": "image on page 3 has Hamming 0",
            "location": "page 3",
            "severity": "high",
        }],
    }))

    # Patch parse_pdf to return page-text with the CAPS rendered
    # figure label on page 3.
    from manusift.ingest import pdf as _pdf_mod

    class _TB:
        def __init__(self, page: int, text: str):
            self.page = page
            self.text = text

    class _FakeDoc:
        text_blocks = [
            _TB(2, "Body text mentioning Figure 3 in passing"),
            _TB(3, "FIGURE 3\nThis is the caption for Figure 3.\n"),
        ]
        images = []
        tables = []

    original = _pdf_mod.parse_pdf
    _pdf_mod.parse_pdf = lambda *a, **kw: _FakeDoc()  # type: ignore[assignment]
    try:
        align = _build(alignment_module, case_dir)
    finally:
        _pdf_mod.parse_pdf = original  # type: ignore[assignment]

    rows = align["expected_targets"]
    assert rows[0]["manusift_detected"] == "exact"
    assert rows[0]["manusift_findings_count"] >= 1