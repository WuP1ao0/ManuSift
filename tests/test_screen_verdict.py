"""Unit tests for the P3 MCP product surface (screen verdict + async jobs).

Covers ``manusift/mcp/screen.py`` (verdict rules, score, artifact
reuse, the ScreenJobManager state machine / persistence / restart
recovery) and the four tools in ``manusift/tools/screen_tools.py``.
The pipeline itself is faked — no real PDF parsing, no network.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from manusift.mcp import screen
from manusift.mcp.screen import ScreenJobManager, compute_verdict

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _issue(issue_id: str, severity: str, member_count: int = 1) -> dict:
    return {
        "issue_id": issue_id,
        "kind": "image",
        "severity": severity,
        "title": f"title-{issue_id}",
        "detectors": ["image_dup"],
        "finding_ids": [f"f-{issue_id}"],
        "member_count": member_count,
        "group_key": f"image|{issue_id}",
    }


def _write_issues_json(ws: Path, tid: str, issues: list[dict]) -> None:
    root = ws / tid / "output"
    root.mkdir(parents=True, exist_ok=True)
    (root / "issues.json").write_text(
        json.dumps(
            {
                "trace_id": tid,
                "schema": "manusift.issues.v1",
                "issue_count": len(issues),
                "finding_count": sum(i["member_count"] for i in issues),
                "issues": issues,
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# verdict rules + score
# ---------------------------------------------------------------------------


def test_verdict_clean_when_no_high_and_few_medium() -> None:
    out = compute_verdict(
        [_issue("a", "medium"), _issue("b", "low"), _issue("c", "info")],
        trace_id="t1",
        report_path="/r.html",
    )
    assert out["verdict"] == "clean"
    assert out["counts_by_severity"] == {
        "high": 0,
        "medium": 1,
        "low": 1,
        "info": 1,
    }
    assert out["trace_id"] == "t1"
    assert out["report_path"] == "/r.html"
    assert out["schema"] == screen.VERDICT_SCHEMA


def test_verdict_suspect_on_medium_cluster() -> None:
    issues = [_issue(f"m{i}", "medium") for i in range(3)]
    out = compute_verdict(
        issues, trace_id="t2", report_path="/r.html"
    )
    assert out["verdict"] == "suspect"
    # 3 * 0.4 / 3.0 = 0.4
    assert out["score"] == pytest.approx(0.4)


def test_verdict_flagged_on_single_high() -> None:
    out = compute_verdict(
        [_issue("h", "high")], trace_id="t3", report_path="/r.html"
    )
    assert out["verdict"] == "flagged"
    # 1.0 / 3.0 -> 0.333
    assert out["score"] == pytest.approx(0.333, abs=1e-3)


def test_score_saturates_at_one() -> None:
    issues = [_issue(f"h{i}", "high") for i in range(4)]
    out = compute_verdict(
        issues, trace_id="t4", report_path="/r.html"
    )
    assert out["score"] == 1.0


def test_score_is_monotonic_in_severity() -> None:
    low = compute_verdict(
        [_issue("a", "low")], trace_id="t", report_path=""
    )["score"]
    med = compute_verdict(
        [_issue("a", "medium")], trace_id="t", report_path=""
    )["score"]
    high = compute_verdict(
        [_issue("a", "high")], trace_id="t", report_path=""
    )["score"]
    assert low < med < high


def test_top_issues_sorted_and_capped() -> None:
    issues = [
        _issue("low-big", "low", member_count=9),
        _issue("med-small", "medium", member_count=1),
        _issue("med-big", "medium", member_count=5),
        _issue("info", "info"),
        _issue("high", "high"),
        _issue("low-small", "low", member_count=1),
    ]
    out = compute_verdict(
        issues, trace_id="t5", report_path="", top_n=3
    )
    top = out["top_issues"]
    assert [i["issue_id"] for i in top] == ["high", "med-big", "med-small"]
    # projection keeps exactly the documented fields
    assert set(top[0]) == {
        "issue_id",
        "severity",
        "title",
        "detectors",
        "member_count",
    }


def test_suspect_threshold_is_configurable() -> None:
    issues = [_issue(f"m{i}", "medium") for i in range(2)]
    out = compute_verdict(
        issues,
        trace_id="t6",
        report_path="",
        suspect_medium_threshold=2,
    )
    assert out["verdict"] == "suspect"


# ---------------------------------------------------------------------------
# verdict_for_trace (artifact reuse)
# ---------------------------------------------------------------------------


def test_verdict_for_trace_from_issues_json(tmp_path: Path) -> None:
    _write_issues_json(tmp_path, "tid-1", [_issue("h", "high")])
    out = screen.verdict_for_trace("tid-1", workspace_dir=tmp_path)
    assert out["verdict"] == "flagged"
    # cached verdict file is written for the next call
    cached = tmp_path / "tid-1" / "output" / "screen_verdict.json"
    assert cached.is_file()
    assert json.loads(cached.read_text(encoding="utf-8"))["verdict"] == "flagged"


def test_verdict_for_trace_from_findings_json(tmp_path: Path) -> None:
    root = tmp_path / "tid-2" / "output"
    root.mkdir(parents=True)
    findings = [
        {
            "finding_id": f"f{i}",
            "trace_id": "tid-2",
            "detector": "metadata",
            "severity": "medium",
            "title": f"m{i}",
            "evidence": "",
            "location": "",
        }
        for i in range(3)
    ]
    (root / "findings.json").write_text(
        json.dumps({"trace_id": "tid-2", "findings": findings}),
        encoding="utf-8",
    )
    out = screen.verdict_for_trace("tid-2", workspace_dir=tmp_path)
    # three medium findings from one detector family aggregate into
    # one medium issue -> below the suspect threshold -> clean
    assert out["verdict"] == "clean"
    assert out["issue_count"] == 1


def test_verdict_for_trace_missing_artifacts(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        screen.verdict_for_trace("no-such-trace", workspace_dir=tmp_path)


# ---------------------------------------------------------------------------
# ScreenJobManager
# ---------------------------------------------------------------------------


def _mk_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4 fake\n")
    return path


def _fake_run_screen_returning(verdict: dict):
    """Build a run_screen replacement that ticks the hook 3 times."""

    def _fake(pdf_path, *, trace_id, use_llm, workspace_dir=None, on_step_complete=None):
        assert trace_id
        for name in ("metadata", "image_dup", "text_patterns"):
            if on_step_complete is not None:
                on_step_complete(SimpleNamespace(detector=name), None)
            time.sleep(0.02)
        payload = dict(verdict, trace_id=trace_id)
        ws = workspace_dir or screen._workspace_dir()
        screen._atomic_write_json(
            screen._verdict_path(trace_id, ws), payload
        )
        return payload

    return _fake


@pytest.fixture()
def job_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated workspace + 3-step fake pipeline."""
    ws = tmp_path / "jobs"
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(ws))
    verdict = {
        "schema": screen.VERDICT_SCHEMA,
        "trace_id": "",
        "verdict": "clean",
        "score": 0.0,
        "top_issues": [],
        "counts_by_severity": {"high": 0, "medium": 0, "low": 0, "info": 0},
        "issue_count": 0,
        "report_path": "/r.html",
    }
    monkeypatch.setattr(
        screen, "run_screen", _fake_run_screen_returning(verdict)
    )
    monkeypatch.setattr(
        "manusift.pipeline._pipeline_detector_classes",
        lambda: [object, object, object],
    )
    return ws


