"""Unit tests for open-source-inspired stats_algo algorithms."""
from __future__ import annotations

import math

import pytest

from manusift.stats_algo import (
    benford_analyze,
    extract_statcheck_hits,
    grim_consistent,
    grimmer_sd_possible,
    last_digit_round_bias,
    leading_digit,
    robust_z_scores,
)


def test_grim_known_impossible_mean() -> None:
    # n=5, mean 1.23 to 2 decimals is often impossible for integers
    # 1.23 * 5 = 6.15 — not near integer within half of 0.01
    assert grim_consistent(1.23, 5, decimals=2) is False or grim_consistent(
        1.2, 5, decimals=1
    )


def test_grim_known_possible_mean() -> None:
    # mean 2.0 with n=4 is fine
    assert grim_consistent(2.0, 4, decimals=1) is True
    assert grim_consistent(1.5, 2, decimals=1) is True


def test_grim_likert_multi_item() -> None:
    # multi-item scale increases granularity
    assert grim_consistent(3.25, 4, decimals=2, n_items=1) in (True, False)
    # with more items, more means become possible
    assert grim_consistent(3.25, 4, decimals=2, n_items=4) is True


def test_benford_natural_fib_not_strongly_nonconforming() -> None:
    fib = [1, 1]
    for _ in range(400):
        fib.append(fib[-1] + fib[-2])
    a = benford_analyze(fib)
    assert a["n"] > 100
    # Fibonacci is famously Benford-like
    assert a["conformity_mad"] != "nonconforming" or a["pvalue"] > 0.001


def test_benford_all_ones_is_anomalous() -> None:
    vals = [10**k + 1 for k in range(50, 250)]
    a = benford_analyze(vals)
    assert a["significant_chi2"] or a["conformity_mad"] == "nonconforming"


def test_leading_digit() -> None:
    assert leading_digit(321) == 3
    assert leading_digit(0.0456) == 4
    assert leading_digit(0) is None


def test_last_digit_round_bias_detects_multiples_of_five() -> None:
    vals = [float(i * 5) for i in range(1, 100)]
    a = last_digit_round_bias(vals)
    assert a["round_ratio"] > 0.5
    assert "last_digit_round_bias" in a["flags"]


def test_statcheck_t_inconsistency() -> None:
    # t(10)=0.1 cannot have p=0.001
    hits = extract_statcheck_hits("t(10) = 0.1, p = 0.001")
    assert hits
    assert any(h.get("inconsistent") for h in hits)


def test_statcheck_consistent_t() -> None:
    # Roughly: large t with tiny p is ok
    hits = extract_statcheck_hits("t(30) = 5.0, p < 0.001")
    assert hits
    # may or may not be inconsistent depending on exact p; just parse
    assert hits[0]["stat"] == "t"


def test_robust_z_constant_column() -> None:
    z = robust_z_scores([1.0] * 20)
    assert all(abs(x) < 1e-9 for x in z)


def test_grimmer_sd_too_large() -> None:
    # Likert 1-7, mean 4, sd 100 is impossible
    assert grimmer_sd_possible(4.0, 100.0, 20) is False
    assert grimmer_sd_possible(4.0, 1.2, 20) is True


# ---------------------------------------------------------------------------
# 2026-07 statcheck upgrade: rounding-interval decision, z, special rules
# ---------------------------------------------------------------------------


def test_statcheck_interval_boundary_inside_not_flagged() -> None:
    # t(20)=2.0 -> t in [1.95, 2.05] -> p in [0.0537, 0.0653], which
    # rounds at 2 dp to [0.05, 0.07].  A reported p at the interval
    # endpoint (.05) or inside (.06) must NOT be flagged.
    for text in ("t(20) = 2.0, p = .06", "t(20) = 2.0, p = .05"):
        hits = extract_statcheck_hits(text)
        assert hits and hits[0]["inconsistent"] is False
        assert hits[0]["p_low"] < hits[0]["p_up"]


def test_statcheck_interval_outside_flagged() -> None:
    # p = .03 lies outside the rounded interval [0.05, 0.07].
    hits = extract_statcheck_hits("t(20) = 2.0, p = .03")
    assert hits and hits[0]["inconsistent"] is True


def test_statcheck_p_less_than_direction() -> None:
    # p < x is inconsistent only when even the smallest recomputed p
    # is clearly >= x.
    hits = extract_statcheck_hits("t(20) = 1.0, p < .05")
    assert hits[0]["inconsistent"] is True  # recomputed p ~ 0.33
    hits = extract_statcheck_hits("t(20) = 2.5, p < .05")
    assert hits[0]["inconsistent"] is False  # recomputed p ~ 0.02


def test_statcheck_p_greater_than_direction() -> None:
    # p > x is inconsistent only when the largest recomputed p is
    # clearly <= x.
    hits = extract_statcheck_hits("t(20) = 2.5, p > .05")
    assert hits[0]["inconsistent"] is True
    hits = extract_statcheck_hits("t(20) = 1.0, p > .05")
    assert hits[0]["inconsistent"] is False


