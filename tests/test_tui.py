"""Tests for the TUI.

These use textual's headless ``run_test`` so they work in CI / on
machines without a real terminal. They do *not* open a browser; the
``open_report`` action falls through to a no-op when no row is
highlighted.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from rich.console import Console
from io import StringIO

from manusift.config import get_settings
from manusift.tui.app import (
    FilterState,
    JobsTable,
    ManuSiftApp,
    _passes_filter,
    _job_min_severity,
)
from manusift.tui.data import JobSummary, list_jobs, load_findings


# ---------- data layer ----------

def test_list_jobs_returns_done_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """list_jobs walks the workspace, reads job.json, and sorts by
    created_at descending."""
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    # Build two fake job dirs.
    from manusift.workspace import JobPaths
    import time
    for i, ts in enumerate([100.0, 200.0]):
        tid = f"job{i}"
        p = JobPaths.for_trace(tid, tmp_path / "jobs")
        p.ensure()
        p.job_json.write_text(
            json.dumps(
                {
                    "trace_id": tid,
                    "status": "done",
                    "source_filename": f"f{i}.pdf",
                    "created_at": ts,
                    "detectors_run": ["text_patterns"],
                    "finding_count": i,
                }
            ),
            encoding="utf-8",
        )
        time.sleep(0.01)

    jobs = list_jobs()
    assert [j.trace_id for j in jobs] == ["job1", "job0"]
    assert all(isinstance(j, JobSummary) for j in jobs)


def test_list_jobs_skips_dirs_without_job_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "garbage").mkdir()
    (tmp_path / "jobs" / "garbage" / "junk.txt").write_text("hi")
    assert list_jobs() == []


def test_load_findings_handles_missing_file(tmp_path: Path) -> None:
    job = JobSummary(
        trace_id="x",
        status="done",
        source_filename="x.pdf",
        created_at=0.0,
        finished_at=None,
        error=None,
        finding_count=0,
        duration_ms=0,
        detectors_run=[],
        llm_calls=0,
        report_path=tmp_path / "report.html",
        findings_path=tmp_path / "findings.json",  # doesn't exist
    )
    assert load_findings(job) == []


# ---------- JobSummary.matches ----------

def _mk_job(trace: str, **kw) -> JobSummary:
    return JobSummary(
        trace_id=trace,
        status=kw.get("status", "done"),
        source_filename=kw.get("source_filename", ""),
        created_at=kw.get("created_at", 0.0),
        finished_at=kw.get("finished_at"),
        error=kw.get("error"),
        finding_count=kw.get("finding_count", 0),
        duration_ms=kw.get("duration_ms", 0),
        detectors_run=kw.get("detectors_run", []),
        llm_calls=kw.get("llm_calls", 0),
        report_path=kw.get("report_path"),
        findings_path=kw.get("findings_path"),
    )


def test_job_matches_empty_query_passes() -> None:
    j = _mk_job("abc123", source_filename="chatbot.pdf")
    assert j.matches("")


def test_job_matches_trace_id_case_insensitive() -> None:
    j = _mk_job("abc123def", source_filename="")
    assert j.matches("ABC123")
    assert j.matches("def")
    assert not j.matches("xyz")


def test_job_matches_filename_and_status() -> None:
    j = _mk_job("x", source_filename="composite_image.pdf", status="done")
    assert j.matches("composite")
    assert j.matches("done")
    assert not j.matches("chatbot")


def test_job_matches_detector_name() -> None:
    j = _mk_job("x", detectors_run=["image_dup", "text_patterns"])
    assert j.matches("image")
    assert j.matches("TEXT")


# ---------- FilterState ----------

def test_filter_state_default() -> None:
    f = FilterState()
    assert f.query == ""
    assert f.severity == "all"
    assert f.description() == "no filter"


def test_filter_state_cycles_severity() -> None:
    f = FilterState()
    assert f.severity == "all"
    f.cycle_severity()
    assert f.severity == "high"
    f.cycle_severity()
    assert f.severity == "medium"
    f.cycle_severity()
    f.cycle_severity()
    f.cycle_severity()  # wraps back to all
    assert f.severity == "all"


def test_filter_state_description_reflects_active_filters() -> None:
    f = FilterState()
    f.query = "chatbot"
    f.severity = "high"
    assert "chatbot" in f.description()
    assert "high" in f.description()


# ---------- _passes_filter (jobs level) ----------

def _mk_job_with_findings(tmp_path: Path, trace: str, severities: list[str]) -> JobSummary:
    """Build a job whose findings.json lists findings with the given severities."""
    from manusift.workspace import JobPaths
    p = JobPaths.for_trace(trace, tmp_path / "jobs")
    p.ensure()
    p.job_json.write_text(
        json.dumps(
            {
                "trace_id": trace,
                "status": "done",
                "source_filename": f"{trace}.pdf",
                "created_at": 100.0,
                "detectors_run": ["text_patterns"],
                "finding_count": len(severities),
            }
        ),
        encoding="utf-8",
    )
    findings = [
        {
            "finding_id": f"{trace}-f{i}",
            "trace_id": trace,
            "detector": "text_patterns",
            "severity": sev,
            "title": f"f{i}",
            "evidence": "x",
            "location": "p1",
            "raw": {},
        }
        for i, sev in enumerate(severities)
    ]
    p.findings_json.write_text(
        json.dumps(
            {
                "trace_id": trace,
                "detectors_run": ["text_patterns"],
                "llm_calls": 0,
                "findings": findings,
            }
        ),
        encoding="utf-8",
    )
    return _mk_job(
        trace,
        source_filename=f"{trace}.pdf",
        report_path=p.report_html,
        findings_path=p.findings_json,
        finding_count=len(severities),
        detectors_run=["text_patterns"],
    )


def test_passes_filter_empty_passes_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    j = _mk_job_with_findings(tmp_path, "a", ["high"])
    assert _passes_filter(j, FilterState())


def test_passes_filter_query_matches_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    j = _mk_job_with_findings(tmp_path, "abc", ["high"])
    f = FilterState()
    f.query = "abc"
    assert _passes_filter(j, f)
    f.query = "notthere"
    assert not _passes_filter(j, f)


def test_passes_filter_severity_filters_by_min(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Severity filter 'high' should only pass jobs whose minimum
    finding severity is high. A job with only 'medium' findings
    should be filtered out."""
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    j_high = _mk_job_with_findings(tmp_path, "h", ["high", "low"])
    j_med = _mk_job_with_findings(tmp_path, "m", ["medium"])
    f = FilterState()
    f.severity = "high"
    assert _passes_filter(j_high, f)
    assert not _passes_filter(j_med, f)

    f.severity = "medium"
    assert _passes_filter(j_high, f)
    assert _passes_filter(j_med, f)


