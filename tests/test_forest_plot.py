"""Tests for the forest-plot rule checker (v1).

The tests render synthetic forest plots with PIL (a vertical
dashed null line, evenly spaced CI whiskers, weight squares)
and pair them with text blocks carrying the printed numeric
column ("1.23 [0.98, 1.55]"). No real PDFs, no network, no
models: the numeric column comes from the text layer.
"""
from __future__ import annotations

import json
import math

import numpy as np
from PIL import Image, ImageDraw

# Log-axis pixel mapping shared by the renderer and the tests:
# x = NULL_X + SCALE * log10(value) / log10(2), so the null
# value 1.0 sits at NULL_X and the axis spans [0.5, 2.0].
NULL_X = 300
SCALE = 200
IMG_W = 600
IMG_H = 400


def _x(value: float) -> int:
    return int(round(NULL_X + SCALE * math.log10(value) / math.log10(2)))


def _write_png(arr: np.ndarray, tmp_path, name: str = "fp.png") -> str:
    path = tmp_path / name
    Image.fromarray(arr).save(path, format="PNG")
    return str(path)


def _image_record(page: int, path: str):
    from manusift.contracts import ExtractedImage

    return ExtractedImage(
        page=page,
        index=0,
        xref=0,
        phash="",
        width=IMG_W,
        height=IMG_H,
        bytes_size=0,
        image_path=path,
    )


def _doc(text_by_page: dict[int, str], images=None):
    from manusift.contracts import ParsedDoc, TextBlock

    blocks = [
        TextBlock(page=p, bbox=(0.0, 0.0, 0.0, 0.0), text=t)
        for p, t in text_by_page.items()
    ]
    return ParsedDoc(
        trace_id="t-forest",
        source_path="",
        text_blocks=blocks,
        images=images or [],
        metadata={},
    )


def _forest_plot_image(rows: list[tuple[float, float, float]], y0=80, dy=40):
    """Render a synthetic forest plot. ``rows`` are
    ``(est, lo, hi)`` triples drawn on the log axis; returns the
    RGB array. Rows whose whisker must *not* match the text can
    pass explicit pixel spans via ``_forest_plot_image_custom``.
    """
    return _forest_plot_image_custom(
        [(_x(lo), _x(hi), y0 + i * dy, _x(est)) for i, (est, lo, hi) in enumerate(rows)]
    )


def _forest_plot_image_custom(segments: list[tuple[int, int, int, int]]):
    """Render from explicit pixel spans ``(x1, x2, y, x_est)``."""
    img = Image.new("RGB", (IMG_W, IMG_H), "white")
    d = ImageDraw.Draw(img)
    # Vertical dashed null line, ~60% dark coverage of the
    # interior height.
    y = 20
    while y < IMG_H - 20:
        d.line(
            [(NULL_X, y), (NULL_X, min(y + 6, IMG_H - 20))],
            fill="black",
            width=2,
        )
        y += 10
    for x1, x2, y, x_est in segments:
        d.line([(x1, y), (x2, y)], fill="black", width=2)
        d.rectangle([x_est - 4, y - 4, x_est + 4, y + 4], fill="black")
    return np.array(img)


# A normal, internally consistent plot: 4 rows, some CIs cross
# the null value, all printed CIs bracket their estimate and are
# symmetric in log space.
GOOD_TRIPLES = [
    (1.23, 0.98, 1.55),
    (0.85, 0.60, 1.20),
    (1.60, 1.20, 2.10),
    (0.70, 0.50, 0.98),
]

GOOD_TEXT = (
    "Figure 2. Forest plot of Odds Ratio (OR) with 95% CI and weight.\n"
    "Smith 2020  1.23 [0.98, 1.55]\n"
    "Jones 2021  0.85 [0.60, 1.20]\n"
    "Lee 2022    1.60 [1.20, 2.10]\n"
    "Wang 2023   0.70 [0.50, 0.98]\n"
)


def _good_doc(tmp_path):
    arr = _forest_plot_image(GOOD_TRIPLES)
    path = _write_png(arr, tmp_path)
    return _doc({1: GOOD_TEXT}, images=[_image_record(1, path)])


def _run(doc):
    from manusift.detectors.forest_plot import ForestPlotDetector

    return ForestPlotDetector().run(doc)


