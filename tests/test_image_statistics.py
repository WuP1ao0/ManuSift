"""Tests for the image-statistics detector (T11).

The detector flags figures
that look synthesised rather
than photographed. The tests
build three different kinds
of synthetic image and check
the detector's verdict for
each.
"""
from __future__ import annotations

import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import pytest


def _write_png(arr: np.ndarray) -> str:
    f = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False
    )
    Image.fromarray(arr).save(f, format="PNG")
    f.close()
    return f.name


def _record(page: int, path: str):
    from manusift.contracts import ExtractedImage
    return ExtractedImage(
        page=page,
        index=0,
        xref=0,
        width=256,
        height=256,
        bytes_size=0,
        phash="",
        image_path=path,
    )


def _doc_with(images):
    from manusift.contracts import ParsedDoc
    return ParsedDoc(
        trace_id="t-stats",
        source_path="/tmp/fake.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )


# ---------- 1. detector name and registration ----------

def test_image_statistics_detector_name() -> None:
    from manusift.detectors import ImageStatisticsDetector
    assert (
        ImageStatisticsDetector().name
        == "image_statistics"
    )


# ---------- 2. natural photo is not flagged ----------

def test_natural_photo_not_flagged() -> None:
    """A natural photo (smooth
    colour gradients, many
    distinct colours, normal
    edge density) is not
    flagged."""
    from manusift.detectors import ImageStatisticsDetector
    # Build a "natural"-looking
    # image: continuous
    # gradients + a touch of
    # noise.
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:256, 0:256]
    r = ((xx + yy) % 256).astype(np.uint8)
    g = ((xx * 2 + yy) % 256).astype(np.uint8)
    b = ((xx + yy * 2) % 256).astype(np.uint8)
    arr = np.stack([r, g, b], axis=-1)
    arr = (
        arr.astype(np.int32)
        + rng.normal(0, 8, arr.shape)
    ).clip(0, 255).astype(np.uint8)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ImageStatisticsDetector().run(doc)
    # The detector should not
    # flag a natural photo.
    assert result.findings == []


# ---------- 3. synthetic plot is flagged ----------

def test_synthetic_plot_is_flagged() -> None:
    """A matplotlib-style plot
    (white background, a few
    coloured markers, lots of
    edges) has low entropy, low
    colour count, and high
    edge density -- all three
    signals flagged."""
    from manusift.detectors import ImageStatisticsDetector
    # White background with a
    # bar chart.
    img = Image.new("RGB", (256, 256), "white")
    d = ImageDraw.Draw(img)
    for x in range(20, 240, 30):
        d.rectangle([x, 200 - (x % 90), x + 20, 200], fill="blue")
    # Add an x-axis line.
    d.line([(10, 200), (246, 200)], fill="black", width=1)
    arr = np.array(img)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ImageStatisticsDetector().run(doc)
    assert len(result.findings) >= 1
    f = result.findings[0]
    # At least two of the three
    # signals are flagged.
    import json
    ev = json.loads(f.evidence)
    assert len(ev["flagged_signals"]) >= 2


# ---------- 4. corrupted image is skipped ----------

def test_corrupted_image_does_not_crash() -> None:
    from manusift.detectors import ImageStatisticsDetector
    bogus = _record(
        1, "/nonexistent/path/for/testing.png"
    )
    doc = _doc_with([bogus])
    result = ImageStatisticsDetector().run(doc)
    assert result.findings == []


# ---------- 5. small image is skipped ----------

def test_small_image_is_skipped() -> None:
    """An image smaller than 64x64
    is too small for any
    statistics to be meaningful;
    the detector skips it."""
    from manusift.detectors import ImageStatisticsDetector
    arr = np.full((32, 32, 3), 128, dtype=np.uint8)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ImageStatisticsDetector().run(doc)
    assert result.findings == []


# ---------- 6. flat image is flagged ----------

def test_flat_image_with_one_logo_is_flagged() -> None:
    """A flat-colour background
    with a single small logo is
    the textbook 'synthesised
    figure' case: low entropy,
    low colour count, and low
    edge density (because the
    logo is tiny)."""
    from manusift.detectors import ImageStatisticsDetector
    img = Image.new("RGB", (256, 256), "red")
    d = ImageDraw.Draw(img)
    # Tiny white logo in the
    # middle.
    d.rectangle([120, 120, 136, 136], fill="white")
    arr = np.array(img)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ImageStatisticsDetector().run(doc)
    # Two or three signals
    # flagged.
    assert len(result.findings) >= 1
    import json
    ev = json.loads(result.findings[0].evidence)
    assert "histogram_entropy" in ev["signals"]
    assert "edge_density" in ev["signals"]
    assert "color_count" in ev["signals"]


# ---------- 7. helper functions ----------

def test_histogram_entropy_of_uniform_is_8() -> None:
    from manusift.detectors.image_statistics import (
        _histogram_entropy,
    )
    # Build a 256x256 image
    # where every grayscale
    # value appears exactly
    # 256 times -- uniform
    # histogram.
    gray = np.arange(256, dtype=np.uint8)
    gray = np.tile(gray, 256)  # 256 * 256 values
    gray = gray.reshape(256, 256)
    assert abs(_histogram_entropy(gray) - 8.0) < 0.01


def test_histogram_entropy_of_constant_is_0() -> None:
    from manusift.detectors.image_statistics import (
        _histogram_entropy,
    )
    gray = np.full((64, 64), 128, dtype=np.uint8)
    assert _histogram_entropy(gray) == 0.0


def test_color_count_of_uniform_image_is_1() -> None:
    from manusift.detectors.image_statistics import _color_count
    arr = np.full((64, 64, 3), 128, dtype=np.uint8)
    assert _color_count(arr) == 1
