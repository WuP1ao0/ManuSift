"""Tests for the panel-segmentation detector (P3.1).

The detector segments a
multi-panel figure into
its component panels and
compares each pair via
SSIM. The tests build
synthetic multi-panel
images in memory and
assert on the findings.
"""
from __future__ import annotations

import importlib.util
import os
import json
import tempfile

import pytest

if os.environ.get("MANUSIFT_RUN_VISION", "").strip().lower() not in {
    "1",
    "true",
    "yes",
    "on",
}:
    pytest.skip("requires MANUSIFT_RUN_VISION=1", allow_module_level=True)
if importlib.util.find_spec("cv2") is None:
    pytest.skip("requires OpenCV (cv2)", allow_module_level=True)

import numpy as np
from PIL import Image, ImageDraw

pytestmark = pytest.mark.vision


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
        width=400,
        height=300,
        bytes_size=0,
        phash="",
        image_path=path,
    )


def _doc_with(images):
    from manusift.contracts import ParsedDoc
    return ParsedDoc(
        trace_id="t-panel",
        source_path="",
        text_blocks=[],
        images=images,
        metadata={},
    )


def _two_panel_image(
    width: int = 400,
    height: int = 300,
    duplicate: bool = False,
) -> np.ndarray:
    """Render a 2-panel figure:
    two side-by-side square
    panels on a black
    background. If
    ``duplicate`` is True,
    the second panel is a
    copy of the first."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    # White panel 1.
    arr[20:160, 20:160] = 220
    if duplicate:
        # Panel 2 is a
        # duplicate of
        # panel 1.
        arr[20:160, 200:340] = 220
    else:
        # Panel 2 is a
        # different image.
        rng = np.random.default_rng(0)
        arr[20:160, 200:340] = rng.integers(
            100, 200, (140, 140, 3), dtype=np.uint8
        )
    return arr


# ---------- 1. detector name ----------

def test_panel_detector_name() -> None:
    from manusift.detectors import PanelSegmentationDetector
    assert (
        PanelSegmentationDetector().name
        == "panel_duplicate"
    )


# ---------- 2. two distinct panels produce no findings ----------

def test_two_distinct_panels_no_finding() -> None:
    from manusift.detectors import PanelSegmentationDetector
    arr = _two_panel_image(duplicate=False)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = PanelSegmentationDetector().run(doc)
    # The two panels have
    # different content;
    # SSIM should be low.
    assert result.findings == []


# ---------- 3. two duplicate panels are flagged ----------

def test_two_duplicate_panels_flagged() -> None:
    from manusift.detectors import PanelSegmentationDetector
    arr = _two_panel_image(duplicate=True)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = PanelSegmentationDetector().run(doc)
    # Identical panels have
    # SSIM = 1.0.
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "panel" in f.title.lower()
    assert "duplicate" in f.title.lower()


# ---------- 4. corrupted image is silent ----------

def test_corrupted_image_silent() -> None:
    from manusift.detectors import PanelSegmentationDetector
    bogus = _record(1, "/no/such/file.png")
    doc = _doc_with([bogus])
    result = PanelSegmentationDetector().run(doc)
    assert result.findings == []


# ---------- 5. single panel image is silent ----------

def test_single_panel_silent() -> None:
    """A figure with one
    panel cannot have a
    duplicate, so the
    detector must be
    silent."""
    from manusift.detectors import PanelSegmentationDetector
    arr = np.full((300, 400, 3), 200, dtype=np.uint8)
    # Add a single white
    # rectangle.
    arr[20:160, 20:160] = 255
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = PanelSegmentationDetector().run(doc)
    # The detector segments
    # but cannot find
    # duplicate -- silently
    # no finding.
    assert result.findings == []


# ---------- 6. helpers ----------

def test_segment_panels_basic() -> None:
    """A synthetic figure with
    two white panels on a
    black background
    should segment into two
    boxes."""
    from manusift.detectors.panel_segmentation import (
        _segment_panels,
    )
    arr = _two_panel_image()
    gray = np.array(
        Image.fromarray(arr).convert("L")
    )
    boxes = _segment_panels(gray)
    assert len(boxes) == 2


def test_segment_panels_uniform_is_empty() -> None:
    """A uniform image has no
    panels. The function
    should return an empty
    list rather than
    crashing."""
    from manusift.detectors.panel_segmentation import (
        _segment_panels,
    )
    arr = np.full((300, 400), 128, dtype=np.uint8)
    boxes = _segment_panels(arr)
    assert boxes == []


# ---------- 7. evidence is JSON ----------

def test_evidence_is_json() -> None:
    from manusift.detectors import PanelSegmentationDetector
    arr = _two_panel_image(duplicate=True)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = PanelSegmentationDetector().run(doc)
    for f in result.findings:
        ev = json.loads(f.evidence)
        assert "ssim_score" in ev
        assert "panel_a" in ev
        assert "panel_b" in ev