def test_submit_status_result_happy_path(job_env: Path, tmp_path: Path) -> None:
    mgr = ScreenJobManager()
    pdf = _mk_pdf(tmp_path / "paper.pdf")
    sub = mgr.submit(str(pdf))
    assert sub["status"] == "queued"
    job_id = sub["job_id"]

    # job_id == trace_id, and the state file is on disk from the start
    state_file = job_env / "_screen_jobs" / f"{job_id}.json"
    assert state_file.is_file()

    progress_series: list[int] = []
    deadline = time.time() + 10
    final: dict = {}
    while time.time() < deadline:
        st = mgr.status(job_id)
        progress_series.append(int(st["progress_pct"]))
        if st["status"] in ("done", "failed"):
            final = st
            break
        time.sleep(0.02)
    assert final["status"] == "done", final
    # monotonic non-decreasing progress while polling
    assert progress_series == sorted(progress_series)
    assert final["progress_pct"] == 100
    assert final["steps_done"] == 3
    assert final["steps_total"] == 3
    assert final["stage"] == "done"
    assert final["finished_at"]

    res = mgr.result(job_id)
    assert res["verdict"] == "clean"
    assert res["trace_id"] == job_id
    assert res["schema"] == screen.VERDICT_SCHEMA


def test_result_while_running_returns_status(job_env: Path, tmp_path: Path) -> None:
    mgr = ScreenJobManager()
    pdf = _mk_pdf(tmp_path / "paper.pdf")
    job_id = mgr.submit(str(pdf))["job_id"]
    # Immediately after submit the job is queued/running; result()
    # must return the status payload, not a verdict.
    out = mgr.result(job_id)
    if out.get("status") != "done":  # race: tiny fake may finish fast
        assert "progress_pct" in out
        assert "verdict" not in out
    deadline = time.time() + 10
    while time.time() < deadline:
        if mgr.status(job_id)["status"] == "done":
            break
        time.sleep(0.02)
    assert mgr.result(job_id)["verdict"] == "clean"


def test_submit_rejects_bad_input(job_env: Path, tmp_path: Path) -> None:
    mgr = ScreenJobManager()
    assert mgr.submit(str(tmp_path / "missing.pdf"))["error"] == "pdf_not_found"
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    assert mgr.submit(str(txt))["error"] == "not_a_pdf"


def test_status_validation_and_unknown_job(job_env: Path) -> None:
    mgr = ScreenJobManager()
    assert mgr.status("../etc")["error"] == "invalid_job_id"
    assert mgr.status("abcd1234abcd")["error"] == "unknown_job"


