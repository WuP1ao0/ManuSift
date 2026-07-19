"""End-to-end eval runner: drives the FastAPI app via TestClient.

Unlike the pipeline-level runner in :mod:`evals.runner`, this one
goes through ``POST /api/upload`` → polling → ``GET /report`` and
checks the full HTTP surface, not just the detector output.

The fixture PDFs are the same as for the pipeline-level suite (see
``evals/fixtures/``).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.runner import CaseResult, _check_expectation, FIXTURES_DIR


E2E_CASES_DIR = Path(__file__).parent / "cases" / "e2e"

# How long to poll the job before giving up. Generous — 5s is plenty
# for a 1-page fixture PDF, but the smoke CI box might be slow.
_POLL_TIMEOUT_S = 10.0
_POLL_INTERVAL_S = 0.1


def _load_e2e_cases(filter_name: str | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(E2E_CASES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            case = json.load(f)
        if filter_name and filter_name not in case["name"]:
            continue
        cases.append(case)
    return cases


def _run_e2e_one(case: dict[str, Any], tmp_workspace: Path) -> CaseResult:
    """Drive the FastAPI app through TestClient against one fixture.

    ``tmp_workspace`` is supplied by the caller so the test can be
    run from both the CLI and pytest with the same isolation
    guarantees.
    """
    name = case["name"]
    fixture_path = FIXTURES_DIR / case["fixture"]
    failures: list[str] = []

    if not fixture_path.exists():
        return CaseResult(
            name=name, passed=False, finding_count=0, duration_ms=0,
            failures=[f"fixture not found: {fixture_path}"],
        )

    # Set workspace before importing the app so get_settings() picks
    # it up on first read.
    import os
    old_workspace = os.environ.get("MANUSIFT_WORKSPACE_DIR")
    os.environ["MANUSIFT_WORKSPACE_DIR"] = str(tmp_workspace)
    try:
        # Late imports so the env var is in place.
        from fastapi.testclient import TestClient
        from manusift.llm import client as llm_client
        from manusift.web.app import create_app

        # Reset module-level singletons that hold workspace-bound state.
        # The LLM client has no workspace state but its own singleton
        # is process-global; reset for hygiene.
        llm_client._reset_for_tests()

        app = create_app()
        t0 = time.time()

        with TestClient(app) as client:
            # 1. Upload.
            with open(fixture_path, "rb") as f:
                resp = client.post(
                    "/api/upload",
                    files={"file": (case["fixture"], f, "application/pdf")},
                )
            if resp.status_code != 202:
                return CaseResult(
                    name=name, passed=False, finding_count=0,
                    duration_ms=int((time.time() - t0) * 1000),
                    failures=[
                        f"POST /api/upload: expected 202, got {resp.status_code}: "
                        f"{resp.text[:200]}"
                    ],
                )
            tid = resp.json()["trace_id"]
            if "X-ManuSift-Trace-Id" not in resp.headers:
                failures.append("response missing X-ManuSift-Trace-Id header")

            # 2. Poll until done.
            deadline = time.time() + _POLL_TIMEOUT_S
            job: dict[str, Any] = {}
            while time.time() < deadline:
                jr = client.get(f"/api/jobs/{tid}")
                if jr.status_code != 200:
                    failures.append(f"GET /api/jobs/{tid}: {jr.status_code} {jr.text}")
                    break
                job = jr.json()
                if job["status"] in ("done", "failed"):
                    break
                time.sleep(_POLL_INTERVAL_S)
            else:
                failures.append(
                    f"job did not finish within {_POLL_TIMEOUT_S}s (last status: "
                    f"{job.get('status')})"
                )

            if job.get("status") == "failed":
                failures.append(f"job failed: {job.get('error')}")

            # 3. Findings JSON.
            fr = client.get(f"/api/jobs/{tid}/findings")
            if fr.status_code != 200:
                failures.append(
                    f"GET /api/jobs/{tid}/findings: {fr.status_code} {fr.text[:200]}"
                )
                findings: list[dict[str, Any]] = []
            else:
                findings = fr.json().get("findings", [])

            # 4. Report HTML.
            rr = client.get(f"/api/jobs/{tid}/report")
            if rr.status_code != 200:
                failures.append(
                    f"GET /api/jobs/{tid}/report: {rr.status_code} {rr.text[:200]}"
                )
            else:
                # Sanity: report must contain the trace id we just got.
                if tid not in rr.text:
                    failures.append("report HTML does not contain the trace_id")
                # If any findings, the report should reference them by
                # at least one of the finding titles. (If the report
                # is empty we don't enforce this — clean papers are
                # allowed to have an empty report.)
                if findings:
                    titles_in_report = sum(
                        1 for f in findings if f["title"] in rr.text
                    )
                    if titles_in_report == 0:
                        failures.append(
                            "report HTML mentions no finding titles — report "
                            "rendering may be broken"
                        )

        duration_ms = int((time.time() - t0) * 1000)

        # Wrap dict findings as objects so _check_expectation's filter
        # helper works (it accesses .detector / .severity / .raw / .title).
        from types import SimpleNamespace
        finding_objs = [
            SimpleNamespace(
                detector=f["detector"],
                severity=f["severity"],
                title=f["title"],
                raw=f.get("raw", {}),
            )
            for f in findings
        ]
        failures.extend(_check_expectation(case.get("expect", {}), finding_objs))

        return CaseResult(
            name=name,
            passed=not failures,
            finding_count=len(findings),
            duration_ms=duration_ms,
            failures=failures,
        )
    finally:
        if old_workspace is None:
            os.environ.pop("MANUSIFT_WORKSPACE_DIR", None)
        else:
            os.environ["MANUSIFT_WORKSPACE_DIR"] = old_workspace


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from evals.runner import configure_logging, _print_report

    configure_logging(level="WARNING")
    parser = argparse.ArgumentParser(prog="manusift-evals-e2e")
    parser.add_argument(
        "--case", default=None,
        help="Substring filter: only run cases whose name contains this",
    )
    parser.add_argument(
        "--keep-tmp", action="store_true",
        help="Print the tmp workspace path instead of deleting it",
    )
    args = parser.parse_args(argv)

    cases = _load_e2e_cases(args.case)
    if not cases:
        print(
            f"No e2e cases found in {E2E_CASES_DIR} (filter={args.case!r})",
            file=sys.stderr,
        )
        return 2

    results: list[CaseResult] = []
    for c in cases:
        import tempfile
        with tempfile.TemporaryDirectory(prefix="manusift-e2e-") as td:
            workspace = Path(td) / "jobs"
            if args.keep_tmp:
                print(f"[keep-tmp] workspace = {workspace}")
            results.append(_run_e2e_one(c, workspace))

    _print_report(results)
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
