"""Tests for the chart_data_extract pipeline gate (P4, 2026-07-18).

The detector now runs in the offline pipeline, so it needs an
independent kill-switch for eval / CI runners
(``MANUSIFT_CHART_EXTRACT_ENABLED=0``) and must degrade
gracefully when the optional CV stack (numpy / OpenCV) is
absent. These tests need neither cv2 nor MANUSIFT_RUN_VISION
because the gated paths return before any image processing.
"""
from __future__ import annotations


class _Img:
    def __init__(self, path):
        self.image_path = path
        self.page = 0


class _Doc:
    def __init__(self, images):
        self.trace_id = "t-chart-gate"
        self.source_path = ""
        self.text_blocks = []
        self.images = list(images)
        self.metadata = {}
        self.tables = []


def test_gate_off_returns_empty(monkeypatch) -> None:
    """``MANUSIFT_CHART_EXTRACT_ENABLED=0``
    makes the detector a
    silent no-op, even with
    images present."""
    from manusift.detectors import ChartDataExtractorDetector

    monkeypatch.setenv("MANUSIFT_CHART_EXTRACT_ENABLED", "0")
    doc = _Doc([_Img("/nonexistent/chart.png")])
    result = ChartDataExtractorDetector().run(doc)
    assert result.ok
    assert result.findings == []


def test_missing_cv_stack_degrades_gracefully(monkeypatch) -> None:
    """With the gate on but
    the CV stack
    unavailable, the
    detector returns an
    empty OK result instead
    of raising -- the
    pipeline must not
    break."""
    import manusift.detectors.chart_data_extract as mod
    from manusift.detectors import ChartDataExtractorDetector

    monkeypatch.delenv(
        "MANUSIFT_CHART_EXTRACT_ENABLED", raising=False
    )
    monkeypatch.setattr(mod, "_load_cv2", lambda: None)
    doc = _Doc([_Img("/nonexistent/chart.png")])
    result = ChartDataExtractorDetector().run(doc)
    assert result.ok
    assert result.findings == []


def test_gate_on_by_default(monkeypatch) -> None:
    """Default (env unset)
    is enabled."""
    from manusift.detectors.chart_data_extract import (
        _chart_extract_enabled,
    )

    monkeypatch.delenv(
        "MANUSIFT_CHART_EXTRACT_ENABLED", raising=False
    )
    assert _chart_extract_enabled()
    monkeypatch.setenv("MANUSIFT_CHART_EXTRACT_ENABLED", "off")
    assert not _chart_extract_enabled()
