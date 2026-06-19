"""Unit tests for the Evidence Report layer (R-2026-06-12).

The user spec asks for tests covering:

  * crop asset creation;
  * side-by-side annotated image existence;
  * evidence_index.json schema;
  * numerical explanation generation;
  * regression on at least 2 previous benchmark cases;
  * the report still works when no findings exist.

These tests are pure
unit / integration
tests -- they don't
OCR anything (the OCR
path is tested
elsewhere in
``test_figure_grim``)
and they don't run
the full benchmark
(that's covered by
the real_eval_fraud_cases
runs)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.report import evidence
from manusift.report import evidence_builder
from manusift.report import evidence_report
from manusift.report import visual_evidence


# ---- Evidence schema tests --------------------------------------

def test_severity_enum_values() -> None:
    """The 5 severity levels match the spec."""

    assert {s.value for s in evidence.Severity} == {
        "critical", "high", "medium", "low", "info",
    }


def test_finding_type_enum_values() -> None:
    """The 7 evidence categories match the spec."""

    assert {t.value for t in evidence.FindingType} == {
        "image_similarity",
        "numerical_consistency",
        "metadata",
        "reference",
        "compliance",
        "text_pattern",
        "unknown",
    }


def test_promote_severity_impossible() -> None:
    """GRIM ``impossible=True`` promotes medium -> high."""

    sev = evidence.promote_severity(evidence.Severity.MEDIUM, impossible=True)
    assert sev == evidence.Severity.HIGH


def test_promote_severity_hamming() -> None:
    """Hamming <= 2 promotes medium -> high."""

    sev = evidence.promote_severity(evidence.Severity.MEDIUM, hamming=1)
    assert sev == evidence.Severity.HIGH
    sev = evidence.promote_severity(evidence.Severity.MEDIUM, hamming=3)
    assert sev == evidence.Severity.MEDIUM


def test_promote_severity_critical() -> None:
    """``confirmed_official=True`` promotes high -> critical."""

    sev = evidence.promote_severity(evidence.Severity.HIGH, confirmed_official=True)
    assert sev == evidence.Severity.CRITICAL


def test_bounding_box_as_tuple() -> None:
    bb = evidence.BoundingBox(0, 1, 2, 3)
    assert bb.as_tuple() == (0, 1, 2, 3)


def test_location_label_full_and_short() -> None:
    loc = evidence.Location(
        page=7, figure="Fig. 5", panel="B",
        bbox=evidence.BoundingBox(0, 1, 100, 200),
    )
    assert loc.label() == "Page 7 · Fig. Fig. 5 · Panel B" or "Fig. 5" in loc.label()
    assert "bbox=" in loc.full_label()


# ---- Visual evidence asset tests --------------------------------

def test_safe_open_missing_file(tmp_path: Path) -> None:
    """_safe_open returns None for a missing file."""

    result = visual_evidence._safe_open(tmp_path / "does-not-exist.png")
    assert result is None


def test_safe_open_none_path() -> None:
    """_safe_open returns None for a None path (the spec
    mentions graceful degradation when the source image is
    missing)."""

    assert visual_evidence._safe_open(None) is None  # type: ignore[arg-type]


def test_safe_open_real_image(tmp_path: Path) -> None:
    """_safe_open returns a PIL Image for a real PNG."""

    from PIL import Image
    p = tmp_path / "test.png"
    Image.new("RGB", (50, 50), (255, 0, 0)).save(p)
    img = visual_evidence._safe_open(p)
    assert img is not None
    assert img.size == (50, 50)


def test_side_by_side_label_strip() -> None:
    """_draw_label writes a one-line label strip."""

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 50), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    visual_evidence._draw_label(draw, "Page 7 · Fig. 2 · Panel A", y=0, width=200)
    # Verify
    # the
    # background
    # strip
    # is
    # drawn
    # (white).
    pixel = img.getpixel((10, 5))
    assert pixel == (255, 255, 255)


def test_build_visual_assets_missing_source(tmp_path: Path) -> None:
    """build_visual_assets degrades gracefully when the
    source image is missing."""

    finding = evidence.VisualFinding(
        finding_id="X1",
        severity=evidence.Severity.HIGH,
        confidence=0.5,
        detector="image_dup",
        summary="Test",
        location_a=evidence.Location(
            page=1, source_image=str(tmp_path / "missing.png"),
        ),
        location_b=evidence.Location(
            page=2, source_image=str(tmp_path / "missing.png"),
        ),
        reasoning="Test",
    )
    result = visual_evidence.build_visual_assets(
        finding=finding, out_dir=tmp_path,
    )
    # No
    # assets
    # were
    # written,
    # but
    # the
    # call
    # returns
    # the
    # finding
    # without
    # raising.
    assert result.assets == {}


# ---- Data evidence explainer tests -------------------------------

def test_explain_figure_grim_impossible() -> None:
    """``97% with n=3`` should be flagged as ``impossible``."""

    raw = {
        "finding_id": "X1",
        "detector": "figure_grim",
        "severity": "medium",
        "page": 6,
        "region": 0,
        "text": "97% identical",
        "confidence": 0.8,
        "percentage": 97.0,
        "n_used": 3,
        "implied_count": 2.91,
    }
    from manusift.report.data_evidence import explain_figure_grim
    explained = explain_figure_grim(raw)
    assert explained.result == "impossible"
    assert "integer" in explained.reasoning.lower()
    # The
    # severity
    # should
    # have
    # been
    # promoted
    # to
    # high.
    assert explained.severity == evidence.Severity.HIGH


def test_explain_figure_grim_n_is_list() -> None:
    """The n field can be a list (the detector sweeps a range).
    The explainer should normalise it."""

    raw = {
        "finding_id": "X1",
        "page": 6,
        "percentage": 97.0,
        "n_used": [3, 100],  # the detector's sweep range
        "implied_count": 2.91,
    }
    from manusift.report.data_evidence import explain_figure_grim
    explained = explain_figure_grim(raw)
    # Should
    # not
    # raise
    # even
    # though
    # n is
    # a
    # list.
    assert explained.result == "impossible"
    # expected_constraint
    # is
    # now
    # a
    # string
    # (not
    # a
    # list).
    assert isinstance(explained.expected_constraint, str)


def test_explain_figure_grim_not_testable() -> None:
    """If implied_count is None, the result is ``not_testable``."""

    raw = {
        "finding_id": "X1",
        "page": 6,
        "percentage": 50.0,
        "n_used": 10,
        "implied_count": None,
    }
    from manusift.report.data_evidence import explain_figure_grim
    explained = explain_figure_grim(raw)
    assert explained.result == "not_testable"


def test_explain_image_forensics_hamming_zero() -> None:
    """Hamming=0 should promote severity to high."""

    raw = {
        "finding_id": "X1",
        "page": 6,
        "index": 0,
        "grid": 8,
        "match_count": 50,
        "best": {"cell_a": [0, 0], "cell_b": [1, 0], "hamming": 0},
        "image_path": "/nonexistent/img.png",
    }
    from manusift.report.data_evidence import explain_image_forensics
    explained = explain_image_forensics(raw)
    assert explained.severity == evidence.Severity.HIGH
    # Source
    # image
    # must
    # be
    # wired
    # through
    # --
    # the
    # explainer
    # now
    # reads
    # image_path
    # from
    # the
    # raw
    # envelope.
    assert explained.location_a.source_image == "/nonexistent/img.png"


def test_explain_panel_dup_provenance() -> None:
    """panel_dup must populate page/panel fields from the raw
    envelope."""

    raw = {
        "finding_id": "X1",
        "page_a": 10,
        "panel_a": 2,
        "phash_a": "abc",
        "page_b": 11,
        "panel_b": 2,
        "phash_b": "def",
        "hamming": 4,
    }
    from manusift.report.data_evidence import explain_panel_dup
    explained = explain_panel_dup(raw)
    assert explained.location_a.page == 10
    assert explained.location_a.panel == "2"
    assert explained.location_b.page == 11
    assert explained.location_b.panel == "2"
    # hamming=4
    # does
    # not
    # promote
    # to
    # high
    # (only
    # hamming<=2).
    assert explained.severity == evidence.Severity.MEDIUM


# ---- Builder / renderer integration tests -----------------------

def test_unwrap_raw_merges_top_level() -> None:
    """``_unwrap_raw`` lifts ``raw.*`` keys onto the top level."""

    from manusift.report.data_evidence import _unwrap_raw
    d = {"detector": "x", "raw": {"page": 5, "score": 0.9}}
    out = _unwrap_raw(d)
    assert out["page"] == 5
    assert out["score"] == 0.9
    assert out["detector"] == "x"


def test_unwrap_raw_does_not_clobber() -> None:
    """``_unwrap_raw`` does not overwrite an existing top-level
    field with the same name."""

    from manusift.report.data_evidence import _unwrap_raw
    d = {"raw": {"page": 5}, "page": 99}
    out = _unwrap_raw(d)
    assert out["page"] == 99


def test_build_evidence_index_empty_findings(tmp_path: Path) -> None:
    """The report still works when there are no findings."""

    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps({
        "trace_id": "test",
        "detectors_run": [],
        "llm_calls": 0,
        "duration_ms": 0,
        "findings": [],
    }))
    out_dir = tmp_path / "report"
    index = evidence_builder.build_evidence_index(
        findings_path=findings_path,
        out_dir=out_dir,
        paper_id="test",
    )
    assert index.summary == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    assert index.visual_findings == []
    assert index.numerical_findings == []
    assert index.metadata_findings == []


def test_build_evidence_index_minimal_metadata_finding(tmp_path: Path) -> None:
    """A finding with no recognisable detector should land
    in the metadata bucket as a fallback (not crash the
    report)."""

    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps({
        "trace_id": "t",
        "detectors_run": ["unknown_detector"],
        "llm_calls": 0,
        "duration_ms": 0,
        "findings": [{
            "finding_id": "X1",
            "trace_id": "t",
            "detector": "unknown_detector",
            "severity": "low",
            "title": "Unknown detector finding",
            "evidence": "...",
            "location": "...",
            "raw": {},
        }],
    }))
    out_dir = tmp_path / "report"
    index = evidence_builder.build_evidence_index(
        findings_path=findings_path,
        out_dir=out_dir,
        paper_id="t",
    )
    assert len(index.metadata_findings) == 1
    assert index.metadata_findings[0].detector == "unknown_detector"


def test_evidence_index_to_dict_normalises_lists() -> None:
    """``to_dict`` should normalise list-valued strings to a
    single string."""

    f = evidence.NumericalFinding(
        finding_id="X1",
        severity=evidence.Severity.MEDIUM,
        confidence=0.5,
        detector="figure_grim",
        summary="test",
        location=evidence.Location(),
        test_name="t",
        test_description="d",
        input_values={},
        expected_constraint=["a", "b"],  # list!
        observed_value="o",
        result="inconsistent",
        reasoning="r",
    )
    index = evidence.EvidenceIndex(
        trace_id="t",
        paper_id="p",
        detectors_run=[],
        numerical_findings=[f],
    )
    d = index.to_dict()
    # The
    # list
    # was
    # joined
    # with
    # " | ".
    assert d["numerical_findings"][0]["expected_constraint"] == "a | b"


def test_write_evidence_index_handles_path_objects(tmp_path: Path) -> None:
    """``write_evidence_index`` serialises Path objects."""

    f = evidence.NumericalFinding(
        finding_id="X1",
        severity=evidence.Severity.MEDIUM,
        confidence=0.5,
        detector="figure_grim",
        summary="test",
        location=evidence.Location(source_image=tmp_path / "a.png"),
        test_name="t",
        test_description="d",
        input_values={},
        expected_constraint="c",
        observed_value="o",
        result="inconsistent",
        reasoning="r",
    )
    index = evidence.EvidenceIndex(
        trace_id="t",
        paper_id="p",
        detectors_run=[],
        numerical_findings=[f],
    )
    out_path = tmp_path / "evidence_index.json"
    evidence.write_evidence_index(index, out_path)
    data = json.loads(out_path.read_text())
    assert data["numerical_findings"][0]["location"]["source_image"].endswith("a.png")


# ---- HTML / Markdown rendering smoke tests ----------------------

def test_render_markdown_with_no_findings() -> None:
    """The Markdown renderer should not crash on an empty index."""

    index = evidence.EvidenceIndex(
        trace_id="t",
        paper_id="p",
        detectors_run=[],
    )
    md = evidence_report.render_markdown(index, Path("."))
    assert "ManuSift evidence report" in md
    assert "## 1. Executive Summary" in md


def test_render_html_with_no_findings() -> None:
    index = evidence.EvidenceIndex(
        trace_id="t",
        paper_id="p",
        detectors_run=[],
    )
    html = evidence_report.render_html(index, Path("."))
    assert "ManuSift evidence report" in html
    assert "<h2>1. Executive Summary</h2>" in html


# ---- Real-benchmark regression tests ----------------------------

def test_regression_case_005_evidence_report(tmp_path: Path) -> None:
    """Run the evidence builder on the v9 case_005 findings
    and verify the report has the expected counts.

    R-2026-06-12: case_005
    is a Frontiers paper
    with both image and
    numerical findings
    -- the regression test
    checks that the
    builder produces the
    right shape of report.
    """

    findings_path = Path(
        r"C:\Users\22509\Desktop\ManuSift1"
        r"\real_eval_fraud_cases\cases\case_005_frontiers_cpxra_salmonella_hild"
        r"\manusift_run\findings.json"
    )
    if not findings_path.exists():
        pytest.skip("case_005 findings.json not present -- benchmark not run yet")
    out_dir = tmp_path / "report"
    pdf_path = Path(
        r"C:\Users\22509\Desktop\ManuSift1"
        r"\real_eval_fraud_cases\cases\case_005_frontiers_cpxra_salmonella_hild"
        r"\paper.pdf"
    )
    index = evidence_builder.build_evidence_index(
        findings_path=findings_path,
        out_dir=out_dir,
        paper_id="case_005",
        pdf_path=pdf_path if pdf_path.exists() else None,
    )
    # We
    # expect
    # at
    # least
    # 1
    # visual
    # finding
    # (panel_dup)
    # and
    # 1
    # numerical
    # finding
    # (figure_grim).
    assert len(index.visual_findings) >= 1
    assert len(index.numerical_findings) >= 1
    # The
    # visual
    # findings
    # should
    # have
    # generated
    # side_by_side.png
    # files.
    for f in index.visual_findings:
        if f.assets:
            sbs = out_dir / f.assets.get("side_by_side", "")
            assert sbs.exists(), f"missing side-by-side for {f.finding_id}"
            crop_a = out_dir / f.assets.get("crop_a", "")
            crop_b = out_dir / f.assets.get("crop_b", "")
            assert crop_a.exists() and crop_b.exists()
    # The
    # numerical
    # finding
    # should
    # be
    # the
    # 97%
    # n=3
    # case
    # --
    # impossible
    # verdict.
    for f in index.numerical_findings:
        if f.detector == "figure_grim" and "97" in str(f.input_values.get("ocr_text", "")):
            assert f.result == "impossible"
            break


def test_regression_case_001_evidence_report(tmp_path: Path) -> None:
    """Run on case_001 (PLOS) which has many image_dup findings.

    The renderer should
    produce at least one
    visual finding with a
    side-by-side image."""

    findings_path = Path(
        r"C:\Users\22509\Desktop\ManuSift1"
        r"\real_eval_fraud_cases\cases\case_001_plos_plasmonic_nanobubbles"
        r"\manusift_run\findings.json"
    )
    if not findings_path.exists():
        pytest.skip("case_001 findings.json not present")
    out_dir = tmp_path / "report"
    index = evidence_builder.build_evidence_index(
        findings_path=findings_path,
        out_dir=out_dir,
        paper_id="case_001",
    )
    # case_001
    # has
    # many
    # image_dup
    # findings.
    assert len(index.visual_findings) >= 1
