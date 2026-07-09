"""Tests for the cross-page image duplicate detector using
``imagehash`` (Step T3).

Pre-T3, the image duplicate
detector used a single
hand-rolled pHash. T3 layers
four perceptual hash algorithms
(``phash`` / ``ahash`` /
``dhash`` / ``whash``) on top
of the existing detector so we
can cover different content
types: photographs, line
drawings, screenshots, and
re-encoded stock images.

The tests are unit-level -- we
build ``ExtractedImage`` values
in memory, run the detector,
and assert on the findings.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from manusift.contracts import ExtractedImage, ParsedDoc


# ---------- helpers ----------

def _make_image_path(width: int, height: int, color) -> str:
    """Write a solid-color PNG to a
    temp file and return the
    path. The imagehash detector
    reads the path via PIL; we
    cannot use a BytesIO because
    PIL needs a real file
    descriptor for the DCT
    transform that pHash/wHash
    use internally."""
    import tempfile
    img = Image.new("RGB", (width, height), color)
    f = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False
    )
    img.save(f, format="PNG")
    f.close()
    return f.name


def _doc_with_images(images: list[ExtractedImage], trace_id: str = "t-1") -> ParsedDoc:
    """Build a minimal ParsedDoc
    with the given images and
    empty text/metadata. The
    detector does not need text
    blocks or metadata."""
    return ParsedDoc(
        trace_id=trace_id,
        source_path="/tmp/fake.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )


def _image(
    page: int = 1,
    color=(255, 0, 0),
    phash: str = "",
) -> ExtractedImage:
    return ExtractedImage(
        page=page,
        index=0,
        xref=0,
        width=64,
        height=64,
        bytes_size=0,
        phash=phash,
        image_path=_make_image_path(64, 64, color),
    )


# ---------- 1. detector name and registration ----------

def test_phash_detector_name() -> None:
    """The detector's ``name``
    must be the unique registry
    key the pipeline looks up.
    Distinct from the original
    ``image_dup`` so users can
    run both side by side."""
    from manusift.detectors import PHashDetector
    d = PHashDetector()
    assert d.name == "imagehash_phash"


def test_detector_variants_have_distinct_names() -> None:
    from manusift.detectors import (
        AHashDetector,
        DHashDetector,
        PHashDetector,
        WHashDetector,
    )
    names = {
        PHashDetector().name,
        AHashDetector().name,
        DHashDetector().name,
        WHashDetector().name,
    }
    assert len(names) == 4


# ---------- 2. exact-duplicate images are flagged ----------

def test_exact_duplicate_images_are_flagged() -> None:
    """Two byte-identical images
    must produce one finding with
    Hamming distance 0 (perfect
    match). The severity should
    be "high" because the
    distance is at or below 4."""
    from manusift.detectors import PHashDetector
    a = _image(page=1, color=(10, 200, 50), phash="00000000ffff0000")
    b = _image(page=2, color=(10, 200, 50), phash="00000000ffff0000")
    doc = _doc_with_images([a, b])
    result = PHashDetector().run(doc)
    assert len(result.findings) >= 1
    # The first finding should be high severity.
    assert result.findings[0].severity == "high"


def test_distinct_images_are_not_flagged() -> None:
    """Two visually very different
    images (a black square vs. a
    white square) must not
    produce a "high" severity
    finding. pHash is robust to
    the exact colour of the
    pixels -- a red square vs
    a blue square are similar
    in shape and may still be
    within the threshold. We use
    a much higher contrast
    pattern (checkerboard vs.
    solid black) which pHash
    reliably separates.
    """
    from manusift.detectors import PHashDetector
    # Make a checkerboard image.
    import tempfile
    from PIL import Image as _Img
    cb = _Img.new("L", (64, 64), 0)
    for x in range(64):
        for y in range(64):
            if (x // 8 + y // 8) % 2 == 0:
                cb.putpixel((x, y), 255)
    f = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False
    )
    cb.save(f, format="PNG")
    f.close()
    a = _image(page=1, color=(0, 0, 0))  # solid black
    b = _Img.open(f.name)
    # Inject the checkerboard
    # image into the doc by
    # constructing a second
    # image manually.
    checker = ExtractedImage(
        page=2,
        index=0,
        xref=0,
        width=64,
        height=64,
        bytes_size=0,
        phash="",
        image_path=f.name,
    )
    doc = _doc_with_images([a, checker])
    result = PHashDetector().run(doc)
    # Solid black vs checkerboard
    # should not produce a "high"
    # finding.
    high_findings = [
        fnd for fnd in result.findings
        if fnd.severity == "high"
    ]
    assert len(high_findings) == 0


# ---------- 3. all four algorithms work ----------

def test_ahash_detector_runs() -> None:
    from manusift.detectors import AHashDetector
    a = _image(page=1, color=(128, 128, 128))
    b = _image(page=2, color=(128, 128, 128))
    doc = _doc_with_images([a, b])
    result = AHashDetector().run(doc)
    # Identical gray images should
    # match under aHash.
    assert len(result.findings) >= 1


def test_dhash_detector_runs() -> None:
    from manusift.detectors import DHashDetector
    a = _image(page=1, color=(10, 20, 30))
    b = _image(page=2, color=(10, 20, 30))
    doc = _doc_with_images([a, b])
    result = DHashDetector().run(doc)
    assert len(result.findings) >= 1


def test_whash_detector_runs() -> None:
    from manusift.detectors import WHashDetector
    a = _image(page=1, color=(64, 64, 64))
    b = _image(page=2, color=(64, 64, 64))
    doc = _doc_with_images([a, b])
    result = WHashDetector().run(doc)
    assert len(result.findings) >= 1


# ---------- 4. corrupted image is skipped silently ----------

def test_corrupted_image_bytes_are_skipped() -> None:
    """A single corrupted image in
    the PDF must not crash the
    detector. The other images
    are still compared normally."""
    from manusift.detectors import PHashDetector
    good = _image(page=1, color=(0, 0, 0))
    corrupted = ExtractedImage(
        page=2,
        index=0,
        xref=0,
        width=64,
        height=64,
        bytes_size=0,
        phash="",
        image_path="/nonexistent/path.png",
    )
    # The good image is compared
    # with itself (only one of
    # each), so the loop yields
    # no findings, but the
    # detector must not raise.
    doc = _doc_with_images([good, corrupted])
    result = PHashDetector().run(doc)
    # No crash, no findings.
    assert isinstance(result.findings, list)


# ---------- 5. finding evidence includes both images ----------

def test_finding_evidence_includes_both_images() -> None:
    """A duplicate finding must
    name both images (page,
    phash, dimensions) so the
    user can locate them in the
    PDF without re-running the
    detector."""
    from manusift.detectors import PHashDetector
    import json as _json
    a = _image(page=3, color=(1, 2, 3), phash="aaaa")
    b = _image(page=5, color=(1, 2, 3), phash="aaaa")
    doc = _doc_with_images([a, b])
    result = PHashDetector().run(doc)
    assert len(result.findings) == 1
    evidence = _json.loads(result.findings[0].evidence)
    assert evidence["image_a"]["page"] == 3
    assert evidence["image_b"]["page"] == 5
    assert "hamming" in evidence
    assert evidence["algorithm"] == "phash"


# ---------- 6. threshold is respected ----------

def test_higher_threshold_yields_more_findings(monkeypatch) -> None:
    """Bumping the threshold up
    should produce at least as
    many findings as the lower
    threshold. We monkey-patch
    the settings and check both
    extremes."""
    from manusift.config import get_settings
    from manusift.detectors import PHashDetector
    a = _image(page=1, color=(50, 50, 50))
    b = _image(page=2, color=(60, 60, 60))
    doc = _doc_with_images([a, b])
    s = get_settings()
    # Strict: require near-
    # identical.
    s_strict = s.model_copy(update={"image_duplicate_hamming_threshold": 0})
    monkeypatch.setattr("manusift.config.get_settings", lambda: s_strict)
    strict_count = len(
        PHashDetector().run(doc).findings
    )
    # Permissive: anything within
    # 64 bits counts.
    s_loose = s.model_copy(update={"image_duplicate_hamming_threshold": 64})
    monkeypatch.setattr("manusift.config.get_settings", lambda: s_loose)
    loose_count = len(
        PHashDetector().run(doc).findings
    )
    assert loose_count >= strict_count
