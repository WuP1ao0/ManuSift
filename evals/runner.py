"""ManuSift eval runner.

Reads ``evals/cases/*.json``, runs the pipeline against each fixture
PDF, and checks the resulting findings against the case's ``expect``
block.

Usage::

    ./.venv/Scripts/python.exe -m evals.runner
    ./.venv/Scripts/python.exe -m evals.runner --case 02_duplicate_image
    ./.venv/Scripts/python.exe -m pytest -q tests/test_evals.py

The runner depends on no LLM and is meant to be fast enough to run
on every save during development.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from manusift.config import get_settings
from manusift.contracts import AnalysisResult, Finding, JobState
from manusift.ingest.pdf import parse_pdf
from manusift.pipeline import run_pipeline
from manusift.trace import bind_trace_id, configure_logging, new_trace_id
from manusift.workspace import JobPaths


CASES_DIR = Path(__file__).parent / "cases"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class CaseResult:
    name: str
    passed: bool
    finding_count: int
    duration_ms: int
    failures: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


# ---------- expectation checker ----------

def _matches(filter_: dict[str, Any], f: Finding) -> bool:
    """Does a Finding satisfy the filter dict?

    Supported keys: ``detector``, ``severity``, ``check`` (raw.check),
    ``raw_kind`` (raw.kind), ``title_contains`` (case-insensitive).
    """
    if "detector" in filter_ and f.detector != filter_["detector"]:
        return False
    if "severity" in filter_ and f.severity != filter_["severity"]:
        return False
    if "check" in filter_ and f.raw.get("check") != filter_["check"]:
        return False
    if "raw_kind" in filter_ and f.raw.get("kind") != filter_["raw_kind"]:
        return False
    if "title_contains" in filter_:
        needle = str(filter_["title_contains"]).lower()
        if needle not in f.title.lower():
            return False
    return True


def _check_expectation(
    expect: dict[str, Any], findings: list[Finding]
) -> list[str]:
    failures: list[str] = []
    n = len(findings)

    if "min_findings" in expect and n < int(expect["min_findings"]):
        failures.append(
            f"min_findings: expected >= {expect['min_findings']}, got {n}"
        )
    if "max_findings" in expect and n > int(expect["max_findings"]):
        failures.append(
            f"max_findings: expected <= {expect['max_findings']}, got {n}"
        )

    for i, f_spec in enumerate(expect.get("must_contain", [])):
        min_count = int(f_spec.get("min_count", 1))
        matched = sum(1 for f in findings if _matches(f_spec, f))
        if matched < min_count:
            failures.append(
                f"must_contain[{i}]: expected >= {min_count} match(es) for "
                f"{f_spec}, got {matched}"
            )

    for i, f_spec in enumerate(expect.get("must_not_contain", [])):
        matched = [f for f in findings if _matches(f_spec, f)]
        if matched:
            failures.append(
                f"must_not_contain[{i}]: expected 0 matches for {f_spec}, "
                f"got {len(matched)}"
            )

    return failures


# ---------- runner ----------

def _is_case_skipped(case: dict[str, Any]) -> tuple[bool, str]:
    """Check whether the case should be skipped.

    A case can opt into an environment-gated skip by setting
    ``"skip_unless_env": "SOME_VAR"`` at the top level. This is how
    LLM-dependent cases signal "skip me unless MANUSIFT_LLM_EVALS=1".
    """
    env_var = case.get("skip_unless_env")
    if env_var and not os.environ.get(env_var):
        return True, f"set {env_var}=1 to enable"
    return False, ""


def _run_one(case: dict[str, Any]) -> CaseResult:
    name = case["name"]
    skipped, reason = _is_case_skipped(case)
    if skipped:
        return CaseResult(
            name=name,
            passed=True,
            finding_count=0,
            duration_ms=0,
            skipped=True,
            skip_reason=reason,
        )
    fixture_path = FIXTURES_DIR / case["fixture"]
    if not fixture_path.exists():
        return CaseResult(
            name=name,
            passed=False,
            finding_count=0,
            duration_ms=0,
            failures=[f"fixture not found: {fixture_path}"],
        )

    settings = get_settings()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    tid = new_trace_id()
    bind_trace_id(tid)

    paths = JobPaths.for_trace(tid, settings.workspace_dir)
    paths.ensure()
    paths.original.write_bytes(fixture_path.read_bytes())
    job = JobState(trace_id=tid, status="queued", source_filename=case["fixture"])

    t0 = time.time()
    try:
        result: AnalysisResult = run_pipeline(paths.original, paths, job)
    except Exception as exc:  # noqa: BLE001
        return CaseResult(
            name=name,
            passed=False,
            finding_count=0,
            duration_ms=int((time.time() - t0) * 1000),
            failures=[f"pipeline crashed: {type(exc).__name__}: {exc}"],
        )

    duration_ms = int((time.time() - t0) * 1000)
    failures = _check_expectation(case.get("expect", {}), result.findings)
    return CaseResult(
        name=name,
        passed=not failures,
        finding_count=len(result.findings),
        duration_ms=duration_ms,
        failures=failures,
    )


def _load_cases(filter_name: str | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(CASES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            case = json.load(f)
        if filter_name and filter_name not in case["name"]:
            continue
        cases.append(case)
    return cases


def _print_report(results: list[CaseResult]) -> None:
    print("")
    print("=" * 70)
    print("ManuSift eval report")
    print("=" * 70)
    width = max(len(r.name) for r in results) if results else 0
    for r in results:
        if r.skipped:
            status = "SKIP"
        elif r.passed:
            status = "PASS"
        else:
            status = "FAIL"
        suffix = f"  ({r.skip_reason})" if r.skipped else ""
        print(
            f"  [{status}] {r.name.ljust(width)}  "
            f"findings={r.finding_count:>3}  {r.duration_ms:>4}ms{suffix}"
        )
        for fail in r.failures:
            print(f"           - {fail}")
    n_pass = sum(1 for r in results if r.passed and not r.skipped)
    n_skip = sum(1 for r in results if r.skipped)
    n_fail = len(results) - n_pass - n_skip
    print("-" * 70)
    print(
        f"  {n_pass} passed, {n_fail} failed, {n_skip} skipped  "
        f"({len(results)} total)"
    )
    print("=" * 70)


def main(argv: list[str] | None = None) -> int:
    configure_logging(level="WARNING")
    parser = argparse.ArgumentParser(prog="manusift-evals")
    parser.add_argument(
        "--case", default=None, help="Substring filter: only run cases whose name contains this"
    )
    args = parser.parse_args(argv)

    cases = _load_cases(args.case)
    if not cases:
        print(f"No cases found in {CASES_DIR} (filter={args.case!r})", file=sys.stderr)
        return 2

    results = [_run_one(c) for c in cases]
    _print_report(results)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
