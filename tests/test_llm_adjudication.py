"""P1.2 LLM adjudication tests.

The adjudicator sits between aggregation and enrichment: high issues are
judged ``actionable | explainable | uncertain``; only ``explainable``
demotes member findings high→medium (never drops). All LLM access goes
through stub clients — no network.
"""
from __future__ import annotations

import pytest

from manusift.contracts import Finding
from manusift.llm.adjudication import (
    ADJUDICATION_VERSION,
    adjudicate_issues,
)
from manusift.report.finding_aggregation import aggregate_findings

# ---------- helpers ----------


def _mk_finding(
    fid: str,
    *,
    detector: str = "det_a",
    severity: str = "high",
    title: str = "suspicious pattern",
    location: str = "page 1",
    evidence: str = "evidence",
    raw: dict | None = None,
) -> Finding:
    return Finding(
        finding_id=fid,
        trace_id="t",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence=evidence,
        location=location,
        raw=raw or {},
    )


class _StubClient:
    """Returns a canned raw-prompt response (or raises) and counts calls."""

    name = "test-adjudicate"

    def __init__(self, payload: str | None, *, fail: bool = False) -> None:
        self._payload = payload
        self._fail = fail
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def _call_raw_prompt(self, prompt: str, *, max_tokens: int = 800) -> str:
        self.calls += 1
        if self._fail:
            raise RuntimeError("boom")
        assert self._payload is not None
        return self._payload


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_LLM_ADJUDICATE", "1")


# ---------- verdict handling ----------


def test_explainable_demotes_members(enabled: None) -> None:
    findings = [_mk_finding("f1"), _mk_finding("f2")]
    issues = aggregate_findings(findings)
    assert len(issues) == 1 and issues[0].severity == "high"

    client = _StubClient(
        '{"verdict": "explainable", "reason": "intentional derived column"}'
    )
    out_findings, out_issues = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 1
    assert len(out_findings) == 2  # nothing dropped
    for f in out_findings:
        assert f.severity == "medium"
        adj = f.raw["adjudication"]
        assert adj["verdict"] == "explainable"
        assert adj["reason"] == "intentional derived column"
        assert adj["issue_id"] == issues[0].issue_id
        assert adj["prior_severity"] == "high"
        assert adj["version"] == ADJUDICATION_VERSION
    # inputs untouched
    assert all(f.severity == "high" for f in findings)
    # issue view rebuilt from adjudicated findings
    assert [i.to_dict() for i in out_issues] == [
        i.to_dict() for i in aggregate_findings(out_findings)
    ]
    assert out_issues[0].severity == "medium"


@pytest.mark.parametrize("verdict", ["actionable", "uncertain"])
def test_actionable_and_uncertain_keep_severity(
    enabled: None, verdict: str
) -> None:
    findings = [_mk_finding("f1")]
    issues = aggregate_findings(findings)
    client = _StubClient(f'{{"verdict": "{verdict}", "reason": "r"}}')

    out_findings, out_issues = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 1
    assert out_findings is findings  # no demotion → inputs returned as-is
    assert out_issues is issues
    assert out_findings[0].severity == "high"
    assert "adjudication" not in out_findings[0].raw


def test_garbage_response_is_uncertain(enabled: None) -> None:
    findings = [_mk_finding("f1")]
    issues = aggregate_findings(findings)
    client = _StubClient("this is not json at all")

    out_findings, _ = adjudicate_issues(findings, issues, client=client)

    assert out_findings is findings
    assert findings[0].severity == "high"


def test_invalid_verdict_value_is_uncertain(enabled: None) -> None:
    findings = [_mk_finding("f1")]
    issues = aggregate_findings(findings)
    client = _StubClient('{"verdict": "bogus", "reason": "r"}')

    out_findings, _ = adjudicate_issues(findings, issues, client=client)

    assert out_findings is findings
    assert findings[0].severity == "high"


def test_llm_exception_is_uncertain(enabled: None) -> None:
    findings = [_mk_finding("f1")]
    issues = aggregate_findings(findings)
    client = _StubClient(None, fail=True)

    out_findings, _ = adjudicate_issues(findings, issues, client=client)

    assert out_findings is findings
    assert findings[0].severity == "high"


# ---------- cost guardrails ----------


def test_max_issues_truncation(
    enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MANUSIFT_LLM_ADJUDICATE_MAX_ISSUES", "1")
    # distinct detectors → distinct single-member issues
    findings = [_mk_finding("f1", detector="det_a"), _mk_finding("f2", detector="det_b")]
    issues = aggregate_findings(findings)
    assert len(issues) == 2

    client = _StubClient('{"verdict": "explainable", "reason": "r"}')
    out_findings, _ = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 1  # only one issue adjudicated
    demoted = [f for f in out_findings if f.severity == "medium"]
    kept = [f for f in out_findings if f.severity == "high"]
    assert len(demoted) == 1 and len(kept) == 1


def test_same_fingerprint_asked_once(enabled: None) -> None:
    # Two table issues (different identities) whose representative findings
    # share one enrichment fingerprint → one call, verdict broadcast.
    findings = [
        _mk_finding(
            "f1",
            detector="table_relationships",
            title="fixed offset between col a and col b (n=12)",
            location="table 10, column a",
            raw={"check": "fixed_offset", "fig_name": "table 10"},
        ),
        _mk_finding(
            "f2",
            detector="table_relationships",
            title="fixed offset between col a and col b (n=99)",
            location="table 25, column a",
            raw={"check": "fixed_offset", "fig_name": "table 25"},
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2

    client = _StubClient('{"verdict": "explainable", "reason": "derived"}')
    out_findings, out_issues = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 1  # broadcast: one call for both issues
    assert all(f.severity == "medium" for f in out_findings)
    assert all(i.severity == "medium" for i in out_issues)


def test_non_high_issue_not_sent(enabled: None) -> None:
    findings = [_mk_finding("f1", severity="medium")]
    issues = aggregate_findings(findings)
    assert issues[0].severity == "medium"

    client = _StubClient('{"verdict": "explainable", "reason": "r"}')
    out_findings, out_issues = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 0
    assert out_findings is findings
    assert out_issues is issues


def test_off_by_default_zero_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MANUSIFT_LLM_ADJUDICATE", raising=False)
    findings = [_mk_finding("f1")]
    issues = aggregate_findings(findings)

    client = _StubClient('{"verdict": "explainable", "reason": "r"}')
    out_findings, out_issues = adjudicate_issues(findings, issues, client=client)

    assert client.calls == 0
    assert out_findings is findings
    assert out_issues is issues
    assert findings[0].severity == "high"
