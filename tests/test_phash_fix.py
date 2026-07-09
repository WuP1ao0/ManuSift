"""Tests for the pHash fix (R-audit, 2026-06-10).

The previous
``_compute_phash`` used a
custom 8x8 average-hash
that returned
``"0000000000000000"`` for
every solid-white icon,
causing the duplicate
detector to flag every
pair of blank icons as a
"duplicate". This test
pins the new behaviour:

  * Real images get a
    proper 16-char DCT-
    based pHash from
    ``imagehash.phash``.

  * Solid-color images
    return ``None`` (the
    detector skips them).

  * Tiny images (smaller
    than 32x32) return
    ``None`` (too small
    for pHash to be
    meaningful).

  * Decode failures
    return ``None`` rather
    than raising.

The detector-level test
covers the contract that
``None`` is treated as
"skip, do not flag as
duplicate".
"""
from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from manusift.detectors.image_dup import ImageDuplicateDetector
from manusift.ingest.pdf import _compute_phash, _MIN_PHASH_SIDE
from manusift.contracts import ExtractedImage


# ---------- helpers ----------


def _img_bytes(
    width: int,
    height: int,
    *,
    solid: tuple[int, int, int] | None = None,
    pattern: bool = False,
) -> bytes:
    """Build an in-memory PNG.

    ``solid=(R,G,B)`` makes
    a solid-color image. If
    ``pattern=True``, draws
    a rectangle + ellipse so
    the image has more than
    one unique luminance
    value (i.e. not
    solid-color).
    """
    if pattern:
        img = Image.new(
            "RGB", (width, height), color=(255, 255, 255)
        )
        d = ImageDraw.Draw(img)
        d.rectangle(
            [4, 4, width // 2, height // 2],
            fill=(200, 50, 50),
        )
        d.ellipse(
            [width // 2, height // 4, width - 4, height - 4],
            fill=(50, 100, 200),
        )
    else:
        img = Image.new(
            "RGB",
            (width, height),
            color=solid or (255, 255, 255),
        )
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------- 1. _compute_phash returns a real hash for real images ----------


def test_compute_phash_real_image_returns_16_hex() -> None:
    """A 200x200 image with a
    rectangle + ellipse
    pattern returns a 16-
    character lowercase hex
    string (the
    ``imagehash.phash``
    output format).
    """
    h = _compute_phash(_img_bytes(200, 200, pattern=True))
    assert h is not None
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_phash_identical_images_match() -> None:
    """Two byte-identical
    images hash to the same
    value (DCT-pHash is
    deterministic)."""
    a = _img_bytes(100, 100, pattern=True)
    b = _img_bytes(100, 100, pattern=True)
    assert _compute_phash(a) == _compute_phash(b)


def test_compute_phash_different_images_likely_differ() -> None:
    """Two images with very
    different content hash
    to different values (we
    do not pin a specific
    bit distance because
    the DCT algorithm could
    collide on small
    differences; we just
    assert they are not
    byte-equal)."""
    a = _img_bytes(200, 200, pattern=True)
    # Invert the colours
    # for image b.
    img = Image.new("RGB", (200, 200), color=(0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle(
        [4, 4, 100, 100], fill=(55, 205, 205)
    )
    d.ellipse(
        [100, 50, 196, 196], fill=(205, 155, 55)
    )
    buf = io.BytesIO()
    img.save(buf, "PNG")
    b = buf.getvalue()
    assert _compute_phash(a) != _compute_phash(b)


# ---------- 2. degenerate filters ----------


def test_compute_phash_solid_white_returns_none() -> None:
    """A solid-white image
    has a single unique
    luminance value, so
    pHash is meaningless.
    The detector would
    otherwise flag every
    pair of solid-white
    icons as a duplicate.
    This is the bug we
    fixed.
    """
    h = _compute_phash(
        _img_bytes(200, 200, solid=(255, 255, 255))
    )
    assert h is None


def test_compute_phash_solid_black_returns_none() -> None:
    """Solid black is also
    filtered."""
    h = _compute_phash(
        _img_bytes(200, 200, solid=(0, 0, 0))
    )
    assert h is None


def test_compute_phash_solid_red_returns_none() -> None:
    """A single-colour
    *non-white* image is
    filtered too. The bug
    pattern was not specific
    to white."""
    h = _compute_phash(
        _img_bytes(200, 200, solid=(200, 50, 50))
    )
    assert h is None


def test_compute_phash_too_small_returns_none() -> None:
    """An image smaller than
    ``_MIN_PHASH_SIDE`` (16)
    on either side cannot
    be meaningfully pHashed
    (``imagehash.phash``
    internally resizes to
    32x32; below 16 px, the
    resize destroys all
    signal)."""
    h = _compute_phash(
        _img_bytes(8, 8, pattern=True)
    )
    assert h is None


def test_compute_phash_too_small_one_axis_returns_none() -> None:
    """An image that is
    narrow but tall (or
    vice versa) is also
    filtered -- the limit
    applies to both
    axes."""
    h = _compute_phash(
        _img_bytes(200, 8, pattern=True)
    )
    assert h is None


def test_compute_phash_at_boundary_is_accepted() -> None:
    """Exactly ``_MIN_PHASH_SIDE``
    on both axes is the
    boundary: it must
    pass. (The check is
    strict-less-than; the
    boundary itself is
    allowed.)"""
    img = Image.new(
        "RGB",
        (_MIN_PHASH_SIDE, _MIN_PHASH_SIDE),
        color=(255, 255, 255),
    )
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, 8, 8], fill=(200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    h = _compute_phash(buf.getvalue())
    assert h is not None
    assert len(h) == 16


def test_compute_phash_above_boundary_is_accepted() -> None:
    """A 18x18 chart marker
    -- the kind of small
    icon that appears in
    Nature / Science
    figure legends -- must
    hash successfully. The
    previous 32-px
    threshold dropped these
    and caused the
    duplicate detector to
    miss real findings in
    the Nature pilot.
    """
    img = Image.new(
        "RGB",
        (18, 18),
        color=(255, 255, 255),
    )
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, 16, 16], fill=(200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    h = _compute_phash(buf.getvalue())
    assert h is not None
    assert len(h) == 16


def test_compute_phash_corrupt_bytes_returns_none() -> None:
    """Garbage bytes that
    Pillow cannot decode
    return ``None`` rather
    than raising -- the
    ingest layer must keep
    moving on a single
    bad image.
    """
    assert _compute_phash(b"not an image") is None
    assert _compute_phash(b"") is None
    assert _compute_phash(b"\x00\x01\x02\x03") is None


# ---------- 3. detector skips None ----------


def _extracted(
    *,
    phash: str | None,
    width: int = 100,
    height: int = 100,
    page: int = 0,
    index: int = 0,
) -> ExtractedImage:
    return ExtractedImage(
        page=page,
        index=index,
        xref=index,
        phash=phash,
        width=width,
        height=height,
        bytes_size=10_000,
        exif={},
        image_path=None,
    )


def test_detector_skips_pairs_with_none_phash() -> None:
    """Two images with
    ``phash=None`` (i.e.
    filtered as
    degenerate) must NOT
    be flagged as
    duplicates. This is
    the heart of the
    fix: the old detector
    would have produced
    one finding for the
    pair, because both
    None-vs-string-comparison
    would have crashed
    and the old
    all-zero string would
    have matched
    itself.
    """
    from manusift.contracts import ParsedDoc

    doc = ParsedDoc(
        trace_id="t1",
        source_path="/tmp/x.pdf",
        text_blocks=[],
        metadata={},
        images=[
            _extracted(phash=None, page=0, index=0),
            _extracted(phash=None, page=0, index=1),
        ],
    )
    det = ImageDuplicateDetector()
    result = det.run(doc)
    assert result.findings == [], (
        "expected no findings for two degenerate images, "
        f"got {len(result.findings)}"
    )


def test_detector_skips_mixed_none_and_real() -> None:
    """One real image + one
    degenerate image: the
    pair is skipped (we
    cannot meaningfully
    compare)."""
    from manusift.contracts import ParsedDoc

    doc = ParsedDoc(
        trace_id="t1",
        source_path="/tmp/x.pdf",
        text_blocks=[],
        metadata={},
        images=[
            _extracted(phash="ff81113c1991c3ff", page=0, index=0),
            _extracted(phash=None, page=0, index=1),
        ],
    )
    det = ImageDuplicateDetector()
    result = det.run(doc)
    assert result.findings == []


def test_detector_real_duplicate_pair_still_fires() -> None:
    """Two real images with
    the same pHash
    (Hamming distance 0)
    are still flagged --
    the fix must not
    break the happy
    path."""
    from manusift.contracts import ParsedDoc

    doc = ParsedDoc(
        trace_id="t1",
        source_path="/tmp/x.pdf",
        text_blocks=[],
        metadata={},
        images=[
            _extracted(
                phash="ff81113c1991c3ff",
                page=0,
                index=0,
            ),
            _extracted(
                phash="ff81113c1991c3ff",
                page=0,
                index=1,
            ),
        ],
    )
    det = ImageDuplicateDetector()
    result = det.run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.detector == "image_dup"
    assert f.severity == "high"


def test_detector_empty_string_phash_is_skipped() -> None:
    """Test fixtures use
    ``phash=""`` to mean
    "no hash available".
    The detector must
    treat that the same
    way as ``None``."""
    from manusift.contracts import ParsedDoc

    doc = ParsedDoc(
        trace_id="t1",
        source_path="/tmp/x.pdf",
        text_blocks=[],
        metadata={},
        images=[
            _extracted(phash="", page=0, index=0),
            _extracted(phash="", page=0, index=1),
        ],
    )
    det = ImageDuplicateDetector()
    result = det.run(doc)
    assert result.findings == []