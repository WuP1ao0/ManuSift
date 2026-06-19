"""Tests for the figure-text vs. table cross-check (P2.5).

The detector pulls
percentage values from
the prose and from the
tables attached to the
document, then compares
the distributions. The
tests build small documents
with tables in memory.
"""
from __future__ import annotations

import json

import pytest


class FakeTable:
    def __init__(self, headers, rows):
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]


class FakeDoc:
    def __init__(self, text="", tables=None):
        self.trace_id = "t-fig"
        self.source_path = ""
        self.text_blocks = (
            [type("B", (), {"text": text})()] if text else []
        )
        self.images = []
        self.metadata = {}
        self.tables = list(tables or [])


# ---------- 1. detector name ----------

def test_cross_check_detector_name() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    assert (
        FigureTextCrossCheckDetector().name
        == "figure_table_consistency"
    )


# ---------- 2. consistent prose and table ----------

def test_consistent_prose_and_table_silent() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    text = (
        "60% of patients recovered. "
        "65% showed improvement. "
        "55% reported side effects."
    )
    tables = [
        FakeTable(
            ["outcome", "percent"],
            [
                ["recovered", "60"],
                ["improved", "65"],
                ["side effects", "55"],
            ],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 3. inconsistent prose and table ----------

def test_inconsistent_prose_and_table_flagged() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    text = (
        "70% of patients recovered. "
        "80% showed improvement. "
        "75% reported side effects."
    )
    tables = [
        FakeTable(
            ["outcome", "percent"],
            [
                ["recovered", "20"],
                ["improved", "25"],
                ["side effects", "15"],
            ],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "medium"


# ---------- 4. no text percentages ----------

def test_no_text_percentages_silent() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "The experiment ran for three months. No percentages."
    tables = [FakeTable(["percent"], [["60"], ["70"]])]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 5. no tables ----------

def test_no_tables_silent() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "60% of patients recovered."
    doc = FakeDoc(text=text)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 6. empty document is silent ----------

def test_empty_doc_silent() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    doc = FakeDoc()
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 7. proportion values (0-1) are converted ----------

def test_proportion_values_converted() -> None:
    """Values in [0, 1] are
    treated as proportions
    and converted to
    percentages."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "60% of patients recovered."
    tables = [FakeTable(["proportion"], [[0.6]])]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 8. evidence lists both distributions ----------

def test_evidence_includes_both() -> None:
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "70% recovered. 75% improved."
    tables = [FakeTable(["p"], [["20"], ["25"]])]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    assert "text_buckets" in ev
    assert "table_buckets" in ev
