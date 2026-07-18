"""Pairs-localization investigation report (primary human entry)."""
from __future__ import annotations

import json
from pathlib import Path

from manusift.contracts import Finding
from manusift.report.investigation_pairs import (
    build_investigation_pairs_payload,
    normalize_pair_item,
    write_investigation_pairs,
)
from manusift.report.llm_report import write_llm_reports


def _f(
    *,
    detector: str,
    severity: str,
    title: str,
    location: str,
    raw: dict | None = None,
    evidence: str = "e",
) -> Finding:
    return Finding.make(
        trace_id="t-pairs",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence=evidence,
        location=location,
        raw=raw or {},
    )


def test_normalize_table_cross_pair() -> None:
    f = _f(
        detector="table_relationships",
        severity="high",
        title="cross-table fixed offset",
        location="Fig.S1a in Sfig.2, column 1 to Fig.S1c in Sfig.2, column 3",
        raw={
            "check": "cross_table_fixed_offset",
            "n": 12,
            "offset": 0,
            "left_table": "Fig.S1a in Sfig.2",
            "right_table": "Fig.S1c in Sfig.2",
            "left_column": "Fig.S1a",
            "right_column": "Fig.S1c",
        },
    )
    it = normalize_pair_item(f, 1)
    assert it["kind"] == "table_cross"
    assert it["is_pair"] is True
    assert "Fig.S1a" in it["side_a"]
    assert "Fig.S1c" in it["side_b"]
    assert it["location_sufficient"] is True
    assert "固定差" in it["relation"] or "offset" in it["relation"].lower()


def test_normalize_image_pair() -> None:
    f = _f(
        detector="image_forensics",
        severity="medium",
        title="Cross-image local feature match",
        location="Page 3 / image 0 -> Page 5 / image 2",
        raw={
            "kind": "cross_image_sift",
            "image_a": {"page": 2, "index": 0},
            "image_b": {"page": 4, "index": 2},
            "inlier_count": 40,
            "match_count": 80,
        },
    )
    it = normalize_pair_item(f, 2)
    assert it["kind"] == "image_pair"
    assert it["is_pair"] is True
    assert "Page 3" in it["side_a"]
    assert "Page 5" in it["side_b"]
    assert it["location_sufficient"] is True


def test_all_severities_included() -> None:
    findings = [
        _f(
            detector="table_relationships",
            severity="high",
            title="fixed offset",
            location="Table #1, columns 1 and 2",
            raw={
                "check": "fixed_offset",
                "left_column": "A",
                "right_column": "B",
                "n": 10,
                "offset": 0,
            },
        ),
        _f(
            detector="image_forensics",
            severity="low",
            title="Possible copy-move",
            location="Page 1 / image 0",
            raw={"kind": "copy_move", "page": 0, "index": 0},
        ),
        _f(
            detector="compliance",
            severity="info",
            title="meta",
            location="pdf",
            raw={},
        ),
    ]
    payload = build_investigation_pairs_payload(
        trace_id="t-pairs", findings=findings, language="zh"
    )
    assert payload["schema"] == "manusift.investigation_pairs.v1"
    assert payload["counts"]["total"] == 3
    sevs = {i["severity"] for i in payload["items"]}
    assert sevs == {"high", "low", "info"}
    # insufficient location should capture bare "pdf"
    insuff = [i for i in payload["items"] if not i["location_sufficient"]]
    assert any(i["severity"] == "info" for i in insuff)


def test_write_investigation_pairs_files(tmp_path: Path) -> None:
    findings = [
        _f(
            detector="table_relationships",
            severity="high",
            title="fixed offset",
            location="Fig.3b, columns 1 and 2",
            raw={
                "check": "fixed_offset",
                "left_column": "ctrl",
                "right_column": "treat",
                "offset": 0,
                "n": 8,
            },
        ),
    ]
    object.__setattr__(findings[0], "llm_verdict", "两列差恒定，建议核原始记录。")
    paths = write_investigation_pairs(
        root_dir=tmp_path,
        trace_id="t-pairs",
        findings=findings,
        llm_calls=1,
        language="zh",
    )
    html = Path(paths["pairs_html"])
    md = Path(paths["pairs_md"])
    js = Path(paths["pairs_json"])
    assert html.is_file()
    assert md.is_file()
    assert js.is_file()
    assert html.name == "investigation_pairs.html"
    text = html.read_text(encoding="utf-8")
    assert "配对定位" in text
    assert "索引总表" in text
    assert "ctrl" in text or "Fig.3" in text
    assert "不是" in text or "非" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["counts"]["total"] == 1
    assert data["items"][0]["location_sufficient"] is True


def test_write_llm_reports_emits_pairs(tmp_path: Path) -> None:
    findings = [
        _f(
            detector="table_relationships",
            severity="high",
            title="fixed offset",
            location="Fig.1, columns 1 and 2",
            raw={
                "check": "fixed_offset",
                "left_column": "a",
                "right_column": "b",
            },
        ),
    ]
    paths = write_llm_reports(
        root_dir=tmp_path,
        trace_id="t1",
        findings=findings,
        llm_calls=0,
        language="zh",
    )
    assert "pairs_html" in paths
    assert Path(paths["pairs_html"]).is_file()
    assert Path(paths["pairs_html"]).name == "investigation_pairs.html"
    assert "plain_html" in paths
