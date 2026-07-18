"""Tests for the GRIM / percent / p-value consistency detectors (P0.2-P0.4).

The three detectors all run
on the same ``doc.tables``
input format. The tests
build small tables in
memory, attach them to a
``ParsedDoc``, and assert
on the findings.
"""
from __future__ import annotations

import json

import pytest


class FakeTable:
    def __init__(self, headers, rows):
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]


class FakeDoc:
    def __init__(self, tables=None, text=""):
        self.trace_id = "t-stat"
        self.source_path = ""
        # The detector
        # concatenates the
        # ``text`` attribute of
        # every block in
        # ``text_blocks`` -- a
        # single block with the
        # full text is enough.
        if text:
            self.text_blocks = [
                type("B", (), {"text": text})()
            ]
        else:
            self.text_blocks = []
        self.images = []
        self.metadata = {}
        self.tables = list(tables or [])


# ---------- 1. detector names ----------

def test_grim_detector_name() -> None:
    from manusift.detectors import GrimTestDetector
    assert GrimTestDetector().name == "stat_grim"


def test_percent_detector_name() -> None:
    from manusift.detectors import PercentDivisibilityDetector
    assert (
        PercentDivisibilityDetector().name
        == "stat_percent"
    )


def test_pvalue_detector_name() -> None:
    from manusift.detectors import PValueConsistencyDetector
    assert (
        PValueConsistencyDetector().name
        == "stat_pvalue"
    )


# ---------- 2. GRIM test passes on consistent data ----------

