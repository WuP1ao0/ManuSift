"""Tests for the chart-data extractor (P3.2).

The detector reads each
image in the document,
tries to find the chart
baseline, then finds the
bars. The tests build
synthetic bar charts and
assert on the extracted
bar heights.
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
        trace_id="t-chart",
        source_path="",
        text_blocks=[],
        images=images,
        metadata={},
    )


def _bar_chart_image(
    bar_heights: list[int],
    width: int = 400,
    height: int = 300,
    baseline_y: int = 250,
) -> np.ndarray:
    """Render a simple bar
    chart: a white background
    with a black baseline and
    a few dark grey bars on
    top. The bars are evenly
    spaced; their heights are
    given in pixel units."""
    img = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(img)
    # Baseline.
    d.line(
        [(20, baseline_y), (width - 20, baseline_y)],
        fill="black",
        width=2,
    )
    # Bars.
    n = len(bar_heights)
    if n == 0:
        return np.array(img)
    # Spread bars evenly
    # across the chart
    # width.
    bar_width = 30
    spacing = (width - 40) // n
    for i, h in enumerate(bar_heights):
        x_left = 30 + i * spacing
        x_right = x_left + bar_width
        y_top = baseline_y - h
        d.rectangle(
            [x_left, y_top, x_right, baseline_y],
            fill="grey",
        )
    return np.array(img)


# ---------- 1. detector name ----------

def test_chart_detector_name() -> None:
    from manusift.detectors import ChartDataExtractorDetector
    assert (
        ChartDataExtractorDetector().name
        == "chart_data_extract"
    )


# ---------- 2. simple bar chart is detected ----------

def test_simple_bar_chart_detected() -> None:
    from manusift.detectors import ChartDataExtractorDetector
    arr = _bar_chart_image([100, 50, 75])
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ChartDataExtractorDetector().run(doc)
    # 3 bars in the chart.
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    assert len(ev["bars"]) == 3


# ---------- 3. bar heights are extracted in pixel units ----------

def test_bar_heights_extracted() -> None:
    from manusift.detectors import ChartDataExtractorDetector
    arr = _bar_chart_image([120, 80, 40, 20])
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ChartDataExtractorDetector().run(doc)
    ev = json.loads(result.findings[0].evidence)
    heights = sorted(ev["bars"], reverse=True)
    # The largest bar
    # should be the first
    # one.
    assert heights[0] >= 100
    assert heights[-1] <= 50


# ---------- 4. no bars in a non-chart image ----------

def test_non_chart_image_silent() -> None:
    from manusift.detectors import ChartDataExtractorDetector
    # Solid white image.
    arr = np.full((300, 400, 3), 255, dtype=np.uint8)
    path = _write_png(arr)
    doc = _doc_with([_record(1, path)])
    result = ChartDataExtractorDetector().run(doc)
    assert result.findings == []


# ---------- 5. corrupted image is silent ----------

def test_corrupted_image_silent() -> None:
    from manusift.detectors import ChartDataExtractorDetector
    bogus = _record(1, "/no/such/file.png")
    doc = _doc_with([bogus])
    result = ChartDataExtractorDetector().run(doc)
    assert result.findings == []


# ---------- 6. helpers ----------

def test_find_baseline_helper() -> None:
    from manusift.detectors.chart_data_extract import (
        _find_baseline,
    )
    import cv2
    arr = np.full((300, 400), 255, dtype=np.uint8)
    arr[250, 20:380] = 0
    baseline = _find_baseline(arr)
    # The baseline is around
    # y=250 (within a few
    # pixels).
    assert baseline is not None
    assert 240 <= baseline <= 260


def test_find_baseline_no_line() -> None:
    from manusift.detectors.chart_data_extract import (
        _find_baseline,
    )
    arr = np.full((300, 400), 255, dtype=np.uint8)
    baseline = _find_baseline(arr)
    # No horizontal line in
    # the image: function
    # returns None.
    assert baseline is None


def test_extract_chart_returns_dict() -> None:
    from manusift.detectors.chart_data_extract import (
        _extract_chart,
    )
    arr = _bar_chart_image([100, 50])
    path = _write_png(arr)
    data = _extract_chart(path)
    assert "bars" in data
    assert "baseline" in data
    assert isinstance(data["bars"], list)


def test_extract_chart_bad_path() -> None:
    from manusift.detectors.chart_data_extract import (
        _extract_chart,
    )
    data = _extract_chart("/no/such/file.png")
    assert data["bars"] == []
    assert data["baseline"] is None
