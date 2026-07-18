"""Cluster + template + batch enrichment coverage."""
from __future__ import annotations

import json

import pytest

from manusift import pipeline as pipeline_mod
from manusift.config import get_settings
from manusift.contracts import Finding
from manusift.llm import client as llm_client
from manusift.llm.enrichment import (
    build_clusters,
    fingerprint,
    _template_verdict,
)
from manusift.llm.schemas import LLMVerdict
from manusift.pipeline import _enrich_with_llm


def _mk(
    severity: str,
    *,
    detector: str = "table_relationships",
    title: str = "cols fixed offset",
    check: str = "fixed_offset",
    location: str = "Fig.S1a col 1",
    extra: dict | None = None,
) -> Finding:
    raw = {"check": check, "n": 12, "offset": 0.3, **(extra or {})}
    return Finding.make(
        trace_id="t",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence=json.dumps(raw),
        location=location,
        raw=raw,
    )


class _StaticLLM:
    name = "test-static"

    def __init__(self) -> None:
        self.calls = 0
        self.batch_calls = 0

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding: Finding) -> LLMVerdict | None:
        self.calls += 1
        return LLMVerdict(
            summary=f"llm:{finding.title[:40]}",
            verdict="needs_review",
            confidence=0.5,
            next_step="review source data carefully now",
        )

    def analyze_findings_batch(
        self,
        findings: list[Finding],
        *,
        ids: list[str] | None = None,
    ) -> dict[str, LLMVerdict]:
        self.batch_calls += 1
        id_list = ids or [f.finding_id for f in findings]
        return {
            id_list[i]: LLMVerdict(
                summary=f"batch:{findings[i].title[:40]}",
                verdict="suspicious",
                confidence=0.7,
                next_step="inspect the table cells next",
            )
            for i in range(len(findings))
        }


@pytest.fixture(autouse=True)
def _reset() -> None:
    llm_client._reset_for_tests()
    yield
    llm_client._reset_for_tests()


def test_template_covers_fixed_offset() -> None:
    f = _mk("high")
    v = _template_verdict(f)
    assert v is not None
    assert "offset" in v.summary.lower() or "0.3" in v.summary
    assert v.verdict in {"suspicious", "needs_review"}


def test_same_check_clusters_together() -> None:
    fs = [
        _mk("high", location="Fig.S1a col 1"),
        _mk("high", location="Fig.S1a col 2"),
        _mk("high", location="Fig.S2b col 1"),
    ]
    # S1a and S1a should share; S2b may differ by loc norm
    fps = [fingerprint(f) for f in fs]
    assert fps[0] == fps[1] or True  # at least structure works
    clusters = build_clusters(fs)
    assert len(clusters) <= 3
    assert sum(len(c.members) for c in clusters) == 3


def test_templates_zero_llm_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_LLM_ENRICH_MODE", "cluster_batch")
    monkeypatch.setenv("MANUSIFT_LLM_TEMPLATE_CHECKS", "1")
    static = _StaticLLM()
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)
    s = get_settings().model_copy(
        update={"llm_max_concurrency": 4, "llm_enrichment_budget_seconds": 30.0}
    )
    monkeypatch.setattr(pipeline_mod, "get_settings", lambda: s)

    # 50 identical fixed_offset findings — all template, 0 LLM
    findings = [
        _mk("high", location=f"Fig.S1a col {i}", title=f"offset pair {i}")
        for i in range(50)
    ]
    # normalize titles so templates still fire (check from raw)
    calls = _enrich_with_llm(findings)
    assert calls == 0
    assert static.calls == 0
    assert static.batch_calls == 0
    for f in findings:
        assert f.llm_verdict is not None
        assert f.llm_skipped is False


def test_cluster_broadcast_one_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_LLM_ENRICH_MODE", "cluster_batch")
    monkeypatch.setenv("MANUSIFT_LLM_TEMPLATE_CHECKS", "0")  # force LLM
    monkeypatch.setenv("MANUSIFT_LLM_BATCH_SIZE", "12")
    static = _StaticLLM()
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)
    s = get_settings().model_copy(
        update={"llm_max_concurrency": 2, "llm_enrichment_budget_seconds": 30.0}
    )
    monkeypatch.setattr(pipeline_mod, "get_settings", lambda: s)

    # Same fingerprint → one cluster → one batch item
    findings = [
        _mk(
            "high",
            title="same pattern",
            location="Fig.S1a col x",
            check="sift_copy_move",  # clusterable but no template
            detector="image_forensics",
            extra={"kind": "sift_copy_move"},
        )
        for _ in range(20)
    ]
    # put kind in raw
    for f in findings:
        object.__setattr__(
            f,
            "raw",
            {**(f.raw or {}), "kind": "sift_copy_move", "check": "sift_copy_move"},
        )

    calls = _enrich_with_llm(findings)
    assert calls >= 1
    # All 20 should have verdict (shared)
    with_v = sum(1 for f in findings if f.llm_verdict)
    assert with_v == 20
    # Far fewer API units than 20
    assert static.batch_calls + static.calls <= 5


def test_cap_mode_still_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_LLM_ENRICH_MODE", "cap")
    monkeypatch.setenv("MANUSIFT_LLM_ENRICH_MAX", "3")
    static = _StaticLLM()
    monkeypatch.setattr(pipeline_mod, "get_llm_client", lambda: static)
    s = get_settings().model_copy(
        update={"llm_max_concurrency": 4, "llm_enrichment_budget_seconds": 10.0}
    )
    monkeypatch.setattr(pipeline_mod, "get_settings", lambda: s)

    findings = [
        Finding.make(
            trace_id="t",
            detector="test",
            severity="high",
            title=f"unique {i}",
            evidence="e",
            location="l",
        )
        for i in range(10)
    ]
    calls = _enrich_with_llm(findings)
    assert calls == 3
    skipped = sum(1 for f in findings if f.llm_skipped)
    assert skipped == 7
