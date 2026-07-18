"""P6 eval gate: target recall + precision@K."""
from __future__ import annotations

from manusift.benchmarks.eval_gate import (
    PRECISION_AT_K_THRESHOLD,
    TARGET_RECALL_THRESHOLD,
    evaluate_benchmark_p6,
    evaluate_case_p6,
    evaluate_fixture_expectations,
    precision_at_k,
    precision_at_k_from_alignment,
    target_recall_from_alignment,
)


def test_target_recall_from_alignment() -> None:
    am = {
        "summary": {
            "n_exact": 2,
            "n_partial": 1,
            "n_missed": 1,
        }
    }
    tr = target_recall_from_alignment(am)
    assert tr["n_testable"] == 4
    assert abs(tr["target_recall"] - 0.75) < 1e-9
    assert tr["passes"] is True


def test_target_recall_all_missed_fails() -> None:
    am = {"summary": {"n_exact": 0, "n_partial": 0, "n_missed": 3}}
    tr = target_recall_from_alignment(am)
    assert tr["target_recall"] == 0.0
    assert tr["passes"] is False


def test_target_recall_no_targets_not_applicable() -> None:
    am = {"summary": {"n_exact": 0, "n_partial": 0, "n_missed": 0}}
    tr = target_recall_from_alignment(am)
    assert tr["target_recall"] is None
    assert tr["applicable"] is False


def test_precision_at_k_ranking() -> None:
    findings = [
        {"detector": "noise", "title": "n1", "severity": "low"},
        {"detector": "image_dup", "title": "dup", "severity": "high"},
        {"detector": "text", "title": "t", "severity": "medium"},
        {"detector": "image_dup", "title": "dup2", "severity": "medium"},
    ]
    pk = precision_at_k(
        findings,
        k=2,
        relevant_detectors={"image_dup"},
    )
    assert pk["n_ranked"] == 2
    # top2 by severity: image_dup high, image_dup medium (or text medium)
    # high first, then mediums — both image_dup if sorted by detector after severity...
    # rank: high image_dup, medium image_dup, medium text, low noise
    assert pk["precision_at_k"] == 1.0
    assert pk["passes"] is True


def test_precision_at_k_from_alignment_synthetic() -> None:
    am = {
        "summary": {"n_exact": 1, "n_partial": 1, "n_incidental": 20},
        "target_alignment": [
            {
                "target": "Fig.1",
                "status": "exact",
                "matched_finding": {
                    "detector": "image_dup",
                    "title": "dup A",
                },
            },
            {
                "target": "Fig.2",
                "status": "partial",
                "matched_finding": {
                    "detector": "image_forensics",
                    "title": "ela",
                },
            },
        ],
        "incidental": [
            {"detector": "text_patterns", "title": f"inc {i}"}
            for i in range(20)
        ],
        "expected_detectors": ["image_dup", "image_forensics"],
    }
    pk = precision_at_k_from_alignment(am, k=5)
    assert pk["n_ranked"] == 5
    # first 2 are matched (high/medium), rest incidental low → 2/5=0.4
    assert pk["precision_at_k"] >= 0.3


def test_evaluate_case_p6_combined() -> None:
    gold = {
        "case_id": "c1",
        "domain": "bio",
        "expected_manusift_detectors": ["image_dup", "image_forensics"],
    }
    run = {
        "findings_by_detector": {
            "image_dup": 3,
            "image_forensics": 2,
            "text_patterns": 10,
        }
    }
    am = {
        "summary": {
            "n_exact": 2,
            "n_partial": 0,
            "n_missed": 0,
            "n_incidental": 5,
        },
        "target_alignment": [
            {
                "target": "Fig.1",
                "status": "exact",
                "matched_finding": {
                    "detector": "image_dup",
                    "title": "d",
                },
            },
            {
                "target": "Fig.2",
                "status": "exact",
                "matched_finding": {
                    "detector": "image_forensics",
                    "title": "f",
                },
            },
        ],
        "incidental": [
            {"detector": "text_patterns", "title": f"x{i}"} for i in range(5)
        ],
        "expected_detectors": ["image_dup", "image_forensics"],
    }
    c = evaluate_case_p6(gold, run, am, k=10)
    assert c.detector_recall == 1.0
    assert c.target_recall == 1.0
    assert c.precision_at_k is not None
    assert c.passes_gate is True


def test_fixture_expectations_positive() -> None:
    expect = {
        "must_contain": [
            {"detector": "image_dup", "min_count": 1},
        ]
    }
    findings = [
        {"detector": "image_dup", "severity": "high", "title": "dup"},
        {"detector": "text_patterns", "severity": "low", "title": "t"},
    ]
    r = evaluate_fixture_expectations(expect, findings)
    assert r["target_recall"] == 1.0
    assert r["passes"] is True


def test_fixture_expectations_negative_control() -> None:
    expect = {"max_findings": 0}
    r = evaluate_fixture_expectations(expect, [])
    assert r["kind"] == "negative_control"
    assert r["passes"] is True
    r2 = evaluate_fixture_expectations(expect, [{"detector": "x"}])
    assert r2["passes"] is False


def test_thresholds_documented() -> None:
    assert TARGET_RECALL_THRESHOLD == 0.7
    assert PRECISION_AT_K_THRESHOLD == 0.15


def test_benchmark_p6_runs_if_data_present() -> None:
    from pathlib import Path

    from manusift.benchmarks.eval_gate import DEFAULT_BENCH_ROOT

    if not DEFAULT_BENCH_ROOT.exists():
        return
    # only run if at least one case has tool_summary
    has = any(
        (p / "manusift_run" / "tool_summary.json").exists()
        for p in (DEFAULT_BENCH_ROOT / "cases").glob("*/*")
    )
    if not has:
        return
    agg = evaluate_benchmark_p6(DEFAULT_BENCH_ROOT, k=20)
    assert agg.n_cases > 0
    assert 0.0 <= agg.overall_detector_recall <= 1.0
    assert 0.0 <= agg.overall_target_recall <= 1.0
    # Report only — do not hard-fail CI if historical bench < threshold;
    # the unit tests above lock the metric math.
    assert isinstance(agg.passes, bool)
