"""Tests for the SSIM image duplicate detector + similarity matrix
tool (P1.4-P1.5).

The tests build small images
in memory, save them as
PNGs, and run the detector
and tool against them. The
SSIM threshold is 0.85;
two images that are
visually "the same" should
score above the threshold.
"""
from __future__ import annotations

import json
import tempfile

import numpy as np
from PIL import Image

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
        width=128,
        height=128,
        bytes_size=0,
        phash="",
        image_path=path,
    )


def _doc_with(images):
    from manusift.contracts import ParsedDoc
    return ParsedDoc(
        trace_id="t-ssim",
        source_path="",
        text_blocks=[],
        images=images,
        metadata={},
    )


# ---------- 1. detector name ----------

def test_ssim_detector_name() -> None:
    from manusift.detectors import SsimDuplicateDetector
    assert SsimDuplicateDetector().name == "image_ssim"


# ---------- 2. identical images produce a finding ----------

def test_identical_images_flagged() -> None:
    from manusift.detectors import SsimDuplicateDetector
    arr = np.random.default_rng(0).integers(
        0, 255, (128, 128, 3), dtype=np.uint8
    )
    path = _write_png(arr)
    doc = _doc_with([_record(1, path), _record(2, path)])
    result = SsimDuplicateDetector().run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    ev = json.loads(f.evidence)
    # Identical images have
    # SSIM = 1.0.
    assert ev["ssim_score"] >= 0.99


# ---------- 3. very different images not flagged ----------

def test_different_images_not_flagged() -> None:
    from manusift.detectors import SsimDuplicateDetector
    rng = np.random.default_rng(0)
    a = rng.integers(0, 50, (128, 128, 3), dtype=np.uint8)
    b = rng.integers(200, 255, (128, 128, 3), dtype=np.uint8)
    pa = _write_png(a)
    pb = _write_png(b)
    doc = _doc_with([_record(1, pa), _record(2, pb)])
    result = SsimDuplicateDetector().run(doc)
    assert result.findings == []


# ---------- 4. resize is handled ----------

def test_resize_still_detected() -> None:
    """A 128x128 image and a
    64x64 resized copy of
    itself should be flagged:
    the SSIM is computed
    after resizing the larger
    image to the smaller's
    size."""
    from manusift.detectors import SsimDuplicateDetector
    arr = np.random.default_rng(0).integers(
        0, 255, (128, 128, 3), dtype=np.uint8
    )
    pa = _write_png(arr)
    # Resize to 64x64.
    img = Image.fromarray(arr).resize(
        (64, 64), Image.LANCZOS
    )
    pb = _write_png(np.array(img))
    doc = _doc_with([_record(1, pa), _record(2, pb)])
    result = SsimDuplicateDetector().run(doc)
    # The 64x64 version is a
    # downsampled copy, so
    # SSIM should still be
    # high.
    assert len(result.findings) == 1
    assert json.loads(result.findings[0].evidence)[
        "ssim_score"
    ] >= 0.85


# ---------- 5. corrupted image is silent ----------

def test_corrupted_image_silent() -> None:
    from manusift.detectors import SsimDuplicateDetector
    bogus = _record(1, "/no/such/file.png")
    doc = _doc_with([bogus, bogus])
    result = SsimDuplicateDetector().run(doc)
    assert result.findings == []


# ---------- 6. truncation finding ----------

def test_truncation_finding() -> None:
    from manusift.detectors import SsimDuplicateDetector
    arr = np.random.default_rng(0).integers(
        0, 255, (32, 32, 3), dtype=np.uint8
    )
    path = _write_png(arr)
    # More images than the
    # cap.
    images = [
        _record(1, path) for _ in range(40)
    ]
    doc = _doc_with(images)
    result = SsimDuplicateDetector().run(doc)
    # A "truncated" finding
    # must be present.
    truncated = [
        f
        for f in result.findings
        if "truncated" in f.title.lower()
    ]
    assert len(truncated) == 1


# ---------- 7. similarity matrix tool ----------

def test_similarity_matrix_tool_returns_matrix() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.similarity_matrix import (
        ImageSimilarityMatrixTool,
    )
    arr = np.random.default_rng(0).integers(
        0, 255, (128, 128, 3), dtype=np.uint8
    )
    path = _write_png(arr)
    images = [_record(1, path), _record(2, path)]
    ctx = ToolContext(trace_id="t")
    out = ImageSimilarityMatrixTool().execute(
        {"images": images}, ctx
    )
    data = json.loads(out)
    assert "matrix" in data
    assert len(data["matrix"]) == 2
    assert data["image_count"] == 2
    # Identical images have
    # distance 0.
    assert data["matrix"][0][1] == 0.0


def test_similarity_matrix_tool_empty() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.similarity_matrix import (
        ImageSimilarityMatrixTool,
    )
    ctx = ToolContext(trace_id="t")
    out = ImageSimilarityMatrixTool().execute(
        {"images": []}, ctx
    )
    data = json.loads(out)
    assert data["matrix"] == []
    assert data["image_count"] == 0


def test_similarity_matrix_tool_no_images() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.similarity_matrix import (
        ImageSimilarityMatrixTool,
    )
    ctx = ToolContext(trace_id="t")
    out = ImageSimilarityMatrixTool().execute({}, ctx)
    data = json.loads(out)
    assert "error" in data


def test_iter_registered_tools_yields_similarity_tool() -> None:
    from manusift.tools import iter_registered_tools
    names = {t.name for t in iter_registered_tools()}
    assert "image_similarity_matrix" in names


# ---------- 8. helpers ----------

def test_ssim_helper_identical() -> None:
    from manusift.detectors.ssim import _ssim_one_pair
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (64, 64), dtype=np.uint8)
    score = _ssim_one_pair(a, a)
    assert score > 0.99


def test_ssim_helper_different() -> None:
    from manusift.detectors.ssim import _ssim_one_pair
    rng = np.random.default_rng(0)
    a = rng.integers(0, 50, (64, 64), dtype=np.uint8)
    b = rng.integers(200, 255, (64, 64), dtype=np.uint8)
    score = _ssim_one_pair(a, b)
    assert score < 0.5


def test_read_image_gray_returns_array() -> None:
    from manusift.detectors.ssim import _read_image_gray
    arr = np.full((64, 64, 3), 128, dtype=np.uint8)
    path = _write_png(arr)
    gray = _read_image_gray(path)
    assert gray is not None
    assert gray.shape == (64, 64)


def test_read_image_gray_bad_path() -> None:
    from manusift.detectors.ssim import _read_image_gray
    assert _read_image_gray("/no/such/file.png") is None
