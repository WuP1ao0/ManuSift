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
    # P4 (2026-07-18): the table header says
    # "percent" and the prose names the row
    # labels, so this is an explicit-pair
    # mismatch with a 50pp+ gap -> high.
    assert result.findings[0].severity == "high"


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


# ---------- 9. explicit-pair: swapped row values -> high ----------

def test_swapped_row_values_flagged_high() -> None:
    """Prose swaps two rows'
    values. The
    distribution buckets
    are identical (same
    multiset), so only the
    explicit-pair path can
    catch this."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = (
        "The treatment group had 45% recovery. "
        "The control group had 60% recovery."
    )
    tables = [
        FakeTable(
            ["group", "recovery %"],
            [["treatment", "60"], ["control", "45"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.severity == "high"
    ev = json.loads(f.evidence)
    assert ev["kind"] == "explicit_pair_mismatch"
    assert len(ev["pairs"]) == 2


# ---------- 10. proximity pairing avoids the two-value trap ----------

def test_two_values_in_one_sentence_not_flagged() -> None:
    """"treatment 60% vs
    control 45%" in one
    sentence must NOT flag:
    each label is paired
    with its nearest
    percentage, not with
    every percentage in the
    sentence."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "Recovery was 60% for treatment vs 45% for control."
    tables = [
        FakeTable(
            ["group", "recovery %"],
            [["treatment", "60"], ["control", "45"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 11. tolerance boundary ----------

def test_within_tolerance_silent() -> None:
    """A prose value within
    PCT_TOLERANCE of the
    cell (rounding) is
    silent."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "The treatment group had 60% recovery."
    tables = [
        FakeTable(
            ["group", "recovery %"],
            [["treatment", "61.4"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


def test_just_beyond_tolerance_flagged_medium() -> None:
    """A small explicit-pair
    gap (> tolerance but
    < HIGH_MIN_GAP) is
    medium, not high --
    conservative severity
    for borderline
    disagreements."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "The treatment group had 68% recovery."
    tables = [
        FakeTable(
            ["group", "recovery %"],
            [["treatment", "60"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "medium"


# ---------- 12. generic row labels are not anchored ----------

def test_generic_label_stopword_skipped() -> None:
    """A row labelled
    "Total" must not anchor
    explicit-pair matching
    (the word appears in
    almost every results
    prose). The
    distribution path still
    applies."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = (
        "60% of patients recovered. "
        "65% showed improvement. "
        "55% reported side effects."
    )
    tables = [
        FakeTable(
            ["outcome", "percent"],
            [["Total", "60"], ["recovered", "60"],
             ["improved", "65"], ["side effects", "55"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert result.findings == []


# ---------- 13. distribution-only mismatch stays medium ----------

def test_distribution_only_mismatch_medium() -> None:
    """When the table has no
    "%" header the explicit
    path cannot anchor; the
    weak distribution check
    still fires at
    medium."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = "70% recovered. 80% improved. 75% responded."
    tables = [FakeTable(["p"], [["20"], ["25"], ["15"]])]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "medium"


# ---------- 14. structural total row (100%) not anchored ----------

def test_total_row_100pct_not_anchored() -> None:
    """R-2026-07-18 (negative_controls ctrl_f1000_01): a
    percentage-of-base total row ("All CPs ... 100%") must
    not anchor explicit-pair matching -- prose subset
    statistics ("approximately 40% of all CPs did not ...")
    share the label and would always mismatch by ~60pp."""
    from manusift.detectors import FigureTextCrossCheckDetector
    text = (
        "Although the appropriate outcome was achieved in "
        "approximately 60% of all visits, approximately 40% of "
        "all CPs did not recommend that the patient consult a "
        "doctor."
    )
    tables = [
        FakeTable(
            ["Recommendation", "Percentage (%)"],
            [["All CPs", "100"], ["Consult doctor", "60"]],
        )
    ]
    doc = FakeDoc(text=text, tables=tables)
    result = FigureTextCrossCheckDetector().run(doc)
    highs = [
        f for f in result.findings
        if f.raw.get("kind") == "explicit_pair_mismatch"
    ]
    assert highs == []