def _kinds(result):
    return [f.raw.get("kind") for f in result.findings]


# ---------- 1. detector name ----------

def test_detector_name() -> None:
    from manusift.detectors.forest_plot import ForestPlotDetector

    assert ForestPlotDetector().name == "forest_plot"


# ---------- 2. normal plot: no high / no medium ----------

def test_normal_plot_no_high(tmp_path) -> None:
    result = _run(_good_doc(tmp_path))
    assert result.ok
    severities = {f.severity for f in result.findings}
    assert "high" not in severities
    assert "medium" not in severities
    # But the plot *is* recognised, with a summary finding.
    assert "forest_plot_detected" in _kinds(result)
    assert "forest_plot_summary" in _kinds(result)
    summary = next(
        f for f in result.findings if f.raw.get("kind") == "forest_plot_summary"
    )
    assert summary.raw["forest_plots_detected"] == 1
    assert summary.raw["numeric_rows_parsed"] == 4
    detected = next(
        f for f in result.findings if f.raw.get("kind") == "forest_plot_detected"
    )
    # All four recognition signals fire on the synthetic plot.
    assert detected.raw["signals"] == {
        "null_line": True,
        "ci_segments": True,
        "keywords": True,
        "numeric_column": True,
    }
    assert detected.raw["confidence"] == 1.0


# ---------- 3. CI order violation -> high ----------

def test_order_violation_high(tmp_path) -> None:
    # Estimate above the upper CI bound: a direct fabrication /
    # copy-paste signal. Text-only page (keywords + numeric
    # column are enough for recognition).
    text = (
        "Forest plot of hazard ratio with 95% CI.\n"
        "Smith 2020  1.23 [0.98, 1.55]\n"
        "Jones 2021  1.80 [0.60, 1.20]\n"
    )
    result = _run(_doc({2: text}))
    highs = [f for f in result.findings if f.severity == "high"]
    assert len(highs) == 1
    assert highs[0].raw["kind"] == "ci_order_violation"
    assert highs[0].raw["row"] == 2
    ev = json.loads(highs[0].evidence)
    assert ev["estimate"] == 1.80


def test_order_violation_lo_gt_est_high(tmp_path) -> None:
    text = (
        "Forest plot of risk ratio (RR).\n"
        "Smith 2020  0.50 [0.98, 1.55]\n"
        "Jones 2021  0.85 [0.60, 1.20]\n"
    )
    result = _run(_doc({1: text}))
    highs = [f for f in result.findings if f.severity == "high"]
    assert len(highs) == 1
    assert highs[0].raw["kind"] == "ci_order_violation"
    assert highs[0].raw["row"] == 1


# ---------- 4. log-space asymmetry -> medium ----------

def test_asymmetry_medium(tmp_path) -> None:
    # 1.50 [0.70, 1.55]: log-midpoint of the CI is ~1.04, far
    # from the printed estimate -> transcription-error signal.
    text = (
        "Forest plot of odds ratio with 95% CI.\n"
        "Smith 2020  1.23 [0.98, 1.55]\n"
        "Jones 2021  1.50 [0.70, 1.55]\n"
    )
    result = _run(_doc({1: text}))
    mediums = [
        f
        for f in result.findings
        if f.raw.get("kind") == "ci_asymmetry"
    ]
    assert len(mediums) == 1
    assert mediums[0].severity == "medium"
    assert mediums[0].raw["row"] == 2
    assert mediums[0].raw["axis"] == "log"


# ---------- 5. null-line geometry/text mismatch -> medium ----------

