"""Tests for the detector-trace report rendering
(R-2026-06-13).

Covers:

  1. **No summary** (test_report_no_summary_block_when_none):
     if ``detector_summary`` is None, the report does NOT
     contain the ``detector-summary-block`` div.
  2. **Headline counts** (test_report_summary_headline):
     the summary headline includes the correct counts
     (done/total, skipped, error, findings).
  3. **Skip reason visible** (test_report_summary_skip_reason):
     a skipped detector appears with its skip reason in the
     "notes" column.
  4. **All categories present** (test_report_summary_categories):
     detectors are grouped / shown with their category label.
  5. **Table rows match summary detectors**
     (test_report_summary_row_count): one table row per
     detector in the summary.

These tests are read-only against the report builder
(``manusift.report.builder.build_report_html``); they do
not require the pipeline or any real detector runs.
"""
from __future__ import annotations

import pytest

from manusift.config import get_settings
from manusift.contracts import Finding
from manusift.report.builder import build_report_html


def _empty_findings() -> list[Finding]:
    return []


def _settings():
    return get_settings()


# ---------- 1. no summary -> no block ----------

def test_report_no_summary_block_when_none() -> None:
    """When ``detector_summary`` is None, the report does
    NOT contain the ``detector-summary-block`` div. This
    keeps the legacy behaviour intact for callers that
    don't pass a summary."""
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=["metadata", "image_dup"],
        llm_calls=0,
        settings=_settings(),
        detector_summary=None,
    )
    assert "detector-summary-block" not in html


def test_report_no_summary_block_when_empty_dict() -> None:
    """When ``detector_summary`` is an empty dict, the
    builder does NOT add the block (no detectors to
    show)."""
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=["metadata"],
        llm_calls=0,
        settings=_settings(),
        detector_summary={},
    )
    assert "detector-summary-block" not in html


# ---------- 2. headline counts ----------

def test_report_summary_headline() -> None:
    """The headline includes the correct counts."""
    summary = {
        "total": 5,
        "completed": 3,
        "skipped": 1,
        "error": 1,
        "findings_total": 7,
        "detectors": [],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # Headline should be present.
    assert "detector-summary-headline" in html
    assert "3/5 done" in html
    assert "1 skipped" in html
    assert "1 errors" in html
    assert "7 findings" in html


def test_report_summary_no_error_when_zero() -> None:
    """When error=0, the headline does NOT mention errors."""
    summary = {
        "total": 2, "completed": 2, "skipped": 0, "error": 0,
        "findings_total": 5, "detectors": [],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # "0 errors" is not part of the user's spec ("0 errors"
    # is allowed, but our builder only adds it when > 0).
    # Check the text is absent.
    assert "error" not in html.split("detector-summary-headline")[1].split(
        "</p>"
    )[0]


# ---------- 3. skip reason visible ----------

def test_report_summary_skip_reason() -> None:
    """A skipped detector shows its reason in the notes column."""
    summary = {
        "total": 1, "completed": 0, "skipped": 1, "error": 0,
        "findings_total": 0,
        "detectors": [
            {
                "detector": "image_dup",
                "category": "Image forensics",
                "status": "detector.skipped",
                "duration_ms": 0,
                "finding_count": 0,
                "phase": "",
                "skip_reason": "no raster images extracted from PDF",
                "error": "",
            }
        ],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # The reason should be HTML-escaped and present.
    assert "no raster images extracted from PDF" in html
    # The row should use the skipped class.
    assert "detector-row-skipped" in html
    # The icon should be the skipped hook.
    assert "\u21b7" in html


# ---------- 4. all categories present ----------

def test_report_summary_categories() -> None:
    """Each detector row shows its category label."""
    summary = {
        "total": 3, "completed": 3, "skipped": 0, "error": 0,
        "findings_total": 0,
        "detectors": [
            {
                "detector": "metadata",
                "category": "PDF / metadata",
                "status": "detector.done",
                "duration_ms": 5,
                "finding_count": 0,
            },
            {
                "detector": "image_dup",
                "category": "Image forensics",
                "status": "detector.done",
                "duration_ms": 5,
                "finding_count": 0,
            },
            {
                "detector": "text_patterns",
                "category": "Text / references",
                "status": "detector.done",
                "duration_ms": 5,
                "finding_count": 0,
            },
        ],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    assert "PDF / metadata" in html
    assert "Image forensics" in html
    assert "Text / references" in html


# ---------- 5. row count matches detectors ----------

def test_report_summary_row_count() -> None:
    """One table row per detector in the summary."""
    summary = {
        "total": 7, "completed": 5, "skipped": 1, "error": 1,
        "findings_total": 10,
        "detectors": [
            {
                "detector": f"d{i}", "category": "general",
                "status": "detector.done", "duration_ms": 1,
                "finding_count": 0,
            } for i in range(5)
        ] + [
            {
                "detector": "skip", "category": "Image forensics",
                "status": "detector.skipped", "duration_ms": 0,
                "finding_count": 0, "skip_reason": "no images",
            },
            {
                "detector": "err", "category": "Text / references",
                "status": "detector.error", "duration_ms": 0,
                "finding_count": 0, "error": "boom",
            },
        ],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # 7 detector rows total.
    assert html.count("detector-row detector-row-") == 7


# ---------- 6. icon mapping ----------

def test_report_summary_icons() -> None:
    """Each status gets the correct icon."""
    summary = {
        "total": 3, "completed": 1, "skipped": 1, "error": 1,
        "findings_total": 0,
        "detectors": [
            {
                "detector": "d1", "category": "c", "status":
                "detector.done", "duration_ms": 1, "finding_count": 0,
            },
            {
                "detector": "d2", "category": "c", "status":
                "detector.skipped", "duration_ms": 0,
                "finding_count": 0, "skip_reason": "x",
            },
            {
                "detector": "d3", "category": "c", "status":
                "detector.error", "duration_ms": 0,
                "finding_count": 0, "error": "boom",
            },
        ],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # done -> check mark
    assert "\u2713" in html
    # skipped -> hook
    assert "\u21b7" in html
    # error -> warning
    assert "\u26a0" in html


# ---------- 7. HTML safety ----------

def test_report_summary_html_escapes_user_input() -> None:
    """Detector names and skip reasons with special HTML
    characters are properly escaped."""
    summary = {
        "total": 1, "completed": 0, "skipped": 1, "error": 0,
        "findings_total": 0,
        "detectors": [
            {
                "detector": "<script>alert(1)</script>",
                "category": "X & Y",
                "status": "detector.skipped",
                "duration_ms": 0,
                "finding_count": 0,
                "skip_reason": "evil<>&",
            }
        ],
    }
    html = build_report_html(
        trace_id="t",
        findings=_empty_findings(),
        detectors_run=[],
        llm_calls=0,
        settings=_settings(),
        detector_summary=summary,
    )
    # The raw script tag MUST be escaped.
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    # The X & Y category should be escaped.
    assert "X &amp; Y" in html
    # Skip reason escaped.
    assert "evil&lt;&gt;&amp;" in html