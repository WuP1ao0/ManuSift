"""Unit tests for scripts/ci_benchmark_gate.py gate rules.

These tests never run the real benchmarks; they build fake
smoke_runs.json / fp_report.json / official_gold.json artifacts in tmp
dirs and exercise the rule checkers plus the --skip-run CLI path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ci_benchmark_gate as gate  # noqa: E402


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _recall_runs(recalls, *, errors=0, skipped=0):
    runs = [
        {"case_id": f"case{i:03d}", "status": "ok", "core_recall": r}
        for i, r in enumerate(recalls)
    ]
    runs += [
        {"case_id": f"err{i}", "status": "error", "error": "boom"}
        for i in range(errors)
    ]
    runs += [
        {"case_id": f"skip{i}", "status": "skipped_no_pdf", "core_recall": None}
        for i in range(skipped)
    ]
    return runs


# --- recall rule ---------------------------------------------------------


def test_recall_all_perfect_is_green(tmp_path):
    _write_json(tmp_path / "smoke_runs.json", _recall_runs([1.0, 1.0, 1.0], skipped=2))
    res = gate.check_recall_benchmark(tmp_path, "fake_recall")
    assert res.ok
    assert res.numbers["n_scored"] == 3


def test_recall_below_one_is_red(tmp_path):
    _write_json(tmp_path / "smoke_runs.json", _recall_runs([1.0, 0.99, 1.0]))
    res = gate.check_recall_benchmark(tmp_path, "fake_recall")
    assert not res.ok
    assert "0.99" in res.detail


def test_recall_error_status_is_red(tmp_path):
    _write_json(tmp_path / "smoke_runs.json", _recall_runs([1.0], errors=1))
    res = gate.check_recall_benchmark(tmp_path, "fake_recall")
    assert not res.ok
    assert res.numbers["n_errors"] == 1


def test_recall_no_scored_cases_is_red(tmp_path):
    _write_json(tmp_path / "smoke_runs.json", _recall_runs([], skipped=3))
    res = gate.check_recall_benchmark(tmp_path, "fake_recall")
    assert not res.ok


# --- negative-controls FP budget rule ------------------------------------


def _fp_report(high_counts):
    return {
        "per_case": [
            {"case": f"ctrl{i:03d}", "n_findings": h, "by_severity": {"high": h}}
            for i, h in enumerate(high_counts)
        ]
    }


def test_fp_budget_zero_high_is_green(tmp_path):
    _write_json(tmp_path / "fp_report.json", _fp_report([0] * 16))
    res = gate.check_fp_benchmark(tmp_path, "fake_controls")
    assert res.ok
    assert res.numbers["high_per_paper"] == 0.0


def test_fp_budget_at_limit_is_green(tmp_path):
    _write_json(tmp_path / "fp_report.json", _fp_report([2, 2, 0, 0]))
    res = gate.check_fp_benchmark(tmp_path, "fake_controls")
    assert res.ok


def test_fp_budget_above_limit_is_red(tmp_path):
    # 21 high over 10 papers = 2.1/paper > 2.0
    _write_json(tmp_path / "fp_report.json", _fp_report([3] * 7 + [0] * 3))
    res = gate.check_fp_benchmark(tmp_path, "fake_controls")
    assert not res.ok
    assert res.numbers["high_per_paper"] == pytest.approx(2.1)


def test_fp_budget_empty_report_is_red(tmp_path):
    _write_json(tmp_path / "fp_report.json", {"per_case": []})
    res = gate.check_fp_benchmark(tmp_path, "fake_controls")
    assert not res.ok


# --- figure_text rule ------------------------------------------------------


def _figure_text_fixture(tmp_path, pos_recalls, neg_fired):
    """pos_recalls: list[float]; neg_fired: list[list[str]] detectors fired
    per negative case (subset of expected_absent_detectors => FP)."""
    runs = []
    for i, r in enumerate(pos_recalls):
        cid = f"pos{i:03d}"
        _write_json(
            tmp_path / "cases" / "synthetic" / cid / "official_gold.json",
            {"case_id": cid, "expected_core_detectors": ["figure_table_consistency"]},
        )
        runs.append({
            "case_id": cid, "status": "ok", "core_recall": r,
            "by_detector": {"figure_table_consistency": 1} if r == 1.0 else {},
        })
    for i, fired in enumerate(neg_fired):
        cid = f"neg{i:03d}"
        _write_json(
            tmp_path / "cases" / "synthetic" / cid / "official_gold.json",
            {
                "case_id": cid,
                "expected_core_detectors": [],
                "expected_absent_detectors": ["figure_table_consistency"],
            },
        )
        runs.append({
            "case_id": cid, "status": "ok", "core_recall": None,
            "by_detector": dict.fromkeys(fired, 1),
        })
    _write_json(tmp_path / "smoke_runs.json", runs)


def test_figure_text_clean_is_green(tmp_path):
    _figure_text_fixture(tmp_path, [1.0] * 5, [[], [], []])
    res = gate.check_figure_text_benchmark(tmp_path, "fake_figtext")
    assert res.ok
    assert res.numbers == {"n_pos": 5, "n_neg": 3, "n_fp": 0, "n_errors": 0}


def test_figure_text_positive_miss_is_red(tmp_path):
    _figure_text_fixture(tmp_path, [1.0, 1.0, 0.0], [[]])
    res = gate.check_figure_text_benchmark(tmp_path, "fake_figtext")
    assert not res.ok
    assert "pos002" in res.detail


def test_figure_text_negative_fp_is_red(tmp_path):
    _figure_text_fixture(tmp_path, [1.0] * 2, [["figure_table_consistency"]])
    res = gate.check_figure_text_benchmark(tmp_path, "fake_figtext")
    assert not res.ok
    assert res.numbers["n_fp"] == 1
    assert "FALSE" not in res.detail  # wording check: detail mentions FP list
    assert "neg000" in res.detail


# --- CLI --skip-run end-to-end on a fake tree ------------------------------


def _stub_script(bench_dir: Path, name: str) -> None:
    # Aggregate scripts are invoked even in --skip-run mode; stub them as
    # no-ops so the CLI test does not touch the real benchmark tree.
    (bench_dir / name).write_text("pass\n", encoding="utf-8")


def test_main_skip_run_green(tmp_path):
    for bench in gate.BENCHMARKS:
        bdir = tmp_path / "benchmarks" / bench.name
        bdir.mkdir(parents=True)
        _stub_script(bdir, bench.aggregate_script)
    _write_json(
        tmp_path / "benchmarks" / "fraud_representatives_v1" / "smoke_runs.json",
        _recall_runs([1.0, 1.0], skipped=1),
    )
    _write_json(
        tmp_path / "benchmarks" / "fraud_web_v1" / "smoke_runs.json",
        _recall_runs([1.0]),
    )
    _write_json(
        tmp_path / "benchmarks" / "negative_controls_v1" / "fp_report.json",
        _fp_report([0] * 4),
    )
    _figure_text_fixture(
        tmp_path / "benchmarks" / "figure_text_v1", [1.0, 1.0], [[]]
    )
    rc = gate.main(["--skip-run", "--root", str(tmp_path)])
    assert rc == 0


def test_main_skip_run_fault_injection_red(tmp_path):
    for bench in gate.BENCHMARKS:
        bdir = tmp_path / "benchmarks" / bench.name
        bdir.mkdir(parents=True)
        _stub_script(bdir, bench.aggregate_script)
    _write_json(
        tmp_path / "benchmarks" / "fraud_representatives_v1" / "smoke_runs.json",
        _recall_runs([1.0, 0.5]),  # injected regression
    )
    _write_json(
        tmp_path / "benchmarks" / "fraud_web_v1" / "smoke_runs.json",
        _recall_runs([1.0]),
    )
    _write_json(
        tmp_path / "benchmarks" / "negative_controls_v1" / "fp_report.json",
        _fp_report([0] * 4),
    )
    _figure_text_fixture(
        tmp_path / "benchmarks" / "figure_text_v1", [1.0], [[]]
    )
    rc = gate.main(["--skip-run", "--root", str(tmp_path)])
    assert rc == 1


def test_main_only_selects_one_benchmark(tmp_path):
    bdir = tmp_path / "benchmarks" / "fraud_web_v1"
    bdir.mkdir(parents=True)
    _stub_script(bdir, "build_gap_report.py")
    _write_json(bdir / "smoke_runs.json", _recall_runs([1.0]))
    rc = gate.main(["--skip-run", "--only", "fraud_web_v1", "--root", str(tmp_path)])
    assert rc == 0
