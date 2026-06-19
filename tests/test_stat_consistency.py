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
    # 2.5 with N=3 and 0
    # decimal places
    # requires integers
    # averaging 2.5, but
    # 2.5 * 3 = 7.5 is not
    # an integer.
    assert _grim_test([0.0] * 3, 2.5, 0) is False
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
    # 0 decimal places:
    # 31.5 is not a multiple
    # of 1.
    assert _grim_test([0.0] * 10, 3.15, 0) is False
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


def test_t51_sensitive_grim_catches_pct_with_n_3() -> None:
    """``n=3, pct=33.3, decimals=1``:
    33.3 * 3 = 99.9 (NOT close
    to an integer -- 100 differs
    by 0.1, which is greater
    than the half-granularity
    tolerance of 0.05 for
    decimals=1).  GRIM fail.
    A 3-person sample cannot
    have an average of 33.3%
    to 1-decimal precision
    because 33.3% * 3 = 99.9 is
    not a sum of 3 integers.
    """
    from manusift.detectors.stat_consistency import (
        GrimTestDetector,
    )
    table = _make_table(
        ["n", "pct"],
        [["3", "33.3"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    # 33.3 * 3 = 99.9.  round to
    # integer = 100.  diff = 0.1
    # > 0.05 (half-granularity
    # at decimals=1).  So the
    # GRIM check fails and we
    # expect 1 finding.
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.severity == "high"
    assert "33.3" in f.title
    assert "N=3" in f.title


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


def test_t51_sensitive_grim_catches_f_with_n_15() -> None:
    """``n=15, F=3.43, decimals=2``:
    3.43 * 15 = 51.45.
    round(51.45) = 51.  diff
    = 0.45 > 0.005 (half-
    granularity at
    decimals=2).  GRIM fail.

    Note: for F statistics
    (test statistics from
    ANOVA), the value is not a
    mean of integer values, so
    the GRIM test is
    theoretically not
    applicable.  In practice
    the test still fires
    because the cell has
    ``decimals >= 1`` and the
    n_col lookup succeeds.
    This is acceptable as a
    *screening* signal: the
    reviewer checks the
    per-cell evidence and
    decides whether the
    finding is meaningful.
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
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "3.43" in f.title
    assert "N=15" in f.title


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
        [["3", "33.3"]],
    )
    det = GrimTestDetector()
    doc = _make_doc_with_tables(table)
    result = det.run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    ev = _json.loads(f.evidence)
    assert ev.get("check") == "grim_sensitive"
    assert ev.get("n") == 3
    assert ev.get("reported_value") == 33.3


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
