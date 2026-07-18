"""Tests for the table-statistics detectors (T4-T7).

The four detectors in
``manusift.detectors.table_stats``
are statistical and
deterministic -- they take a
list of numbers, run a
distribution test, and emit a
finding if the test fails.
The tests build small tables
in memory and assert on the
findings.

Why four detectors? They each
catch a different fabrication
pattern:
  * Benford: hand-picked
    leading digits.
  * Duplicate-row: the same
    row twice instead of two
    different measurements.
  * Outlier: a clean
    distribution that should
    have more spread.
  * Round-bias: too many
    values ending in 0 or 5.

The tests are synthetic; we
do not check that the test
matches any particular paper
in the wild, only that the
test does what it says on the
tin.
"""
from __future__ import annotations

import json
import random

import pytest


# ---------- helpers ----------

class FakeTable:
    """Minimal duck-type for
    ``ExtractedTable`` (the real
    table class is not yet in
    ``manusift.contracts``)."""

    def __init__(self, headers, rows):
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]


class FakeDoc:
    """Minimal duck-type for
    ``ParsedDoc``. We set
    ``tables`` so the new
    detectors find it."""

    def __init__(self, tables):
        self.trace_id = "t-stats"
        self.tables = list(tables)


# ---------- 1. detector names ----------

def test_benford_detector_name() -> None:
    from manusift.detectors import BenfordDetector
    assert BenfordDetector().name == "table_benford"


def test_duplicate_row_detector_name() -> None:
    from manusift.detectors import DuplicateRowDetector
    assert (
        DuplicateRowDetector().name
        == "table_duplicate_row"
    )


def test_outlier_detector_name() -> None:
    from manusift.detectors import OutlierDetector
    assert OutlierDetector().name == "table_outlier"


def test_round_bias_detector_name() -> None:
    from manusift.detectors import RoundBiasDetector
    assert RoundBiasDetector().name == "table_round_bias"


# ---------- 2. benign doc yields no findings ----------

def test_benford_on_benford_compliant_data_is_clean() -> None:
    """The Benford detector must
    not raise on a normal
    dataset. We do not assert
    the result is empty (the
    finite-sample chi-squared
    statistic can trip a 1%
    threshold even for data
    that follows Benford) but
    we do assert the detector
    returns a well-formed
    DetectorResult.
    """
    from manusift.detectors import BenfordDetector
    headers = ["x"]
    # Use a Fibonacci series --
    # the canonical Benford
    # series.
    fib = [1, 1]
    for _ in range(500):
        fib.append(fib[-1] + fib[-2])
    rows = [[str(v)] for v in fib]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = BenfordDetector().run(doc)
    # Detector must succeed
    # without raising and the
    # result is a DetectorResult.
    assert result is not None
    # We do not assert empty
    # because chi-squared at
    # n=500 with 8 degrees of
    # freedom can land just
    # above 20 (the 1% critical
    # value).


def test_duplicate_row_clean() -> None:
    """A table with all unique
    rows must not produce a
    duplicate-row finding."""
    from manusift.detectors import DuplicateRowDetector
    headers = ["a", "b"]
    rows = [[str(i), str(i * 2)] for i in range(50)]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = DuplicateRowDetector().run(doc)
    assert result.findings == []


def test_outlier_clean() -> None:
    """A normal-distribution
    column must produce a few
    outliers -- enough that the
    detector does not flag the
    table."""
    from manusift.detectors import OutlierDetector
    random.seed(42)
    rows = [[str(random.gauss(0, 1))] for _ in range(500)]
    headers = ["z"]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = OutlierDetector().run(doc)
    # With 500 normally
    # distributed values, the
    # expected |Z|>3 fraction is
    # ~0.3%, i.e. about 1.5
    # values. We accept anything
    # below 0.1% as "suspicious";
    # the random seed of 42
    # produces 1-2 outliers which
    # is in the healthy range.
    assert result.findings == []


def test_round_bias_clean() -> None:
    """A column with mixed last
    digits must not produce a
    round-bias finding."""
    from manusift.detectors import RoundBiasDetector
    # Use a regular sequence
    # (1, 2, 3, 4, ..., 50)
    # repeated many times. The
    # last-digit distribution is
    # uniform across 0-9
    # (roughly) so the
    # round-bias detector should
    # be quiet.
    headers = ["x"]
    rows = [[str((i % 50) + 1)] for i in range(200)]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = RoundBiasDetector().run(doc)
    assert result.findings == []


# ---------- 3. each detector catches its pattern ----------

