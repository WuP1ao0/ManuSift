"""Unit-level negative-control guards for P6 channels.

Full 16-paper smoke lives in ``benchmarks/negative_controls_v1/``.
These fixtures lock the high-severity FP regressions we fixed when
P6 gel seam / cross-paper / excel-span first landed on controls.
"""
from __future__ import annotations

from pathlib import Path

from manusift.contracts import ExtractedImage, Finding, ParsedDoc
from manusift.detectors.cross_paper_image import CrossPaperImageDetector
from manusift.detectors.image_dup import ImageDuplicateDetector
from manusift.detectors.image_forensics import _vertical_gel_seam_check
from manusift.detectors.stat_extra import PValuePileupDetector
from manusift.knowledge.fingerprint_index import append_records
from manusift.report.finding_calibration import calibrate_findings


def test_multi_panel_white_gutter_not_gel_seam(tmp_path: Path) -> None:
    """Two dark panels + pure white vertical gutter must not fire seam."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (240, 120), color=40)
    d = ImageDraw.Draw(img)
    # left panel content
    d.rectangle([10, 20, 100, 100], fill=60)
    # white multi-panel gutter
    d.rectangle([112, 0, 128, 120], fill=255)
    # right panel content
    d.rectangle([140, 20, 230, 100], fill=55)
    path = tmp_path / "multipanel.png"
    img.save(path)
    ei = ExtractedImage(
        page=0,
        index=0,
        xref=1,
        width=240,
        height=120,
        bytes_size=path.stat().st_size,
        image_path=str(path),
        phash=None,
    )
    assert _vertical_gel_seam_check(ei) is None


def test_gel_seam_severity_never_high_on_hard_join(tmp_path: Path) -> None:
    """Even a true hard join is screening-level (max medium)."""
    from PIL import Image, ImageDraw
    import random

    rng = random.Random(1)
    img = Image.new("L", (200, 120))
    pix = img.load()
    for y in range(120):
        for x in range(200):
            if x < 100:
                pix[x, y] = max(0, min(255, 70 + rng.randint(-25, 25)))
            else:
                pix[x, y] = max(0, min(255, 190 + rng.randint(-20, 20)))
    d = ImageDraw.Draw(img)
    d.rectangle([15, 40, 85, 55], fill=15)
    path = tmp_path / "splice.png"
    img.save(path)
    ei = ExtractedImage(
        page=0,
        index=0,
        xref=1,
        width=200,
        height=120,
        bytes_size=path.stat().st_size,
        image_path=str(path),
        phash=None,
    )
    hit = _vertical_gel_seam_check(ei)
    assert hit is not None
    sev = hit[0]
    assert sev in ("medium", "low")
    assert sev != "high"


def test_cross_paper_skips_generic_and_trace_paper_ids(
    tmp_path: Path, monkeypatch
) -> None:
    idx = tmp_path / "fp.jsonl"
    monkeypatch.setenv("MANUSIFT_FINGERPRINT_INDEX", str(idx))
    monkeypatch.setenv("MANUSIFT_CROSS_PAPER_IMAGE", "1")
    append_records(
        [
            {
                "paper_id": "original",
                "phash": "bbbbbbbbbbbbbbbb",
                "page": 0,
                "index": 0,
            },
            {
                "paper_id": "db75cb4c4d89",
                "phash": "bbbbbbbbbbbbbbbb",
                "page": 0,
                "index": 1,
            },
        ],
        path=idx,
    )
    doc = ParsedDoc(
        trace_id="t-nc",
        source_path=str(tmp_path / "case_dir" / "paper.pdf"),
        text_blocks=[],
        images=[
            ExtractedImage(
                page=0,
                index=0,
                xref=1,
                width=300,
                height=200,
                bytes_size=40_000,
                image_path=None,
                phash="bbbbbbbbbbbbbbbb",
            )
        ],
        metadata={"title": "A legitimate control paper title long enough"},
    )
    result = CrossPaperImageDetector().run(doc)
    assert result.findings == []


def test_excel_span_calibrated_without_member_highs() -> None:
    f = Finding.make(
        trace_id="t",
        detector="table_relationships",
        severity="high",
        title="Excel-style fabricated numeric patterns span 5 tables",
        evidence="synthetic",
        location="paper-level",
        raw={
            "check": "excel_fabrication_span",
            "n": 18,
            "table_count": 5,
            "high_member_count": 0,
        },
    )
    out = calibrate_findings([f])
    assert out[0].severity == "medium"


def test_duplicate_excess_calibrated_cap_medium() -> None:
    f = Finding.make(
        trace_id="t",
        detector="table_relationships",
        severity="high",
        title="column has statistically improbable duplicate values",
        evidence="synthetic",
        location="Table 1, column 2",
        raw={
            "check": "duplicate_excess",
            "n": 40,
            "q_bh": 1e-6,
            "duplicate_rate": 0.2,
        },
    )
    out = calibrate_findings([f])
    assert out[0].severity == "medium"


def test_clean_text_no_pvalue_pileup() -> None:
    """Sparse legitimate p-values must not fire pileup."""
    class _Doc:
        trace_id = "t"
        source_path = "clean.pdf"
        text_blocks = [
            type(
                "B",
                (),
                {
                    "text": (
                        "Results were significant (p=0.03). "
                        "Secondary endpoint p=0.12. "
                        "Sensitivity p=0.21."
                    )
                },
            )()
        ]
        images: list = []
        metadata: dict = {}
        tables: list = []

    result = PValuePileupDetector().run(_Doc())  # type: ignore[arg-type]
    assert result.findings == []


def test_unrelated_figures_no_loading_control_high(tmp_path: Path) -> None:
    """Two unrelated full figures should not produce LC high findings."""
    from PIL import Image, ImageDraw

    def make(path: Path, color: tuple[int, int, int]) -> None:
        img = Image.new("RGB", (200, 180), color=(250, 250, 250))
        d = ImageDraw.Draw(img)
        d.rectangle([20, 20, 180, 100], fill=color)
        d.ellipse([40, 120, 160, 170], fill=(color[0] // 2,) * 3)
        img.save(path)

    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.png"
    make(p1, (200, 40, 40))
    make(p2, (40, 40, 200))
    images = [
        ExtractedImage(
            page=0,
            index=0,
            xref=1,
            width=200,
            height=180,
            bytes_size=20_000,
            image_path=str(p1),
            phash="1111111111111111",
        ),
        ExtractedImage(
            page=1,
            index=0,
            xref=2,
            width=200,
            height=180,
            bytes_size=20_000,
            image_path=str(p2),
            phash="2222222222222222",
        ),
    ]
    doc = ParsedDoc(
        trace_id="t",
        source_path="paper.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )
    result = ImageDuplicateDetector().run(doc)
    lc_high = [
        f
        for f in result.findings
        if (f.raw or {}).get("check") == "loading_control_roi_dup"
        and f.severity == "high"
    ]
    assert lc_high == []
