"""Tests for table forgery suite (near-dup, cross-copy, gating, orchestrator)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class FakeTable:
    def __init__(
        self,
        headers,
        rows,
        *,
        table_id: str = "",
        fig_name: str = "",
        sheet_name: str = "",
        source_path: str = "",
        source_kind: str = "xlsx",
    ):
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.table_id = table_id or f"t-{id(self)}"
        self.fig_name = fig_name
        self.sheet_name = sheet_name
        self.source_path = source_path
        self.source_kind = source_kind


class FakeDoc:
    def __init__(self, tables):
        self.trace_id = "t-forensics"
        self.tables = list(tables)


def test_near_duplicate_row_catches_one_cell_tweak() -> None:
    from manusift.detectors.table_forensics import NearDuplicateRowDetector

    headers = ["a", "b", "c", "d"]
    base = ["1", "2", "3", "4"]
    tweak = ["1", "2", "3", "9"]  # last cell only
    other = ["10", "20", "30", "40"]
    doc = FakeDoc(
        [FakeTable(headers, [base, tweak, other], sheet_name="S1")]
    )
    result = NearDuplicateRowDetector().run(doc)
    assert len(result.findings) >= 1
    assert result.findings[0].severity in ("high", "medium")
    ev = json.loads(result.findings[0].evidence)
    assert ev["pair_count"] >= 1


def test_near_duplicate_ignores_exact_only_dups() -> None:
    from manusift.detectors.table_forensics import NearDuplicateRowDetector

    # Only exact dups, no near-dups → empty (exact has own detector)
    headers = ["a", "b", "c"]
    rows = [["1", "2", "3"], ["1", "2", "3"], ["9", "8", "7"]]
    doc = FakeDoc([FakeTable(headers, rows)])
    result = NearDuplicateRowDetector().run(doc)
    assert result.findings == []


def test_cross_table_copy_detects_shared_row() -> None:
    from manusift.detectors.table_forensics import CrossTableCopyDetector

    shared = ["PBS", "10.1", "11.2"]
    t1 = FakeTable(
        ["g", "v1", "v2"],
        [shared, ["IOX4", "1", "2"]],
        table_id="t1",
        sheet_name="Fig.4c",
    )
    t2 = FakeTable(
        ["g", "v1", "v2"],
        [shared, ["Sham", "0", "0"]],
        table_id="t2",
        sheet_name="Fig.4e",
    )
    doc = FakeDoc([t1, t2])
    result = CrossTableCopyDetector().run(doc)
    assert len(result.findings) >= 1
    assert "cross" in result.findings[0].location or result.findings[0].detector == (
        "table_cross_copy"
    )


def test_benford_gating_skips_small_n() -> None:
    from manusift.detectors.table_forensics import assess_benford_applicability

    gate = assess_benford_applicability(n=20)
    assert gate["applicable"] is False
    assert "small_n" in gate["flags"]


def test_benford_gating_instrument_keyword_downgrades() -> None:
    from manusift.detectors.table_forensics import assess_benford_applicability

    gate = assess_benford_applicability(
        n=500,
        fig_name="Fig.S1a",
        sheet_name="Sfig.2",
        header="DLS intensity %",
    )
    assert gate["applicable"] is True
    assert gate["max_severity"] == "low"
    assert (
        "instrument_keyword" in gate["flags"]
        or "dls_explicit" in gate["flags"]
        or "psd_figure_context" in gate["flags"]
        or "dls_channel" in gate["flags"]
    )


def test_benford_gating_fig_s1_panel_without_dls_word() -> None:
    """Nature residual FPs: Fig.S1b/d/e with bare/missing channel names."""
    from manusift.detectors.table_forensics import assess_benford_applicability

    for fig, header in (
        ("Fig.S1b", "col1"),
        ("Fig.S1d", ""),
        ("Fig.S1e", "volume"),
        ("Fig.S1c", "number"),
    ):
        gate = assess_benford_applicability(
            n=5000,
            fig_name=fig,
            sheet_name="Sfig.2",
            header=header,
        )
        assert gate["max_severity"] == "low", (fig, header, gate)
        assert "psd_figure_context" in gate["flags"] or "dls_channel_header" in gate[
            "flags"
        ]


def test_benford_gating_intensity_number_volume_headers() -> None:
    from manusift.detectors.table_forensics import assess_benford_applicability

    for header in (
        "Intensity",
        "Number %",
        "Volume",
        "intensity %",
        "Size (nm)",
    ):
        gate = assess_benford_applicability(
            n=800,
            fig_name="",
            sheet_name="export",
            header=header,
        )
        assert gate["max_severity"] == "low", (header, gate)
        assert any(
            f.startswith("dls_channel") or f == "dls_channel"
            for f in gate["flags"]
        ) or "dls_channel_header" in gate["flags"]


def test_benford_gating_size_bin_axis() -> None:
    from manusift.detectors.table_forensics import assess_benford_applicability

    # Classic DLS diameter bins
    bins = [i * 0.00833 for i in range(400)]
    gate = assess_benford_applicability(
        n=len(bins),
        values=bins,
        fig_name="Fig.S1a",
        header="",
    )
    assert gate["max_severity"] == "low"
    assert "size_bin_axis" in gate["flags"] or "psd_figure_context" in gate["flags"]


def test_benford_detector_respects_instrument_gate() -> None:
    from manusift.detectors import BenfordDetector

    # All leading digit 1 → raw would be high; instrument header → low cap
    headers = ["DLS diameter nm"]
    rows = [[str(10**n + 1)] for n in range(200)]
    table = FakeTable(
        headers,
        rows,
        fig_name="Fig.S1a",
        sheet_name="particle size DLS",
    )
    result = BenfordDetector().run(FakeDoc([table]))
    assert len(result.findings) >= 1
    assert result.findings[0].severity == "low"
    ev = json.loads(result.findings[0].evidence)
    assert "applicability" in ev


def test_benford_detector_fig_s1b_intensity_capped_low() -> None:
    """Regression: residual high on Fig.S1b intensity-like column."""
    from manusift.detectors import BenfordDetector

    headers = ["Intensity"]
    # Multi-decade counts, all leading digit skewed → would be high without gate
    rows = [[str(v)] for v in ([11] * 100 + [101] * 100 + [1001] * 100 + [10001] * 100)]
    table = FakeTable(
        headers,
        rows,
        fig_name="Fig.S1b",
        sheet_name="Sfig.2",
    )
    result = BenfordDetector().run(FakeDoc([table]))
    assert len(result.findings) >= 1
    assert result.findings[0].severity == "low"
    flags = json.loads(result.findings[0].evidence)["applicability"]["flags"]
    assert "psd_figure_context" in flags or "dls_channel_header" in flags


def test_table_forensics_orchestrator_summary() -> None:
    from manusift.detectors.table_forensics import TableForensicsDetector

    headers = ["a", "b", "c"]
    rows = [["1", "2", "3"]] * 3 + [["1", "2", "9"], ["9", "8", "7"]]
    doc = FakeDoc([FakeTable(headers, rows, sheet_name="T1")])
    result = TableForensicsDetector().run(doc)
    assert result.ok
    assert result.findings
    assert result.findings[0].detector == "table_forensics"
    assert "risk=" in result.findings[0].title


def test_source_data_audit_accepts_ingest_shape(tmp_path: Path) -> None:
    from manusift.tools.data_audit import (
        audit_data_source,
        normalize_data_source,
    )

    p = tmp_path / "Source_Data.xlsx"
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["x", "y"])
    ws.append([1, 2])
    ws.append([3, 4])
    wb.save(p)

    raw = {
        "table_id": "abc123",
        "source_kind": "xlsx",
        "source_path": str(p),
        "sheet_name": "Fig.1",
    }
    norm = normalize_data_source(raw)
    assert norm["id"] == "abc123"
    assert norm["format"] == "xlsx"
    assert norm["path"] == str(p)

    summary = audit_data_source(raw)
    assert summary.row_count == 2
    assert summary.column_count == 2
    assert not summary.skip_reason


def test_source_data_audit_tool_with_ingest_metadata(tmp_path: Path) -> None:
    from manusift.tools.data_audit import SourceDataAuditTool
    from manusift.tools.tool import ToolContext

    p = tmp_path / "data.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    ctx = ToolContext(
        trace_id="t1",
        metadata={
            "data_sources": [
                {
                    "table_id": "ds-csv",
                    "source_kind": "csv",
                    "source_path": str(p),
                }
            ]
        },
    )
    out = json.loads(SourceDataAuditTool().execute({}, ctx))
    assert out["ok"] is True
    assert out["audit_count"] == 1


def test_table_file_metadata_reads_xlsx_props(tmp_path: Path) -> None:
    import openpyxl
    from manusift.detectors.table_forensics import TableFileMetadataDetector

    p = tmp_path / "s.xlsx"
    wb = openpyxl.Workbook()
    wb.properties.creator = "TestAuthor"
    ws = wb.active
    ws.append(["a"])
    ws.append([1])
    wb.save(p)

    table = FakeTable(
        ["a"],
        [["1"]],
        source_path=str(p),
        source_kind="xlsx",
    )
    result = TableFileMetadataDetector().run(FakeDoc([table]))
    assert result.findings
    # summary low finding always present
    assert any(f.severity == "low" for f in result.findings)
    ev = json.loads(result.findings[-1].evidence)
    assert ev["files"]
    assert any(
        (f.get("creator") == "TestAuthor") for f in ev["files"] if isinstance(f, dict)
    )


def test_detectors_registered() -> None:
    from manusift.detectors import detector_names

    names = set(detector_names())
    for n in (
        "table_forensics",
        "table_near_duplicate_row",
        "table_cross_copy",
        "table_file_metadata",
    ):
        assert n in names


def test_tools_exposed() -> None:
    from manusift.tools import iter_registered_tools

    names = {getattr(t, "name", "") for t in iter_registered_tools()}
    assert "table_forensics" in names
    assert "table_near_duplicate_row" in names
    assert "source_data_audit" in names
