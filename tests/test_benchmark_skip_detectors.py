"""Test the ``benchmark_skip_detectors`` Settings field and its
application in ``pipeline._pipeline_detector_classes()``.

Why this test exists:
  - The benchmark runner (real_eval_fraud_cases_v2) sets
    ``MANUSIFT_BENCHMARK_SKIP_DETECTORS=figure_stat_text,...`` to
    skip slow OCR / Crossref detectors in CI.
  - The skip must:
      1. Be reflected in ``_pipeline_detector_classes()`` (so the
         pipeline doesn't run those detectors).
      2. NOT affect the agent-loop tool list (LLM-visible detectors).
      3. NOT affect any test that does not explicitly set the env
         var (default = empty = no skip).
"""
from __future__ import annotations

import pytest


def test_default_no_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: empty benchmark_skip_detectors means no skip."""
    monkeypatch.delenv("MANUSIFT_BENCHMARK_SKIP_DETECTORS", raising=False)
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.benchmark_skip_detectors == ""

    from manusift.pipeline import _pipeline_detector_classes
    names = [d().name for d in _pipeline_detector_classes()]
    # All detectors should be present by default. Specifically the
    # three skip-targets must be present.
    assert "figure_stat_text" in names
    assert "figure_grim" in names
    assert "citation_network" in names


def test_skip_removes_from_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """When benchmark_skip_detectors is set, _pipeline_detector_classes
    omits those detector names."""
    monkeypatch.setenv(
        "MANUSIFT_BENCHMARK_SKIP_DETECTORS",
        "figure_stat_text,figure_grim,citation_network",
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert "figure_stat_text" in s.benchmark_skip_detectors.split(",")

    from manusift.pipeline import _pipeline_detector_classes
    names = [d().name for d in _pipeline_detector_classes()]
    assert "figure_stat_text" not in names
    assert "figure_grim" not in names
    assert "citation_network" not in names
    # The image detectors we still need are kept.
    assert "image_dup" in names
    assert "image_forensics" in names
    assert "panel_dup" in names


def test_skip_does_not_affect_tool_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """benchmark_skip_detectors must NOT change the LLM-visible tool
    list. The agent loop should still see all detectors as callable
    tools even if the pipeline skips some."""
    monkeypatch.setenv(
        "MANUSIFT_BENCHMARK_SKIP_DETECTORS",
        "figure_stat_text,figure_grim,citation_network",
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from manusift.tools.detector_catalog import register_all_detectors
    tools = register_all_detectors()
    tool_names = {t.name for t in tools}
    # The skip targets MUST still appear as tools (the LLM can call
    # them; the offline pipeline just won't run them automatically).
    assert "figure_stat_text" in tool_names
    assert "figure_grim" in tool_names
    assert "citation_network" in tool_names


def test_partial_skip_only_drops_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skipping only one detector leaves the others intact."""
    monkeypatch.setenv(
        "MANUSIFT_BENCHMARK_SKIP_DETECTORS", "citation_network",
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from manusift.pipeline import _pipeline_detector_classes
    names = [d().name for d in _pipeline_detector_classes()]
    assert "citation_network" not in names
    assert "figure_stat_text" in names
    assert "figure_grim" in names


def test_whitespace_around_skip_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace around comma-separated names is tolerated."""
    monkeypatch.setenv(
        "MANUSIFT_BENCHMARK_SKIP_DETECTORS",
        " figure_stat_text , figure_grim ",
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from manusift.pipeline import _pipeline_detector_classes
    names = [d().name for d in _pipeline_detector_classes()]
    assert "figure_stat_text" not in names
    assert "figure_grim" not in names
    assert "citation_network" in names  # not skipped