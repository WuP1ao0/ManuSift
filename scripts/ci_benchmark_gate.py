"""CI regression gate for the ManuSift benchmarks (ROADMAP P5.2).

Runs the four benchmarks' ``run_smoke.py`` + aggregation scripts in
order, then enforces the gate rules:

  * fraud_representatives_v1 / fraud_web_v1: every smoke-OK case must
    have ``core_recall == 1.0`` (cases without a PDF are skipped by the
    smoke runner itself and carry ``core_recall: null`` — they do not
    count). Any case with ``status == "error"`` is also a regression.
  * negative_controls_v1: mean high-severity findings per legit paper
    must be <= 2.0 (read from ``fp_report.json``, written by
    ``build_fp_report.py``).
  * figure_text_v1: positive cases (non-empty
    ``expected_core_detectors``) must all hit ``core_recall == 1.0``;
    negative cases (``expected_absent_detectors``) must have zero of
    those detectors firing (read from ``smoke_runs.json`` +
    ``official_gold.json``).

Usage::

    python scripts/ci_benchmark_gate.py                 # full run + gate
    python scripts/ci_benchmark_gate.py --skip-run      # aggregate + gate only
    python scripts/ci_benchmark_gate.py --only fraud_web_v1 --skip-run

Exit code 0 = all rules green, 1 = at least one rule red (or a
benchmark step failed).

Smoke environment for the subprocesses matches HANDOFF.md §2:
calibration on, LLM enrichment off, figure-table OCR off, Crossref
citation-network off, Crossref offline cache replay on (CI never hits
the network).

Fault-injection verification (P5 acceptance, 2026-07-18):

    cp benchmarks/fraud_web_v1/smoke_runs.json /tmp/smoke_runs.bak
    # set one case's core_recall to 0.5 in smoke_runs.json, then:
    python scripts/ci_benchmark_gate.py --skip-run --only fraud_web_v1
    # -> [RED] fraud_web_v1 core recall ... exit code 1
    cp /tmp/smoke_runs.bak benchmarks/fraud_web_v1/smoke_runs.json

With the untouched artifacts, ``--skip-run`` is green on all four
benchmarks (fraud_representatives 12/12 with-PDF, fraud_web 13/13,
negative_controls high 0.00/paper, figure_text 5/5 positives, 0 FP).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SMOKE_ENV = {
    "MANUSIFT_FINDING_CALIBRATE": "1",
    "MANUSIFT_LLM_MAX_CONCURRENCY": "0",
    "MANUSIFT_LLM_ENRICH_MODE": "off",
    "MANUSIFT_FIGURE_TABLE_OCR": "0",
    "MANUSIFT_CROSSREF_ENABLED": "0",
    "MANUSIFT_CROSSREF_OFFLINE": "1",
}

HIGH_PER_PAPER_BUDGET = 2.0


@dataclass
class Benchmark:
    name: str
    kind: str  # "recall" | "fp" | "figure_text"
    run_script: str = "run_smoke.py"
    aggregate_script: str = "build_gap_report.py"

    def dir(self, root: Path) -> Path:
        return root / "benchmarks" / self.name


BENCHMARKS = [
    Benchmark("fraud_representatives_v1", "recall"),
    Benchmark("fraud_web_v1", "recall"),
    Benchmark(
        "negative_controls_v1", "fp", aggregate_script="build_fp_report.py"
    ),
    Benchmark("figure_text_v1", "figure_text"),
]


@dataclass
class RuleResult:
    benchmark: str
    ok: bool
    detail: str
    numbers: dict = field(default_factory=dict)


def _run_step(cmd: list[str], cwd: Path, env: dict) -> None:
    print(f"[gate] $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"step failed ({proc.returncode}): {' '.join(cmd)}")


def run_benchmark(bench: Benchmark, root: Path, skip_run: bool) -> None:
    """Run (unless skip_run) and always aggregate a benchmark."""
    bdir = bench.dir(root)
    env = dict(os.environ)
    env.update(SMOKE_ENV)
    if not skip_run:
        _run_step([sys.executable, str(bdir / bench.run_script)], bdir, env)
    _run_step([sys.executable, str(bdir / bench.aggregate_script)], bdir, env)


def check_recall_benchmark(bench_dir: Path, name: str) -> RuleResult:
    """Every smoke-OK case must have core_recall == 1.0; no errors."""
    runs = json.loads((bench_dir / "smoke_runs.json").read_text(encoding="utf-8"))
    errors = [r["case_id"] for r in runs if r.get("status") == "error"]
    scored = [r for r in runs if r.get("status") == "ok" and r.get("core_recall") is not None]
    misses = [r for r in scored if r["core_recall"] < 1.0]
    mean = sum(r["core_recall"] for r in scored) / len(scored) if scored else 0.0
    ok = not errors and not misses and bool(scored)
    detail = (
        f"core recall mean={mean:.3f} over {len(scored)} scored cases "
        f"({len(runs) - len(scored) - len(errors)} skipped/no-pdf); "
        f"errors={len(errors)}; cases below 1.0: "
        + (", ".join(f"{r['case_id']}={r['core_recall']}" for r in misses) or "none")
    )
    return RuleResult(
        name, ok, detail,
        {"mean_recall": mean, "n_scored": len(scored), "n_errors": len(errors)},
    )


def check_fp_benchmark(bench_dir: Path, name: str) -> RuleResult:
    """Mean high-severity findings per legit paper must be <= budget."""
    rep = json.loads((bench_dir / "fp_report.json").read_text(encoding="utf-8"))
    per_case = rep.get("per_case") or []
    if not per_case:
        return RuleResult(name, False, "fp_report.json has no per_case entries")
    total_high = sum(c.get("by_severity", {}).get("high", 0) for c in per_case)
    per_paper = total_high / len(per_case)
    ok = per_paper <= HIGH_PER_PAPER_BUDGET
    detail = (
        f"high findings/paper = {per_paper:.2f} "
        f"({total_high} high over {len(per_case)} controls); "
        f"budget <= {HIGH_PER_PAPER_BUDGET}"
    )
    return RuleResult(
        name, ok, detail,
        {"high_per_paper": per_paper, "total_high": total_high, "n_controls": len(per_case)},
    )


def check_figure_text_benchmark(bench_dir: Path, name: str) -> RuleResult:
    """Positives: core_recall == 1.0. Negatives: zero absent-detector FPs."""
    runs = json.loads((bench_dir / "smoke_runs.json").read_text(encoding="utf-8"))
    errors = [r["case_id"] for r in runs if r.get("status") == "error"]
    pos_misses: list[str] = []
    fp_cases: list[str] = []
    n_pos = n_neg = 0
    for r in runs:
        if r.get("status") != "ok":
            continue
        cid = r["case_id"]
        golds = list((bench_dir / "cases").glob(f"*/{cid}/official_gold.json"))
        if not golds:
            return RuleResult(name, False, f"gold not found for case {cid}")
        gold = json.loads(golds[0].read_text(encoding="utf-8"))
        by_det = r.get("by_detector") or {}
        if gold.get("expected_core_detectors"):
            n_pos += 1
            if (r.get("core_recall") or 0.0) < 1.0:
                pos_misses.append(f"{cid}={r.get('core_recall')}")
        else:
            n_neg += 1
            absent = set(gold.get("expected_absent_detectors") or [])
            fired = sorted(d for d in absent if by_det.get(d, 0) > 0)
            if fired:
                fp_cases.append(f"{cid} ({', '.join(fired)})")
    ok = not errors and not pos_misses and not fp_cases and n_pos > 0
    detail = (
        f"positives {n_pos - len(pos_misses)}/{n_pos} recall 1.0; "
        f"negatives {n_neg} with {len(fp_cases)} FP; errors={len(errors)}"
    )
    if pos_misses:
        detail += "; pos below 1.0: " + ", ".join(pos_misses)
    if fp_cases:
        detail += "; FP: " + ", ".join(fp_cases)
    return RuleResult(
        name, ok, detail,
        {"n_pos": n_pos, "n_neg": n_neg, "n_fp": len(fp_cases), "n_errors": len(errors)},
    )


CHECKERS = {
    "recall": check_recall_benchmark,
    "fp": check_fp_benchmark,
    "figure_text": check_figure_text_benchmark,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--skip-run",
        action="store_true",
        help="only aggregate persisted artifacts and check the gate rules",
    )
    ap.add_argument(
        "--only",
        choices=[b.name for b in BENCHMARKS],
        help="run/check a single benchmark",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repo root containing benchmarks/ (default: script's repo)",
    )
    args = ap.parse_args(argv)

    benches = [b for b in BENCHMARKS if args.only in (None, b.name)]
    results: list[RuleResult] = []
    for bench in benches:
        print(f"[gate] === {bench.name} ===", flush=True)
        try:
            run_benchmark(bench, args.root, args.skip_run)
            results.append(CHECKERS[bench.kind](bench.dir(args.root), bench.name))
        except Exception as exc:  # noqa: BLE001 — gate must report, not crash
            results.append(RuleResult(bench.name, False, f"step failed: {exc}"))

    print("\n[gate] ===== gate results =====")
    for res in results:
        tag = "GREEN" if res.ok else "RED  "
        print(f"[{tag}] {res.benchmark}: {res.detail}")
    n_red = sum(1 for r in results if not r.ok)
    print(f"[gate] {len(results) - n_red}/{len(results)} rules green")
    return 1 if n_red else 0


if __name__ == "__main__":
    raise SystemExit(main())
