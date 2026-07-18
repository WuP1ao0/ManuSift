"""Tests for image_dup multi-hash secondary + region tile bridge.

Covers the gap where whole-image pHash is above threshold but
aHash/dHash or high-variance local tiles still match — the
pattern seen when image_forensics hits and image_dup previously
missed on fraud_representatives_v1.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from manusift.contracts import ExtractedImage, ParsedDoc
from manusift.detectors.image_dup import (
    ImageDuplicateDetector,
    _hamming,
    _region_cell_hashes,
)


def _png_bytes(
    width: int = 128,
    height: int = 128,
    *,
    pattern: str = "A",
    solid: tuple[int, int, int] | None = None,
) -> bytes:
    if solid is not None:
        img = Image.new("RGB", (width, height), color=solid)
    else:
        img = Image.new("RGB", (width, height), color=(240, 240, 240))
        d = ImageDraw.Draw(img)
        if pattern == "A":
            d.rectangle([8, 8, 60, 60], fill=(200, 40, 40))
            d.ellipse([50, 40, 118, 118], fill=(40, 80, 200))
            # High-variance texture patch in corner (gel-like bands).
            for y in range(70, 120, 3):
                d.line([(8, y), (48, y)], fill=(20, 20, 20), width=2)
        elif pattern == "A_crop":
            # Same content, mild crop + shift (secondary multi-hash).
            d.rectangle([12, 10, 64, 62], fill=(200, 40, 40))
            d.ellipse([54, 42, 122, 120], fill=(40, 80, 200))
            for y in range(72, 122, 3):
                d.line([(10, y), (50, y)], fill=(20, 20, 20), width=2)
        elif pattern == "B":
            d.polygon([(10, 10), (110, 20), (60, 110)], fill=(30, 180, 60))
            d.rectangle([80, 80, 120, 120], fill=(180, 30, 180))
        else:  # shared local region only
            d.rectangle([8, 8, 50, 50], fill=(180, 180, 20))
            # Same gel-band patch as pattern A, different rest of frame.
            for y in range(70, 120, 3):
                d.line([(8, y), (48, y)], fill=(20, 20, 20), width=2)
            d.ellipse([70, 10, 120, 60], fill=(10, 10, 200))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _write_png(tmp: Path, name: str, **kwargs) -> Path:
    path = tmp / name
    path.write_bytes(_png_bytes(**kwargs))
    return path


def _img(
    page: int,
    path: Path,
    *,
    phash: str | None,
    index: int = 0,
    width: int = 128,
    height: int = 128,
) -> ExtractedImage:
    return ExtractedImage(
        page=page,
        index=index,
        xref=0,
        phash=phash,
        width=width,
        height=height,
        bytes_size=max(6 * 1024, path.stat().st_size),
        exif={},
        image_path=str(path),
    )


def _doc(images: list[ExtractedImage]) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-multihash",
        source_path="/fake.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )


def test_primary_phash_still_fires_on_identical(tmp_path: Path) -> None:
    p1 = _write_png(tmp_path, "a.png", pattern="A")
    p2 = _write_png(tmp_path, "b.png", pattern="A")
    # Force identical pHash so primary pass fires without decoding.
    hx = "aabbccddeeff0011"
    result = ImageDuplicateDetector().run(
        _doc([_img(0, p1, phash=hx), _img(1, p2, phash=hx)])
    )
    assert len(result.findings) >= 1
    assert result.findings[0].raw.get("pass") == "primary"
    assert result.stats.get("n_primary_hits", 0) >= 1


def test_secondary_multihash_when_phash_diverges(tmp_path: Path) -> None:
    """Far pHash but same raster family → secondary aHash/dHash."""
    p1 = _write_png(tmp_path, "a.png", pattern="A")
    p2 = _write_png(tmp_path, "b.png", pattern="A_crop")
    # Distinct pHashes far above primary threshold (8).
    result = ImageDuplicateDetector().run(
        _doc(
            [
                _img(0, p1, phash="0000000000000000"),
                _img(1, p2, phash="ffffffffffffffff"),
            ]
        )
    )
    secondary = [
        f for f in result.findings if f.raw.get("pass") == "secondary"
    ]
    # Same figure with mild crop should match aHash or dHash.
    assert secondary, (
        f"expected secondary multi-hash hit; got "
        f"{[(f.title, f.raw) for f in result.findings]}"
    )
    assert secondary[0].severity in ("high", "medium")
    assert secondary[0].raw.get("algorithm") in ("ahash", "dhash")


def test_region_bridge_shared_local_texture(tmp_path: Path) -> None:
    """Different overall figures sharing a high-variance tile."""
    p1 = _write_png(tmp_path, "a.png", pattern="A")
    p2 = _write_png(tmp_path, "shared.png", pattern="shared")
    # pHash far apart so only region bridge can fire.
    result = ImageDuplicateDetector().run(
        _doc(
            [
                _img(0, p1, phash="1111111111111111"),
                _img(1, p2, phash="eeeeeeeeeeeeeeee"),
            ]
        )
    )
    region = [f for f in result.findings if f.raw.get("pass") == "region"]
    # Secondary may also catch; at least one of secondary|region.
    non_primary = [
        f
        for f in result.findings
        if f.raw.get("pass") in ("secondary", "region")
    ]
    assert non_primary, (
        f"expected region/secondary bridge; got "
        f"{[(f.title, f.raw) for f in result.findings]}; "
        f"cells_a={_region_cell_hashes(str(p1))}; "
        f"cells_b={_region_cell_hashes(str(p2))}"
    )


def test_distinct_patterns_do_not_force_primary(tmp_path: Path) -> None:
    p1 = _write_png(tmp_path, "a.png", pattern="A")
    p2 = _write_png(tmp_path, "b.png", pattern="B")
    result = ImageDuplicateDetector().run(
        _doc(
            [
                _img(0, p1, phash="0123456789abcdef"),
                _img(1, p2, phash="fedcba9876543210"),
            ]
        )
    )
    primary = [f for f in result.findings if f.raw.get("pass") == "primary"]
    assert primary == []


def test_hamming_hex() -> None:
    assert _hamming("00", "00") == 0
    assert _hamming("00", "ff") == 8
    assert _hamming("0", "00") > 0  # length mismatch upper bound