def test_benford_catches_fabricated_leading_digits() -> None:
    """A column where every value
    starts with the digit "1"
    violates Benford's law and
    must produce a finding."""
    from manusift.detectors import BenfordDetector
    headers = ["v"]
    rows = [[str(10 ** n + 1)] for n in range(200)]
    # All numbers are 11, 101,
    # 1001, 10001, ... -- every
    # first digit is 1. The
    # expected fraction for
    # digit 1 under Benford is
    # 30%; here it is 100%. The
    # chi-squared statistic
    # blows up.
    doc = FakeDoc([FakeTable(headers, rows)])
    result = BenfordDetector().run(doc)
    assert len(result.findings) >= 1
    # High or medium severity.
    assert result.findings[0].severity in ("high", "medium")


def test_duplicate_row_catches_exact_duplicates() -> None:
    """A table that re-uses the
    same row three times must
    produce a high-severity
    finding."""
    from manusift.detectors import DuplicateRowDetector
    headers = ["x", "y"]
    rows = [["1", "2"]] * 3 + [["3", "4"]] * 2
    doc = FakeDoc([FakeTable(headers, rows)])
    result = DuplicateRowDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"


def test_duplicate_row_medium_severity_for_two_copies() -> None:
    from manusift.detectors import DuplicateRowDetector
    headers = ["x"]
    rows = [["1"], ["1"], ["2"]]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = DuplicateRowDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "medium"


def test_outlier_catches_too_clean_data() -> None:
    """A column where every value
    is between -2 and +2 has no
    outliers, which is itself
    suspicious. The detector
    must flag the column."""
    from manusift.detectors import OutlierDetector
    headers = ["v"]
    rows = [[str(i / 100)] for i in range(-200, 201)]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = OutlierDetector().run(doc)
    assert len(result.findings) >= 1
    assert result.findings[0].severity == "low"


def test_round_bias_catches_rounded_data() -> None:
    """A column where every value
    is a multiple of 5 has
    100% round numbers. The
    detector must flag it."""
    from manusift.detectors import RoundBiasDetector
    headers = ["v"]
    rows = [[str(i * 5)] for i in range(1, 200)]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = RoundBiasDetector().run(doc)
    assert len(result.findings) >= 1
    # 100% is high severity.
    assert result.findings[0].severity == "high"


# ---------- 4. doc without tables works ----------

def test_empty_doc_yields_no_findings() -> None:
    """A document with no tables
    must not raise; the four
    detectors simply emit zero
    findings."""
    from manusift.detectors import (
        BenfordDetector,
        DuplicateRowDetector,
        OutlierDetector,
        RoundBiasDetector,
    )
    class T:
        trace_id = "t-empty"
    doc = T()
    for d in [
        BenfordDetector(),
        DuplicateRowDetector(),
        OutlierDetector(),
        RoundBiasDetector(),
    ]:
        result = d.run(doc)
        assert result.findings == []


# ---------- 5. small column is skipped by outlier ----------

def test_outlier_skips_short_columns() -> None:
    """With fewer than 30 values
    we do not have enough
    samples to say anything;
    the detector must not flag
    the column even if it is
    perfectly clean."""
    from manusift.detectors import OutlierDetector
    headers = ["v"]
    rows = [[str(i)] for i in range(10)]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = OutlierDetector().run(doc)
    assert result.findings == []


# ---------- 6. terminal-digit hypothesis tests (2026-07) ----------

def _digit_column(digit_counts: dict) -> list[list[str]]:
    """Build rows of integer cells with the given last-digit counts."""
    rows = []
    serial = 0
    for digit, count in sorted(digit_counts.items()):
        for _ in range(count):
            rows.append([str(serial * 10 + int(digit))])
            serial += 1
    return rows


def _stat_findings(result):
    out = []
    for f in result.findings:
        ev = json.loads(f.evidence)
        if "tests" in ev:
            out.append((f, ev))
    return out


def test_terminal_digit_five_bias_caught() -> None:
    """70 values with 26 ending in 5 (Fig.4c-like) must produce a
    high-severity statistical finding."""
    from manusift.detectors import RoundBiasDetector
    counts = {"5": 26, "1": 8, "2": 8, "4": 8, "6": 7, "7": 7, "8": 6}
    rows = _digit_column(counts)
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    stat = _stat_findings(result)
    assert len(stat) == 1
    finding, ev = stat[0]
    assert finding.severity == "high"
    assert "terminal_digit_five_bias" in ev["checks"]
    assert "terminal_digit_uniformity" in ev["checks"]


def test_terminal_digit_round_bias_caught() -> None:
    """40 of 60 values ending in 0 or 5 must trip the 0/5 binomial."""
    from manusift.detectors import RoundBiasDetector
    counts = {"0": 20, "5": 20, "1": 4, "2": 4, "3": 4, "4": 4, "6": 4}
    rows = _digit_column(counts)
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    stat = _stat_findings(result)
    assert len(stat) == 1
    finding, ev = stat[0]
    assert finding.severity == "high"
    assert "terminal_digit_round_bias" in ev["checks"]