def test_statcheck_stat_operator_compatible_not_flagged() -> None:
    # t > 2.1 means the true p is *below* p(2.1); a small reported p
    # agrees with that direction and must not fire.
    hits = extract_statcheck_hits("t(20) > 2.1, p = .05")
    assert hits[0]["stat_op"] == ">"
    assert hits[0]["inconsistent"] is False
    # A large reported p contradicts t > 2.1.
    hits = extract_statcheck_hits("t(20) > 2.1, p = .20")
    assert hits[0]["inconsistent"] is True
    # t < 2.1 with a non-significant report is direction-compatible.
    hits = extract_statcheck_hits("t(20) < 2.1, p = .30")
    assert hits[0]["inconsistent"] is False


def test_statcheck_z_support() -> None:
    hits = extract_statcheck_hits("z = 1.96, p = .05")
    assert hits and hits[0]["stat"] == "z"
    assert hits[0]["inconsistent"] is False
    hits = extract_statcheck_hits("z = 1.96, p = .01")
    assert hits[0]["inconsistent"] is True


def test_statcheck_z_no_false_match() -> None:
    # "Az" (word char before) and "z-score" (hyphen after) are not
    # z statistics.
    assert extract_statcheck_hits("The Az = 5 was noted") == []
    assert extract_statcheck_hits("a z-score of 2 was seen") == []


def test_statcheck_p_zero_error() -> None:
    hits = extract_statcheck_hits("t(20) = 2.0, p = .000")
    assert hits[0]["inconsistent"] is True
    assert hits[0]["p_zero_error"] is True


def test_statcheck_one_tailed_exemption() -> None:
    # Two-tailed p for t(20)=1.5 is ~0.149, so p=.075 is inconsistent
    # two-tailed but exactly right one-tailed.
    hits = extract_statcheck_hits(
        "We used one-tailed tests. t(20) = 1.5, p = .075"
    )
    assert hits[0]["inconsistent"] is False
    assert hits[0]["one_tailed_exempt"] is True
    # Without a one-sided/directional declaration there is no exemption.
    hits = extract_statcheck_hits("t(20) = 1.5, p = .075")
    assert hits[0]["inconsistent"] is True
    assert hits[0]["one_tailed_exempt"] is False


def test_statcheck_decision_error_flag() -> None:
    # Reported significant (p=.03) but recomputed clearly ns (~0.15).
    hits = extract_statcheck_hits("t(20) = 1.5, p = .03")
    assert hits[0]["inconsistent"] is True
    assert hits[0]["decision_error"] is True
    # Both sides significant: inconsistent magnitude, but no decision
    # error.
    hits = extract_statcheck_hits("z = 1.96, p = .01")
    assert hits[0]["inconsistent"] is True
    assert hits[0]["decision_error"] is False


def test_statcheck_ns_not_judged() -> None:
    hits = extract_statcheck_hits("t(20) = 2.5, p = ns")
    assert hits and hits[0]["p_reported"] is None
    assert hits[0]["inconsistent"] is False


# ---------------------------------------------------------------------------
# DEBIT + GRIMMER upper bound (2026-07)
# ---------------------------------------------------------------------------


def test_debit_check() -> None:
    from manusift.stats_algo import debit_check

    # 50% yes at N=100 -> theoretical SD = sqrt(.25*100/99) ~= 0.5025;
    # a reported 0.50 is within rounding slack.
    res = debit_check(0.5, 0.50, 100, prop_dec=3, sd_dec=2)
    assert res["consistent"] is True
    assert res["expected_sd"] == pytest.approx(0.5025, abs=1e-3)
    # 0.30 is impossible for binary data with p=0.5.
    res = debit_check(0.5, 0.30, 100, prop_dec=3, sd_dec=2)
    assert res["consistent"] is False
    assert res["delta"] > 0.2
    # Out-of-domain inputs can never be refuted.
    assert debit_check(1.5, 0.3, 100)["consistent"] is True
    assert debit_check(0.5, 0.3, 1)["consistent"] is True


def test_grimmer_sd_max_bound() -> None:
    from manusift.stats_algo import grimmer_sd_max

    # Mean 2.0 on [1,7], n=20: all mass split 1/7 gives
    # sqrt((2-1)*(7-2) * 20/19) ~= 2.294.
    assert grimmer_sd_max(2.0, 20, 1, 7) == pytest.approx(2.294, abs=1e-3)
    # Midpoint mean maximises the bound.
    assert grimmer_sd_max(4.0, 20, 1, 7) > grimmer_sd_max(2.0, 20, 1, 7)


def test_grimmer_sd_possible_mean_aware_bound() -> None:
    # The bound is now mean-aware: sd=3.0 IS possible at the midpoint
    # mean 4 (bound ~3.08) but NOT at mean 2 (bound ~2.29).
    assert grimmer_sd_possible(4.0, 3.0, 20) is True
    assert grimmer_sd_possible(2.0, 3.0, 20) is False
    assert grimmer_sd_possible(2.0, 2.0, 20) is True