def test_null_line_mismatch_medium(tmp_path) -> None:
    # Rows: (1.23, 0.98, 1.55) crosses 1 and is drawn crossing
    # -> OK; (0.85, 0.60, 1.20) crosses 1 but is drawn fully
    # right of the null line -> flag; (1.60, 1.20, 2.10) does
    # not cross and is drawn not crossing -> OK.
    segments = [
        (_x(0.98), _x(1.55), 80, _x(1.23)),
        (NULL_X + 20, NULL_X + 120, 120, NULL_X + 70),  # fully right of null
        (_x(1.20), _x(2.10), 160, _x(1.60)),
    ]
    arr = _forest_plot_image_custom(segments)
    path = _write_png(arr, tmp_path, "mismatch.png")
    text = (
        "Forest plot of Odds Ratio (OR) with 95% CI.\n"
        "Smith 2020  1.23 [0.98, 1.55]\n"
        "Jones 2021  0.85 [0.60, 1.20]\n"
        "Lee 2022    1.60 [1.20, 2.10]\n"
    )
    result = _run(_doc({1: text}, images=[_image_record(1, path)]))
    mismatches = [
        f
        for f in result.findings
        if f.raw.get("kind") == "null_line_mismatch"
    ]
    assert len(mismatches) == 1
    assert mismatches[0].severity == "medium"
    assert mismatches[0].raw["mismatched_rows"] == [2]


# ---------- 6. non-forest page -> empty ----------

def test_non_forest_page_silent(tmp_path) -> None:
    # A plain bar-like image (long horizontal lines, no dashed
    # vertical, no whisker grid) plus prose without forest
    # vocabulary: no signal reaches the threshold.
    img = Image.new("RGB", (IMG_W, IMG_H), "white")
    d = ImageDraw.Draw(img)
    d.line([(20, 350), (580, 350)], fill="black", width=2)
    d.rectangle([100, 200, 160, 350], fill="grey")
    d.rectangle([300, 150, 360, 350], fill="grey")
    path = _write_png(np.array(img), tmp_path, "bars.png")
    doc = _doc(
        {1: "The treatment group improved by 40% compared to baseline."},
        images=[_image_record(1, path)],
    )
    result = _run(doc)
    assert result.ok
    assert result.findings == []


def test_empty_doc_silent() -> None:
    result = _run(_doc({}))
    assert result.ok
    assert result.findings == []


# ---------- 7. graceful degradation without cv2 / numpy ----------

def test_cv2_missing_degrades(tmp_path, monkeypatch) -> None:
    import manusift.detectors.forest_plot as fp

    monkeypatch.setattr(fp, "_HAS_CV2", False)
    result = _run(_good_doc(tmp_path))
    assert result.ok
    assert result.findings == []


def test_numpy_missing_degrades(tmp_path, monkeypatch) -> None:
    import manusift.detectors.forest_plot as fp

    monkeypatch.setattr(fp, "_HAS_NUMPY", False)
    result = _run(_good_doc(tmp_path))
    assert result.ok
    assert result.findings == []


def test_env_gate_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_FOREST_PLOT_ENABLED", "0")
    result = _run(_good_doc(tmp_path))
    assert result.ok
    assert result.findings == []


# ---------- 8. helpers ----------

def test_parse_triples_variants() -> None:
    from manusift.detectors.forest_plot import _parse_triples

    text = (
        "a 1.23 [0.98, 1.55] b 0.85 (0.60; 1.20) "
        "c -0.30 [-0.55, -0.05] d 2.0 [1.1 to 3.5]"
    )
    triples = _parse_triples(text)
    assert triples == [
        (1.23, 0.98, 1.55),
        (0.85, 0.60, 1.20),
        (-0.30, -0.55, -0.05),
        (2.0, 1.1, 3.5),
    ]


def test_keywords_case_sensitivity() -> None:
    from manusift.detectors.forest_plot import _has_keywords

    # The English word "or" must not fire the abbreviation "OR".
    assert not _has_keywords("one or two studies were included")
    assert _has_keywords("pooled OR with 95% CI")
    assert _has_keywords("hazard ratio across subgroups")


def test_evenly_spaced_helper() -> None:
    from manusift.detectors.forest_plot import _evenly_spaced

    rows = [(10, 50, 80), (10, 50, 120), (10, 50, 160)]
    assert _evenly_spaced(rows)
    ragged = [(10, 50, 80), (10, 50, 120), (10, 50, 300)]
    assert not _evenly_spaced(ragged)
    assert not _evenly_spaced(rows[:2])


def test_find_null_line_helper(tmp_path) -> None:
    import cv2

    from manusift.detectors.forest_plot import _find_null_line

    arr = _forest_plot_image(GOOD_TRIPLES)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    null_x = _find_null_line(binary)
    assert null_x is not None
    assert abs(null_x - NULL_X) <= 2
