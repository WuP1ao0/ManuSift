"""Standalone LLM report artifacts."""
from __future__ import annotations

from pathlib import Path

from manusift.contracts import Finding
from manusift.report.llm_report import write_llm_reports


def test_write_llm_reports(tmp_path: Path) -> None:
    findings = [
        Finding.make(
            trace_id="t1",
            detector="table_relationships",
            severity="high",
            title="fixed offset",
            evidence="n=12",
            location="Fig.3b",
        ),
        Finding.make(
            trace_id="t1",
            detector="image_forensics",
            severity="medium",
            title="ela hit",
            evidence="e",
            location="p1",
        ),
    ]
    object.__setattr__(findings[0], "llm_verdict", "Suspicious fixed offset pattern.")
    object.__setattr__(findings[0], "llm_skipped", False)
    object.__setattr__(findings[1], "llm_skipped", True)

    paths = write_llm_reports(
        root_dir=tmp_path,
        trace_id="t1",
        findings=findings,
        llm_calls=3,
        language="zh",
    )
    assert Path(paths["html"]).is_file()
    assert Path(paths["md"]).is_file()
    assert Path(paths["json"]).is_file()
    assert Path(paths["briefing_html"]).is_file()
    assert Path(paths["briefing_md"]).is_file()
    md = Path(paths["md"]).read_text(encoding="utf-8")
    assert "LLM 解读报告" in md
    assert "Suspicious fixed offset" in md
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "llm_report" in html or "解读" in html
    brief = Path(paths["briefing_html"]).read_text(encoding="utf-8")
    assert "审阅简报" in brief
    assert "优先关注" in brief
    assert "Suspicious fixed offset" in brief
    # Plain investigation (formal concise report, report.zh.html style)
    assert "plain_html" in paths
    plain = Path(paths["plain_html"]).read_text(encoding="utf-8")
    assert "论文诚信初筛报告" in plain
    assert "执行摘要" in plain
    assert "诊断面板" in plain
    assert "免责声明" in plain
    assert "verdict-high" in plain or "高关注" in plain
    # P1: deep-link into pairs report
    assert "investigation_pairs.html#kind-" in plain
    # Pairs localization (primary human entry)
    assert "pairs_html" in paths
    pairs = Path(paths["pairs_html"]).read_text(encoding="utf-8")
    assert "investigation_pairs" in pairs or "配对定位" in pairs
    assert 'id="kind-' in pairs or "kind-table" in pairs