def test_passes_filter_query_and_severity_combine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    j = _mk_job_with_findings(tmp_path, "chatbot_text", ["high"])
    f = FilterState()
    f.query = "other"
    f.severity = "high"
    assert not _passes_filter(j, f)
    f.query = "chatbot"
    assert _passes_filter(j, f)


def test_job_min_severity_handles_empty_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()
    j = _mk_job_with_findings(tmp_path, "empty", [])
    assert _job_min_severity(j) is None


# ---------- TUI app headless test (existing) ----------

@pytest.mark.asyncio
async def test_app_loads_jobs_and_selects_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Boot the app with a fake workspace, confirm the jobs table
    populates, the detail pane reflects the selection, and the
    findings pane shows that job's findings."""
    import os
    from manusift.workspace import JobPaths

    workspace = tmp_path / "jobs"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))

    # One job with two findings of different severities.
    p = JobPaths.for_trace("aaa", workspace)
    p.ensure()
    p.job_json.write_text(
        json.dumps(
            {
                "trace_id": "aaa",
                "status": "done",
                "source_filename": "demo.pdf",
                "created_at": 100.0,
                "detectors_run": ["text_patterns", "image_dup"],
                "finding_count": 2,
            }
        ),
        encoding="utf-8",
    )
    p.findings_json.write_text(
        json.dumps(
            {
                "trace_id": "aaa",
                "detectors_run": ["text_patterns", "image_dup"],
                "llm_calls": 0,
                "findings": [
                    {
                        "finding_id": "f1",
                        "trace_id": "aaa",
                        "detector": "text_patterns",
                        "severity": "high",
                        "title": "Bot said 'as an AI'",
                        "evidence": "Found phrase.",
                        "location": "p1",
                        "raw": {"check": "chatbot_disclaimer"},
                    },
                    {
                        "finding_id": "f2",
                        "trace_id": "aaa",
                        "detector": "image_dup",
                        "severity": "medium",
                        "title": "Two images match",
                        "evidence": "Hamming=2",
                        "location": "p2",
                        "raw": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    app = ManuSiftApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        jobs_tbl = app.query_one("#jobs")
        assert jobs_tbl.row_count == 1

        # Move the cursor to the only row.
        jobs_tbl.focus()
        await pilot.press("down")
        await pilot.pause()

        assert app.selected_job is not None
        assert app.selected_job.trace_id == "aaa"

        findings_tbl = app.query_one("#findings")
        # Default severity='all' so both findings should be visible.
        assert findings_tbl.row_count == 2

        # The detail pane should mention 'aaa' and 'demo.pdf'.
        sio = StringIO()
        Console(file=sio, width=120, force_terminal=True).print(
            app.query_one("#detail").render()
        )
        detail_text = sio.getvalue()
        assert "aaa" in detail_text
        assert "demo.pdf" in detail_text


@pytest.mark.asyncio
async def test_app_handles_empty_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Boot with no jobs at all — app should not crash, tables empty."""
    import os
    workspace = tmp_path / "jobs"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))

    app = ManuSiftApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#jobs").row_count == 0
        assert app.query_one("#findings").row_count == 0
        assert app.selected_job is None


# ---------- new tests: filter behavior end-to-end ----------

@pytest.mark.asyncio
async def test_app_query_filter_hides_mismatched_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from manusift.workspace import JobPaths

    workspace = tmp_path / "jobs"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))

    # Three jobs: chatbot, duplicate, composite.
    for name in ("chatbot_x", "duplicate_x", "composite_x"):
        p = JobPaths.for_trace(name, workspace)
        p.ensure()
        p.job_json.write_text(
            json.dumps({
                "trace_id": name,
                "status": "done",
                "source_filename": f"{name}.pdf",
                "created_at": 100.0,
                "detectors_run": ["text_patterns"],
                "finding_count": 1,
            }),
            encoding="utf-8",
        )
        p.findings_json.write_text(
            json.dumps({
                "trace_id": name,
                "detectors_run": ["text_patterns"],
                "llm_calls": 0,
                "findings": [{
                    "finding_id": f"{name}-f1",
                    "trace_id": name,
                    "detector": "text_patterns",
                    "severity": "high",
                    "title": "x",
                    "evidence": "x",
                    "location": "p1",
                    "raw": {},
                }],
            }),
            encoding="utf-8",
        )

    app = ManuSiftApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Baseline: 3 jobs.
        assert app.query_one("#jobs").row_count == 3

        # Open the filter input and type one char at a time so
        # textual's pilot processes each key event.
        await pilot.press("/")
        await pilot.pause()
        for ch in "chatbot":
            await pilot.press(ch)
            await pilot.pause()

        assert app.query_one("#jobs").row_count == 1
        # Static's current text lives on its .render() method in
        # textual 8 — render to a string and assert the filter
        # description includes the query we typed.
        from rich.console import Console as _Console
        from io import StringIO as _StringIO
        _sio = _StringIO()
        _Console(file=_sio, width=80, force_terminal=True).print(
            app.query_one("#filter-status").render()
        )
        assert "chatbot" in _sio.getvalue()


@pytest.mark.asyncio
async def test_app_severity_filter_hides_low_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from manusift.workspace import JobPaths

    workspace = tmp_path / "jobs"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))

    # One job, two findings: one high, one low.
    p = JobPaths.for_trace("mix", workspace)
    p.ensure()
    p.job_json.write_text(
        json.dumps({
            "trace_id": "mix",
            "status": "done",
            "source_filename": "mix.pdf",
            "created_at": 100.0,
            "detectors_run": ["text_patterns"],
            "finding_count": 2,
        }),
        encoding="utf-8",
    )
    p.findings_json.write_text(
        json.dumps({
            "trace_id": "mix",
            "detectors_run": ["text_patterns"],
            "llm_calls": 0,
            "findings": [
                {"finding_id": "fh", "trace_id": "mix", "detector": "t",
                 "severity": "high", "title": "H", "evidence": "",
                 "location": "", "raw": {}},
                {"finding_id": "fl", "trace_id": "mix", "detector": "t",
                 "severity": "low", "title": "L", "evidence": "",
                 "location": "", "raw": {}},
            ],
        }),
        encoding="utf-8",
    )

    app = ManuSiftApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one("#jobs", JobsTable).focus()
        await pilot.pause()
        await pilot.press("down")  # select the job
        await pilot.pause()

        # With severity='all' both findings show.
        assert app.query_one("#findings").row_count == 2

        # Cycle severity: all → high. Low finding drops.
        await pilot.press("s")
        await pilot.pause()
        assert app.filter.severity == "high"
        assert app.query_one("#findings").row_count == 1


@pytest.mark.asyncio
async def test_app_clear_filter_restores_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    from manusift.workspace import JobPaths

    workspace = tmp_path / "jobs"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))

    for name in ("alpha", "beta"):
        p = JobPaths.for_trace(name, workspace)
        p.ensure()
        p.job_json.write_text(
            json.dumps({
                "trace_id": name, "status": "done",
                "source_filename": f"{name}.pdf",
                "created_at": 100.0,
                "detectors_run": [], "finding_count": 0,
            }),
            encoding="utf-8",
        )

    app = ManuSiftApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.query_one("#jobs").row_count == 2

        # Apply a query that hides everything.
        await pilot.press("/")
        await pilot.pause()
        for ch in "zzzz":
            await pilot.press(ch)
            await pilot.pause()
        assert app.query_one("#jobs").row_count == 0

        # Return focus to the jobs table so 'c' fires action_clear_filter
        # instead of being typed into the filter input.
        app.query_one("#jobs", JobsTable).focus()
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert app.query_one("#jobs").row_count == 2
        assert app.filter.query == ""
        assert app.filter.severity == "all"