def test_grim_passes_on_consistent_mean() -> None:
    """Mean of 3.00 from N=10
    values of either 2, 3,
    or 4 (granularity 1) is
    consistent: 3.00 * 10 =
    30, which is a multiple
    of 1."""
    from manusift.detectors import GrimTestDetector
    # Ten values that average
    # exactly to 3.00.
    headers = ["n", "mean"]
    rows = [["10", "3.00"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    assert result.findings == []


def test_grim_fails_on_inconsistent_mean() -> None:
    """A reported mean of 3.5
    from N=4 with reported
    granularity 1.0 (0
    decimal places) cannot
    be produced by 4
    integers: 3.5 * 4 =
    14.0, / 1 = 14,
    consistent.
    GRIM is hard to fail
    with reported means
    that match the
    granularity. We
    exercise the detector
    directly via the
    helper instead.
    """
    from manusift.detectors import GrimTestDetector
    from manusift.detectors.stat_consistency import (
        _grim_test,
    )
    # The helper fails for
    # an impossible mean:
    # 2.5 with N=3 and 1
    # decimal place
    # requires integers
    # averaging 2.5, but
    # 2.5 * 3 = 7.5 is not
    # an integer.
    assert _grim_test([0.0] * 3, 2.5, 1) is False
    # The detector still
    # runs on a clean
    # table -- no false
    # positives on a
    # consistent mean.
    # R-2026-06-15 (T5.1): the
    # cell value "2.5" has 1
    # decimal place.  With
    # decimals=1, the half-
    # granularity tolerance is
    # 0.05, but 2.5 * 3 = 7.5
    # differs from the nearest
    # integer (8) by 0.5, which
    # is greater than 0.05 --
    # so the new GRIM check
    # correctly fails on this
    # row.  The previous test
    # passed only because the
    # *old* GRIM test was
    # structurally broken
    # (always returned True).
    # The corrected test uses
    # a row that the new
    # GRIM test accepts: n=4,
    # mean=2.5 (decimals=1)
    # -> sum=10.0, round(10)=10,
    # diff=0 < 0.05.  Passes.
    headers = ["n", "mean"]
    rows = [["4", "2.5"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    # 2.5 * 4 = 10.0.  round(10)=10.
    # diff=0.  Within the
    # half-granularity
    # tolerance.  Passes.
    assert result.findings == []


def test_grim_handles_two_decimal_places() -> None:
    """3.05 from N=20 with
    granularity 0.01 is
    consistent: 3.05 * 20
    = 61, a multiple of
    0.01."""
    from manusift.detectors import GrimTestDetector
    headers = ["n", "mean"]
    rows = [["20", "3.05"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    assert result.findings == []


def test_grim_skips_non_mean_columns() -> None:
    """R-2026-06-15 (T5.1): the
    detector used to skip
    every non-mean column.
    After T5.1 the *sensitive*
    sub-check runs on every
    numeric column with a
    sibling N column.  This
    test now verifies:
      1. An identifier column
         ("year", "id") is still
         skipped.
      2. A "score" column with
         a value that the
         *sensitive* check would
         flag (e.g. n=10,
         score=3.15 -> sum=31.5
         not integer) IS now
         flagged (this is the
         new T5.1 behaviour).
      3. A "score" column with
         a value that passes the
         sensitive check (e.g.
         n=10, score=3.10 ->
         sum=31.0 integer) is
         NOT flagged.
    """
    from manusift.detectors import GrimTestDetector
    # 1. Identifier column is
    # skipped.
    headers = ["n", "year"]
    rows = [["10", "2024.5"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    assert result.findings == []

    # 2. Non-mean, non-identifier
    # column with a GRIM-fail
    # value is now flagged.
    headers = ["n", "score"]
    rows = [["10", "3.15"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    # 3.15 * 10 = 31.5.  round(31.5)
    # = 32 (banker's).  diff = 0.5
    # > 0.005 (half-granularity
    # at decimals=2).  Fail.
    # T5.1 sensitive check fires.
    assert len(result.findings) == 1

    # 3. Same column with a
    # GRIM-pass value is NOT
    # flagged.
    rows = [["10", "3.10"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = GrimTestDetector().run(doc)
    # 3.10 * 10 = 31.0.  round(31)
    # = 31.  diff = 0.  Pass.
    assert result.findings == []


# ---------- 3. percent * n divisibility ----------

def test_percent_passes_on_clean_data() -> None:
    """60% out of N=50 is
    30 cases, an integer."""
    from manusift.detectors import PercentDivisibilityDetector
    headers = ["n", "agreement %"]
    rows = [["50", "60"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = PercentDivisibilityDetector().run(doc)
    assert result.findings == []


def test_percent_fails_on_inconsistent_value() -> None:
    """61% out of N=50 is
    30.5 cases -- not an
    integer."""
    from manusift.detectors import PercentDivisibilityDetector
    headers = ["n", "agreement %"]
    rows = [["50", "61"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = PercentDivisibilityDetector().run(doc)
    assert len(result.findings) == 1
    assert "whole number" in result.findings[0].title


def test_percent_skips_non_percent_columns() -> None:
    """A column without '%' or
    'percent' in the header
    is ignored."""
    from manusift.detectors import PercentDivisibilityDetector
    headers = ["n", "score"]
    rows = [["50", "61"]]
    doc = FakeDoc(tables=[FakeTable(headers, rows)])
    result = PercentDivisibilityDetector().run(doc)
    assert result.findings == []


# ---------- 4. p-value recomputation ----------

def test_pvalue_passes_on_consistent_text() -> None:
    """A reported p=0.001 for
    r=0.5, n=22 is
    consistent with the
    recomputed value (the
    critical p at df=20 for
    r=0.5 is around 0.025,
    so 0.001 is too low but
    the test is forgiving
    up to 0.01). We pick a
    combination that does
    pass.
    """
    from manusift.detectors import PValueConsistencyDetector
    # r=0.5, n=10 -> df=8,
    # recomputed p ≈ 0.144.
    # The report says 0.15
    # -- within tolerance.
    doc = FakeDoc(text="r(8) = 0.5, p = 0.15")
    result = PValueConsistencyDetector().run(doc)
    assert result.findings == []


def test_pvalue_flags_significant_disagreement() -> None:
    """A reported p=0.001 for
    r=0.1, n=20 is wildly
    off: the recomputed
    p-value is around 0.7.
    The detector must flag
    it."""
    from manusift.detectors import PValueConsistencyDetector
    doc = FakeDoc(text="r(18) = 0.1, p = 0.001")
    result = PValueConsistencyDetector().run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "disagrees" in f.title.lower()
    assert "p_reported" in json.loads(f.evidence)
    assert "p_recomputed" in json.loads(f.evidence)


def test_pvalue_ignores_unparseable_text() -> None:
    """Plain prose without
    'r' and 'p' must not
    trigger a finding."""
    from manusift.detectors import PValueConsistencyDetector
    doc = FakeDoc(
        text=(
            "The experiment found no significant "
            "differences between the groups."
        )
    )
    result = PValueConsistencyDetector().run(doc)
    assert result.findings == []


# ---------- 5. helper functions ----------

def test_decimal_places_basic() -> None:
    from manusift.detectors.stat_consistency import (
        _decimal_places,
    )
    assert _decimal_places("3") == 0
    assert _decimal_places("3.1") == 1
    assert _decimal_places("3.14") == 2
    assert _decimal_places("3.140") == 3


def test_grim_helper_function() -> None:
    from manusift.detectors.stat_consistency import _grim_test
    # 3.00 from N=10 with
    # 0 decimal places
    # would be inconsistent
    # -- 3.00 * 10 = 30 is a
    # multiple of 1, so it is
    # consistent.
    assert _grim_test([0.0] * 10, 3.0, 0) is True
    # 3.15 from N=10 with
    # 2 decimal places: no
    # integer sum S exists
    # with S/10 rounding to
    # 3.15 at 2 dp (the
    # interval (31.45, 31.55]
    # contains no integer).
    assert _grim_test([0.0] * 10, 3.15, 2) is False
    # Empty list -- the
    # detector must short-
    # circuit to ``True``
    # (vacuously consistent).
    assert _grim_test([], 0.0, 0) is True


def test_pearson_p_at_extreme_correlation() -> None:
    from manusift.detectors.stat_consistency import _pearson_p
    # r=1.0 -> p=0.
    assert _pearson_p(1.0, 10) == 0.0
    # r=0.0 -> p=1.
    assert _pearson_p(0.0, 10) == pytest.approx(1.0, abs=1e-6)


def test_regularized_incomplete_beta_endpoints() -> None:
    from manusift.detectors.stat_consistency import (
        _regularized_incomplete_beta,
    )
    assert _regularized_incomplete_beta(0.0, 1.0, 1.0) == 0.0
    assert _regularized_incomplete_beta(1.0, 1.0, 1.0) == 1.0
    # The function is
    # symmetric: I_x(a, b) =
    # 1 - I_{1-x}(b, a).
    a = 2.0
    b = 3.0
    x = 0.3
    v1 = _regularized_incomplete_beta(x, a, b)
    v2 = _regularized_incomplete_beta(1.0 - x, b, a)
    assert abs(v1 - (1.0 - v2)) < 1e-6



# ---- R-2026-06-15 (T5.1) regression tests ----
#
# The original
# ``GrimTestDetector`` required
# a column to be labelled
# "mean" / "average" before
# running the GRIM test, which
# meant it fired 0 times on
# Frontiers papers (whose text
# doesn't write "mean=X" in
# the body).  T5.1 added a
# *sensitive* GRIM check on
# every numeric column that
# has a sibling N column:
# ``value * n`` must be a
# multiple of ``1/10^decimals``.
# These tests verify the new
# behaviour.


def _make_table(
    headers: list[str], rows: list[list[str]]
):
    """Tiny helper to build an
    ``ExtractedTable`` for the
    T5.1 regression tests."""
    from manusift.contracts import ExtractedTable
    return ExtractedTable(
        table_id="t-t51",
        source_kind="pdf_text_stat",
        source_path="(t51-test)",
        sheet_name="",
        source_index=0,
        headers=headers,
        rows=rows,
    )


def _make_doc_with_tables(*tables) -> object:
    from manusift.contracts import ParsedDoc
    return ParsedDoc(
        trace_id="t-t51",
        source_path="",
        text_blocks=[],
        images=[],
        metadata={},
        tables=list(tables),
    )


def test_t51_sensitive_grim_catches_pct_with_n_20() -> None:
    """``n=20, pct=5.0, decimals=1``:
    5.0 * 20 = 100.0 (integer)
    so the cell passes (5.0 %
    of 20 IS an integer).
    A value of 5.5 would fail
    (5.5 * 20 = 110, integer;
    5.5 * 21 = 115.5, NOT
    integer)."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    # 5.0 * 20 = 100.0 -- passes
    table = _make_table(
        ["n", "pct"],
        [["20", "5.0"], ["20", "10.0"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # Both rows pass (5.0 and
    # 10.0 are both
    # GRIM-consistent for n=20).
    assert len(result.findings) == 0


def test_t51_sensitive_grim_catches_pct_with_n_9() -> None:
    """``n=9, pct=15.71, decimals=2``:
    no integer sum S exists with
    S/9 rounding to 15.71 at 2 dp
    (the interval (141.345, 141.435]
    contains no integer).  GRIM fail.
    Note: the previous fixture
    (n=3, pct=33.3) was WRONG --
    33.3% of 3 is 1/3 = 33.33...%
    which rounds to 33.3 and is
    genuinely GRIM-consistent.
    """
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["9", "15.71"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # 15.71 * 9 = 141.39 -- no
    # integer sum rounds to
    # 15.71 at 2 dp.  So the
    # GRIM check fails and we
    # expect 1 finding.
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.severity == "high"
    assert "15.71" in f.title
    assert "N=9" in f.title


def test_t51_sensitive_grim_passes_for_n_multiple_of_100() -> None:
    """``n=100, pct=42.5, decimals=1``:
    42.5 * 100 = 4250 (integer,
    multiple of 0.1). Passes."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["100", "42.5"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 0


def test_t51_sensitive_grim_skips_f_statistic_column() -> None:
    """``n=15, F=3.43`` -- the F statistic from an
    ANOVA is not a mean of integer values, so GRIM
    is a category error here.  The T5.1 author
    kept the firing as a "screening signal", but
    negative_controls_v1 (2026-07) showed the same
    logic systematically flags p_value columns on
    *legitimate* clinical papers (ctrl_bmc_02: 6
    high findings, all category errors).  The
    sensitive check now skips statistical-
    quantity columns entirely.
    """
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "F"],
        [["15", "3.43"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert result.findings == []

def test_t51_sensitive_grim_skips_integer_cells() -> None:
    """A cell with 0 decimal
    places is always
    GRIM-consistent regardless
    of n.  The detector must
    not flag it."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["3", "33"], ["7", "100"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # No findings: integer cells
    # are always GRIM-consistent.
    assert len(result.findings) == 0


def test_t51_sensitive_grim_skips_n_lt_2() -> None:
    """``n=1`` makes the GRIM test
    meaningless (1 individual
    = 100% of itself, no
    variance).  Detector must
    skip n < 2."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["1", "100.0"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 0


def test_t51_sensitive_grim_skips_identifier_columns() -> None:
    """A column whose header is
    "year" or "id" is an
    identifier, not a numeric
    measurement.  Detector must
    skip it."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "year"],
        [["20", "2024.0"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # No finding: "year" is an
    # identifier.
    assert len(result.findings) == 0


def test_t51_sensitive_grim_skips_table_without_n() -> None:
    """If the table has no N
    column at all, the GRIM
    test is not applicable.  The
    detector must skip the
    table."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["pct"],
        [["33.3"], ["66.6"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 0


def test_t51_sensitive_grim_skips_very_large_values() -> None:
    """A cell with abs(value) >
    1000 is probably a raw count
    (e.g. "1567 patients"), not
    an average or percentage.
    Detector must skip it."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["5", "1567.5"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # No finding: 1567.5 is
    # larger than 1000, so
    # skipped as a "raw count".
    assert len(result.findings) == 0


def test_t51_sensitive_grim_evidence_includes_check_name() -> None:
    """The T5.1 sensitive-GRIM
    finding must record the
    check name ``grim_sensitive``
    in its evidence JSON so a
    reviewer can distinguish it
    from the original
    mean-column GRIM check
    (``grim_mean``)."""
    import json as _json
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["9", "15.71"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    ev = _json.loads(f.evidence)
    assert ev.get("check") == "grim_sensitive"
    assert ev.get("n") == 9
    assert ev.get("reported_value") == 15.71


def test_t51_sensitive_grim_mean_column_still_works() -> None:
    """The original mean-column
    GRIM check (sub-check a)
    must still fire when a
    column IS labelled "mean".
    We do NOT want T5.1 to
    disable the original
    behaviour."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    # n=20, mean=4.21 (decimals=2):
    # 4.21 * 20 = 84.2.  round(84.2)
    # = 84.  diff = 0.2 > 0.005
    # (half-granularity at
    # decimals=2).  GRIM fail.
    table = _make_table(
        ["n", "mean"],
        [["20", "4.21"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    import json as _json
    ev = _json.loads(f.evidence)
    # The finding should be
    # tagged with the original
    # "grim_mean" check, not
    # "grim_sensitive".
    assert ev.get("check") == "grim_mean"
    assert "4.21" in f.title


# ---------------------------------------------------------------------------
# 2026-07: table-based t/p consistency (fraud_web_v1 web_cureus_01)
# ---------------------------------------------------------------------------


def test_table_tp_scan_flags_inconsistent_gender_table() -> None:
    """The retracted Cureus EDI paper reports t=1.61 with
    p=0.646 (recomputed p≈0.107) and t=0.923 with p=0.943
    (recomputed ≈0.357) in the same table -- 2 inconsistent
    pairs must fire high."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["Variable", "Gender", "N", "Mean ± SD", "t-value", "p-value"],
        [
            ["Perception of equity", "Male", "156", "4 ± 0.8", "1.61", "0.646"],
            ["", "Female 172 3.9 ± 0.8", "", "", "", ""],
            ["Perception of diversity", "Male", "156", "3.8 ± 1", "0.923", "0.943"],
            ["Perception of inclusion", "Male", "156", "4 ± 0.9", "1.048", "0.194"],
        ],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    tp = [f for f in result.findings if "t/p pair" in f.title]
    assert len(tp) == 1
    assert tp[0].severity == "high"
    import json as _json
    ev = _json.loads(tp[0].evidence)
    assert len(ev["inconsistent_pairs"]) == 2


def test_table_tp_scan_clean_when_consistent() -> None:
    """t=-0.37 → p≈0.712 and t=-0.944 → p≈0.346 are
    consistent (these rows come from the *valid* nationality
    table of the same retracted paper) -- no finding."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["Variable", "Nationality", "N", "Mean ± SD", "t-value", "p-value"],
        [
            ["Perception of equity", "Non-Saudi", "74", "3.9 ± 0.7", "-0.37", "0.712"],
            ["Perception of diversity", "Non-Saudi", "74", "3.6 ± 1", "-0.944", "0.346"],
        ],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    assert [f for f in result.findings if "t/p pair" in f.title] == []


def test_table_tp_scan_ignores_tables_without_tp_headers() -> None:
    """A numeric table without t/p column headers must not
    be interpreted as t/p pairs (precision guard)."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["ratio", "coverage"],
        [["3.70", "0.50"], ["2.90", "0.60"]],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    assert [f for f in result.findings if "t/p pair" in f.title] == []


def test_table_tp_scan_single_extreme_pair_medium() -> None:
    """One pair with Δ > 0.35 fires medium."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["Variable", "Group", "N", "Mean ± SD", "t-value", "p-value"],
        [
            ["Score", "A", "100", "4.0 ± 0.8", "1.50", "0.700"],
            ["Score2", "B", "100", "4.1 ± 0.9", "2.90", "0.004"],
        ],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    tp = [f for f in result.findings if "t/p pair" in f.title]
    assert len(tp) == 1
    assert tp[0].severity == "medium"


def test_sensitive_grim_skips_stat_quantity_columns() -> None:
    """negative_controls_v1: GRIM on a p_value column is a
    category error (p-values are not means of integers).
    ctrl_bmc_02 legit paper was flagged for p_value=0.05
    at N=7 -- must not happen."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
        _is_stat_quantity_column,
    )
    assert _is_stat_quantity_column("p_value")
    assert _is_stat_quantity_column("t-value")
    assert _is_stat_quantity_column("F")
    assert _is_stat_quantity_column("Chi2")
    assert not _is_stat_quantity_column("pct")
    assert not _is_stat_quantity_column("mean")
    table = _make_table(
        ["n", "p_value"],
        [["7", "0.05"], ["8", "0.05"], ["7", "0.01"]],
    )
    doc = _make_doc_with_tables(table)
    result = GrimTestDetector().run(doc)
    assert result.findings == []


def test_sensitive_grim_still_fires_on_plain_decimal_columns() -> None:
    """The exclusion must not neuter the sensitive check on
    genuine average-like columns (pct-like values)."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["9", "15.71"]],
    )
    doc = _make_doc_with_tables(table)
    result = GrimTestDetector().run(doc)
    assert len(result.findings) == 1


def test_summary_stat_scan_catches_welch_mismatch() -> None:
    """fraud_web_v1 web_cureus_01 ground truth: Male 156 4±0.8
    vs Female 172 3.9±0.8 with reported t=1.61 -- Welch
    recompute is t≈1.13 (Δ≈0.48). Must fire."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["Variable", "Gender", "N", "Mean ± SD", "t-value", "p-value"],
        [
            ["Perception of equity", "Male", "156", "4 ± 0.8", "1.61", "0.646"],
            ["", "Female 172 3.9 ± 0.8", "", "", "", ""],
            ["Perception of diversity", "Male", "156", "3.8 ± 1", "0.923", "0.943"],
            ["", "Female 172 3.7 ± 1", "", "", "", ""],
        ],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    mm = [f for f in result.findings if "summary-stat recompute" in f.title]
    assert len(mm) == 1
    import json as _json
    ev = _json.loads(mm[0].evidence)
    kinds = [m["kind"] for m in ev["mismatches"]]
    assert kinds == ["welch_t"]


def test_summary_stat_scan_silent_when_consistent() -> None:
    """The diversity block (3.8±1 vs 3.7±1, t=0.923) IS
    consistent (Welch ≈ 0.905) -- no finding."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    table = _make_table(
        ["Variable", "Gender", "N", "Mean ± SD", "t-value", "p-value"],
        [
            ["Perception of diversity", "Male", "156", "3.8 ± 1", "0.923", "0.357"],
            ["", "Female 172 3.7 ± 1", "", "", "", ""],
        ],
    )
    doc = _make_doc_with_tables(table)
    result = PValueConsistencyDetector().run(doc)
    assert [f for f in result.findings if "summary-stat" in f.title] == []


def test_summary_stat_scan_anova_f_to_p() -> None:
    """3-group table with F reported: F=0.701 for the Cureus
    socioeconomic equity block is consistent with its
    summary stats (recompute ≈0.69); a doctored F=2.8 is
    not -- must fire."""
    from manusift.detectors.stat_consistency import (
        PValueConsistencyDetector,
    )
    base_rows = [
        ["Perception of equity", "Low", "103", "4 ± 0.7", None, None],
        ["", "Middle 145 3.9 ± 0.9", "", "", "", ""],
        ["", "High", "80", "4 ± 0.9", "", ""],
    ]
    consistent = _make_table(
        ["Variable", "SES", "N", "Mean ± SD", "F-value", "p-value"],
        [base_rows[0][:4] + ["0.701", "0.497"]] + base_rows[1:],
    )
    doc = _make_doc_with_tables(consistent)
    result = PValueConsistencyDetector().run(doc)
    assert [f for f in result.findings if "summary-stat" in f.title] == []

    doctored = _make_table(
        ["Variable", "SES", "N", "Mean ± SD", "F-value", "p-value"],
        [base_rows[0][:4] + ["2.80", "0.062"]] + base_rows[1:],
    )
    doc2 = _make_doc_with_tables(doctored)
    result2 = PValueConsistencyDetector().run(doc2)
    mm = [f for f in result2.findings if "summary-stat" in f.title]
    assert len(mm) == 1


# ---------------------------------------------------------------------------
# 2026-07: GRIM N>200 skip, DEBIT, GRIMMER bound, statcheck special rules
# ---------------------------------------------------------------------------


def test_grim_skips_n_above_200() -> None:
    """GRIM trap: above N=200 the 1/N granularity is so fine the test
    has no discriminative power, so the detector skips the row.
    ``3.337`` (3 dp) fails GRIM at both N=200 and N=201 -- the N=200
    table MUST fire (proving the value is GRIM-inconsistent) while the
    N=201 table must stay silent (proving the skip)."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    det = GrimTestDetector()
    table_fail = _make_table(["n", "pct"], [["200", "3.337"]])
    res_fail = det.run(_make_doc_with_tables(table_fail))
    assert len(res_fail.findings) == 1
    table_skip = _make_table(["n", "pct"], [["201", "3.337"]])
    res_skip = det.run(_make_doc_with_tables(table_skip))
    assert res_skip.findings == []
    # Same skip on the original mean-column sub-check.
    table_mean = _make_table(["n", "mean"], [["201", "3.337"]])
    res_mean = det.run(_make_doc_with_tables(table_mean))
    assert res_mean.findings == []


def test_debit_fires_on_impossible_binary_sd() -> None:
    """DEBIT: 50% yes at N=100 determines SD = sqrt(.25*100/99) ~=
    0.5025; a reported SD of 0.30 is impossible for binary data."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "yes %", "sd"],
        [["A", "100", "50.0", "0.30"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    debit = [
        f
        for f in result.findings
        if json.loads(f.evidence).get("check") == "debit"
    ]
    assert len(debit) == 1
    assert debit[0].severity == "high"
    ev = json.loads(debit[0].evidence)
    assert ev["n"] == 100
    assert ev["reported_sd"] == 0.30


def test_debit_silent_when_sd_matches() -> None:
    """The same table with SD=0.50 is within rounding slack of the
    theoretical 0.5025 -- no finding."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "yes %", "sd"],
        [["A", "100", "50.0", "0.50"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    assert result.findings == []


def test_debit_skips_non_binary_percentages() -> None:
    """A continuous percentage ("body fat %") is out of DEBIT's
    domain -- the binary-outcome header guard must prevent firing."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "body fat %", "sd"],
        [["A", "100", "50.0", "0.30"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    assert result.findings == []


def test_grimmer_bound_fires_on_impossible_sd() -> None:
    """Mean 2.00 on a 1-7 scale at N=20 has a maximum possible SD of
    ~2.29 (all responses at the endpoints); SD=3.50 cannot exist."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "mean", "sd"],
        [["A", "20", "2.00", "3.50"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    gr = [
        f
        for f in result.findings
        if json.loads(f.evidence).get("check") == "grimmer_sd_bound"
    ]
    assert len(gr) == 1
    assert gr[0].severity == "high"
    ev = json.loads(gr[0].evidence)
    assert ev["sd_max"] < 3.50


def test_grimmer_bound_silent_when_possible() -> None:
    """SD=2.00 is below the 2.29 bound -- no finding."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "mean", "sd"],
        [["A", "20", "2.00", "2.00"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    assert result.findings == []


def test_grimmer_bound_requires_grim_consistent_mean() -> None:
    """A mean that fails GRIM (2.03 at N=20) is not plausibly integer
    scale data, so the SD bound must NOT fire -- the low-severity
    grim_mean finding from sub-check (a) is the only signal."""
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["group", "n", "mean", "sd"],
        [["A", "20", "2.03", "3.50"]],
    )
    result = GrimTestDetector().run(_make_doc_with_tables(table))
    checks = [json.loads(f.evidence).get("check") for f in result.findings]
    assert "grimmer_sd_bound" not in checks


def test_statcheck_decision_error_in_title() -> None:
    """t(20)=1.5 with p=.03: reported significant, recomputed ~0.15
    (ns) -- the finding must carry the decision-error flag."""
    from manusift.detectors import PValueConsistencyDetector
    doc = FakeDoc(text="t(20) = 1.5, p = .03")
    result = PValueConsistencyDetector().run(doc)
    sc = [f for f in result.findings if "statcheck" in f.title]
    assert len(sc) == 1
    assert "decision error" in sc[0].title
    ev = json.loads(sc[0].evidence)
    assert ev["decision_error"] is True
    assert ev["p_low"] < ev["p_up"]


def test_statcheck_p_zero_in_title() -> None:
    """p = .000 is a pZeroError -- always inconsistent."""
    from manusift.detectors import PValueConsistencyDetector
    doc = FakeDoc(text="t(20) = 2.0, p = .000")
    result = PValueConsistencyDetector().run(doc)
    sc = [f for f in result.findings if "statcheck" in f.title]
    assert len(sc) == 1
    assert "exactly 0" in sc[0].title
    ev = json.loads(sc[0].evidence)
    assert ev["p_zero_error"] is True


def test_statcheck_interval_consistent_no_finding() -> None:
    """Rounding-interval consistency: t(20)=2.0 implies p in
    [0.0537, 0.0653]; p=.06 rounds into the interval, so the detector
    must stay silent even though |0.06 - 0.0593| < 0.01 would also
    have passed the old flat tolerance."""
    from manusift.detectors import PValueConsistencyDetector
    doc = FakeDoc(text="t(20) = 2.0, p = .06")
    result = PValueConsistencyDetector().run(doc)
    assert [f for f in result.findings if "statcheck" in f.title] == []