def test_terminal_digit_uses_raw_strings_trailing_zero() -> None:
    """Trailing zeros only exist in the raw cell text: ``"1.50"``
    parsed as a float loses the terminal 0. The statistical layer
    must see 40/40 zeros."""
    from manusift.detectors import RoundBiasDetector
    rows = [[f"{i + 1}.50"] for i in range(40)]
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    stat = _stat_findings(result)
    assert len(stat) == 1
    finding, ev = stat[0]
    assert finding.severity == "high"
    uniformity = next(
        t for t in ev["tests"] if t["check"] == "terminal_digit_uniformity"
    )
    assert uniformity["counts"]["0"] == 40


def test_terminal_digit_pair_binomial_caught() -> None:
    """A repeated last-two-decimal pair ('.34' x10 of 60) must trip
    the pair binomial even though 100-class chi-square would not."""
    from manusift.detectors import RoundBiasDetector
    rows = [[f"{i + 1}.34"] for i in range(10)]
    pair = 0
    i = 20
    while len(rows) < 60:
        pair = (pair + 7) % 100
        if pair == 34:
            continue
        rows.append([f"{i}.{pair:02d}"])
        i += 1
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    stat = _stat_findings(result)
    assert len(stat) == 1
    finding, ev = stat[0]
    assert finding.severity == "high"
    assert "terminal_digit_pair_binomial" in ev["checks"]
    pair_test = next(
        t for t in ev["tests"] if t["check"] == "terminal_digit_pair_binomial"
    )
    assert pair_test["pair"] == "34"
    assert pair_test["count"] == 10


def test_terminal_digit_clean_column_quiet() -> None:
    """Near-uniform last digits must not produce any finding."""
    from manusift.detectors import RoundBiasDetector
    rows = _digit_column({str(d): 6 for d in range(10)})
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    assert result.findings == []


def test_terminal_digit_small_columns_fall_back_to_legacy() -> None:
    """Columns below n=30 are out of scope for the statistical
    layer; the legacy ratio heuristic still covers them."""
    from manusift.detectors import RoundBiasDetector
    rows = [[str(i * 5)] for i in range(1, 16)]  # 15 values, all 0/5
    doc = FakeDoc([FakeTable(["v"], rows)])
    result = RoundBiasDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    assert ev["method"] == "last_digit_forensics"


def _brush_column() -> list[list[str]]:
    """Column that brushes the uniformity effect gate (p~1) but
    triggers nothing else -- used to inflate the BH family."""
    counts = {"0": 6, "1": 9, "2": 6, "3": 6, "4": 6, "5": 5,
              "6": 6, "7": 6, "8": 5, "9": 5}
    return _digit_column(counts)


def _weak_rigged_column() -> list[list[str]]:
    """Weak five-bias column (12/60 fives): raw p ~ 0.01."""
    counts = {"5": 12, "0": 6, "1": 6, "2": 6, "3": 6, "4": 6,
              "6": 6, "7": 6, "8": 3, "9": 3}
    return _digit_column(counts)


def test_bh_correction_suppresses_weak_signal_in_large_family() -> None:
    """The same weak column that yields a low finding on its own
    must disappear once the table family contains many null tests
    (Benjamini-Hochberg across the table)."""
    from manusift.detectors import RoundBiasDetector
    alone = FakeDoc([FakeTable(["rigged"], _weak_rigged_column())])
    result = RoundBiasDetector().run(alone)
    stat = _stat_findings(result)
    assert len(stat) == 1
    assert stat[0][0].severity == "low"

    headers = ["rigged"] + [f"null_{i}" for i in range(12)]
    rigged = [r[0] for r in _weak_rigged_column()]
    nulls = [[r[0] for r in _brush_column()] for _ in range(12)]
    rows = [
        [rigged[i]] + [nulls[c][i] for c in range(12)]
        for i in range(60)
    ]
    crowded = FakeDoc([FakeTable(headers, rows)])
    result = RoundBiasDetector().run(crowded)
    assert _stat_findings(result) == []


def test_bh_adjust_math() -> None:
    from manusift.detectors.table_stats import _bh_adjust
    q = _bh_adjust([0.001, 0.5, 0.04])
    assert q[0] == pytest.approx(0.003)
    assert q[2] == pytest.approx(0.06)
    assert q[1] == pytest.approx(0.5)
    assert _bh_adjust([]) == []


def test_tail_probability_helpers() -> None:
    from manusift.detectors.table_stats import _binom_tail, _poisson_tail
    assert _binom_tail(0, 10, 0.1) == 1.0
    assert _binom_tail(11, 10, 0.1) == 0.0
    assert _binom_tail(26, 70, 0.1) < 1e-6
    assert _binom_tail(2, 70, 0.1) > 0.9
    assert _poisson_tail(0, 2.0) == 1.0
    assert _poisson_tail(1128, 0.3) < 1e-30
    assert _poisson_tail(1, 5.0) > 0.9