def test_failed_job_records_error(job_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(pdf_path, *, trace_id, use_llm, workspace_dir=None, on_step_complete=None):
        raise RuntimeError("parse exploded")

    monkeypatch.setattr(screen, "run_screen", _boom)
    mgr = ScreenJobManager()
    pdf = _mk_pdf(tmp_path / "paper.pdf")
    job_id = mgr.submit(str(pdf))["job_id"]
    deadline = time.time() + 10
    st: dict = {}
    while time.time() < deadline:
        st = mgr.status(job_id)
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert st["status"] == "failed"
    assert "parse exploded" in st["error"]
    # result() on a failed job returns the status payload, not a verdict
    assert mgr.result(job_id)["status"] == "failed"


def test_restart_recovery(job_env: Path, tmp_path: Path) -> None:
    """A fresh manager (new process) sees: done jobs stay done and
    return their result; queued/running leftovers turn into an
    interrupted failure instead of polling forever."""
    mgr1 = ScreenJobManager()
    pdf = _mk_pdf(tmp_path / "paper.pdf")
    job_id = mgr1.submit(str(pdf))["job_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        if mgr1.status(job_id)["status"] == "done":
            break
        time.sleep(0.02)

    # Simulate a crashed job: hand-write a stale "running" state.
    stale_id = "stalejob01"
    stale = {
        "schema": screen.JOB_SCHEMA,
        "job_id": stale_id,
        "trace_id": stale_id,
        "status": "running",
        "progress_pct": 42,
        "stage": "image_dup",
        "steps_done": 3,
        "steps_total": 7,
        "created_at": time.time(),
        "started_at": time.time(),
        "finished_at": None,
        "error": None,
        "result_path": None,
    }
    screen._atomic_write_json(
        job_env / "_screen_jobs" / f"{stale_id}.json", stale
    )

    # "Restart": a brand-new manager with an empty live set.
    mgr2 = ScreenJobManager()
    done = mgr2.status(job_id)
    assert done["status"] == "done"
    assert mgr2.result(job_id)["verdict"] == "clean"

    recovered = mgr2.status(stale_id)
    assert recovered["status"] == "failed"
    assert "interrupted" in recovered["error"]
    # The interrupted status is persisted, not just reported once.
    on_disk = json.loads(
        (job_env / "_screen_jobs" / f"{stale_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["status"] == "failed"


# ---------------------------------------------------------------------------
# tools layer
# ---------------------------------------------------------------------------


def test_screen_verdict_tool_reuses_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    _write_issues_json(tmp_path, "tid-tool", [_issue("h", "high")])
    from manusift.tools.screen_tools import ScreenVerdictTool
    from manusift.tools.tool import ToolContext

    out = json.loads(ScreenVerdictTool().execute({}, ToolContext(trace_id="tid-tool")))
    assert out["verdict"] == "flagged"


def test_screen_verdict_tool_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    from manusift.tools.screen_tools import ScreenVerdictTool
    from manusift.tools.tool import ToolContext

    tool = ScreenVerdictTool()
    ctx = ToolContext(trace_id="t-x")
    assert json.loads(tool.execute({"path": str(tmp_path / "no.pdf")}, ctx))["error"] == "pdf_not_found"
    out = json.loads(tool.execute({}, ctx))
    assert out["error"] == "no_artifacts"


def test_job_tools_roundtrip(job_env: Path, tmp_path: Path) -> None:
    from manusift.tools.screen_tools import (
        GetJobResultTool,
        GetJobStatusTool,
        SubmitScreenTool,
    )
    from manusift.tools.tool import ToolContext

    ctx = ToolContext(trace_id="t-tools")
    pdf = _mk_pdf(tmp_path / "paper.pdf")
    sub = json.loads(SubmitScreenTool().execute({"path": str(pdf)}, ctx))
    job_id = sub["job_id"]

    deadline = time.time() + 10
    st: dict = {}
    while time.time() < deadline:
        st = json.loads(GetJobStatusTool().execute({"job_id": job_id}, ctx))
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert st["status"] == "done"
    res = json.loads(GetJobResultTool().execute({"job_id": job_id}, ctx))
    assert res["verdict"] == "clean"

    # missing-argument error paths
    assert json.loads(SubmitScreenTool().execute({}, ctx))["error"]
    assert json.loads(GetJobStatusTool().execute({}, ctx))["error"]
    assert json.loads(GetJobResultTool().execute({}, ctx))["error"]


def test_screen_tools_are_registered() -> None:
    from manusift.tools.registry import get_tool

    for name in (
        "screen_verdict",
        "submit_screen",
        "get_job_status",
        "get_job_result",
    ):
        assert get_tool(name) is not None, f"{name} not registered"


def test_screen_tools_on_default_mcp_surface() -> None:
    from manusift.mcp.surface import MCP_DEFAULT_TOOLS

    assert MCP_DEFAULT_TOOLS[:4] == [
        "screen_verdict",
        "submit_screen",
        "get_job_status",
        "get_job_result",
    ]
    assert len(MCP_DEFAULT_TOOLS) == 40
