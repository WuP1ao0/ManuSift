"""P6.1: geometric flip/rotate pass on image_dup."""
from __future__ import annotations

from pathlib import Path

import pytest

from manusift.contracts import ExtractedImage, ParsedDoc
from manusift.detectors.image_dup import (
    ImageDuplicateDetector,
    _best_geo_match,
    _compute_transform_phashes,
    _hamming,
)


def _write_pair(tmp: Path) -> tuple[Path, Path]:
    """Create a figure-like PNG and its horizontal flip."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (160, 120), color=(240, 240, 240))
    d = ImageDraw.Draw(img)
    # Asymmetric pattern so flip is not identity.
    d.rectangle([10, 20, 50, 90], fill=(20, 20, 20))
    d.ellipse([90, 30, 140, 100], fill=(180, 40, 40))
    d.line([15, 15, 145, 105], fill=(0, 100, 200), width=3)
    p1 = tmp / "orig.png"
    p2 = tmp / "hflip.png"
    img.save(p1)
    img.transpose(Image.FLIP_LEFT_RIGHT).save(p2)
    return p1, p2


def test_transform_phashes_hflip_matches_flipped_file(tmp_path: Path) -> None:
    p1, p2 = _write_pair(tmp_path)
    h1 = _compute_transform_phashes(str(p1))
    h2 = _compute_transform_phashes(str(p2))
    assert "hflip" in h1 and "identity" in h2
    d = _hamming(h1["hflip"], h2["identity"])
    assert d <= 10


def test_best_geo_match_finds_hflip(tmp_path: Path) -> None:
    p1, p2 = _write_pair(tmp_path)
    hit = _best_geo_match(
        _compute_transform_phashes(str(p1)),
        _compute_transform_phashes(str(p2)),
    )
    assert hit is not None
    t_a, t_b, d = hit
    assert d <= 10
    assert "flip" in t_a or "flip" in t_b or t_a != "identity" or t_b != "identity"


def test_image_dup_detects_hflip_pair(tmp_path: Path) -> None:
    p1, p2 = _write_pair(tmp_path)
    # pHash of flipped pair is usually far — geometric pass must catch it.
    images = [
        ExtractedImage(
            page=0,
            index=0,
            xref=1,
            width=160,
            height=120,
            bytes_size=50_000,
            image_path=str(p1),
            phash="0" * 16,  # force primary miss
        ),
        ExtractedImage(
            page=1,
            index=0,
            xref=2,
            width=160,
            height=120,
            bytes_size=50_000,
            image_path=str(p2),
            phash="f" * 16,
        ),
    ]
    doc = ParsedDoc(
        trace_id="geo-t",
        source_path="paper.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )
    result = ImageDuplicateDetector().run(doc)
    assert result.ok
    geo = [
        f
        for f in result.findings
        if (f.raw or {}).get("pass") == "geometric"
    ]
    assert geo, f"expected geometric hit, got {[f.title for f in result.findings]}"
    assert geo[0].severity in ("high", "medium")
    assert (geo[0].raw or {}).get("pubpeer_pattern") == "image_repositioned_reuse"
