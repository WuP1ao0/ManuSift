"""Tests for ``manusift.tools.data_audit``.

Covers issue 4 (no stable source-data audit tool
exists; the LLM used to spawn sub-agents to write
one-off scripts). The contract:

  * ``audit_data_source(ds)`` returns an
    ``AuditSummary`` with per-column
    missing/distinct/duplicate/min/max/mean/stdev/
    outlier counts;
  * the tool is deterministic and dependency-free
    (openpyxl is imported lazily so the rest of the
    tool can be smoke-tested without it);
  * the result is JSON-friendly via
    ``audit_to_dict``;
  * a source with ``row_count > cap`` returns a
    typed ``skip_reason`` instead of silently
    truncating;
  * unsupported formats and missing files return
    typed ``skip_reason``s;
  * the ``SourceDataAuditTool`` end-to-end wrapper
    returns a typed ``error_kind:
    data_source_missing`` when no data sources are
    registered.

Pattern follows claw-code's
``rust/crates/rusty-claude-cli/tests/output_format_contract.rs``.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from manusift.tools.data_audit import (
    AuditSummary,
    ColumnReport,
    SourceDataAuditTool,
    _analyze_column,
    _classify_dtype,
    _read_csv_or_tsv,
    _read_json,
    _read_xlsx,
    audit_data_source,
    audit_to_dict,
)
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# CSV/TSV reading
# --------------------------------------------------------------------


def test_read_csv_basic(tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text(
        "a,b,c\n1,2,3\n4,5,6\n", encoding="utf-8"
    )
    header, rows = _read_csv_or_tsv(p, "csv")
    assert header == ["a", "b", "c"]
    assert rows == [["1", "2", "3"], ["4", "5", "6"]]


def test_read_tsv_uses_tab_delimiter(tmp_path: Path):
    p = tmp_path / "x.tsv"
    p.write_text("a\tb\tc\n1\t2\t3\n", encoding="utf-8")
    header, rows = _read_csv_or_tsv(p, "tsv")
    assert header == ["a", "b", "c"]
    assert rows == [["1", "2", "3"]]


def test_read_csv_empty_file(tmp_path: Path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    header, rows = _read_csv_or_tsv(p, "csv")
    assert header == []
    assert rows == []


# --------------------------------------------------------------------
# JSON reading
# --------------------------------------------------------------------


def test_read_json_records(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(
        json.dumps([
            {"a": 1, "b": "x"},
            {"a": 2, "b": "y"},
        ]),
        encoding="utf-8",
    )
    header, rows = _read_json(p)
    assert "a" in header and "b" in header
    assert len(rows) == 2


def test_read_json_non_array_raises(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text("{\"a\": 1}", encoding="utf-8")
    with pytest.raises(ValueError):
        _read_json(p)


def test_read_json_empty_array(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text("[]", encoding="utf-8")
    header, rows = _read_json(p)
    assert header == []
    assert rows == []


# --------------------------------------------------------------------
# XLSX reading (smoke)
# --------------------------------------------------------------------


def test_read_xlsx_basic(tmp_path: Path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    ws.append([1, 2])
    p = tmp_path / "x.xlsx"
    wb.save(p)

    header, rows = _read_xlsx(p)
    assert header == ["a", "b"]
    assert rows == [["1", "2"]]


# --------------------------------------------------------------------
# dtype classification
# --------------------------------------------------------------------


def test_classify_dtype_int():
    assert _classify_dtype(["1", "2", "3"]) == "int"


def test_classify_dtype_float():
    assert _classify_dtype(["1.5", "2.5"]) == "float"


def test_classify_dtype_string():
    assert _classify_dtype(["a", "b", "c"]) == "string"


def test_classify_dtype_bool():
    assert _classify_dtype(["true", "false"]) == "bool"


def test_classify_dtype_empty():
    assert _classify_dtype([]) == "empty"


def test_classify_dtype_mixed():
    """Mixed int + non-numeric falls back to string.
    """
    assert (
        _classify_dtype(["1", "two", "3"]) == "string"
    )


# --------------------------------------------------------------------
# column analysis
# --------------------------------------------------------------------


def test_analyze_column_int_clean():
    rep = _analyze_column(
        "n", ["1", "2", "3", "4", "5"], row_count=5
    )
    assert rep.dtype == "int"
    assert rep.missing == 0
    assert rep.distinct == 5
    assert rep.duplicates == 0
    assert rep.min == 1
    assert rep.max == 5
    assert rep.mean == 3.0


def test_analyze_column_missing_flag():
    """A column with >5% missing gets
    ``flags=("missing_over_5pct",)``.
    """
    rep = _analyze_column(
        "x", ["", "", "1", "2", "3", "4", "5", "6", "7", "8"],
        row_count=10,
    )
    assert "missing_over_5pct" in rep.flags
    assert rep.missing == 2


def test_analyze_column_duplicates_flag():
    """A column with >10% duplicates gets
    ``flags=("duplicates_over_10pct",)``.
    """
    rep = _analyze_column(
        "x", ["1", "1", "1", "1", "1", "2", "3", "4", "5", "6"],
        row_count=10,
    )
    assert "duplicates_over_10pct" in rep.flags
    assert rep.duplicates == 4


def test_analyze_column_string_dtype():
    rep = _analyze_column(
        "label",
        ["alpha", "beta", "gamma", "alpha", "beta"],
        row_count=5,
    )
    assert rep.dtype == "string"
    assert rep.min is None
    assert rep.max is None
    assert rep.mean is None


# --------------------------------------------------------------------
# Top-level audit
# --------------------------------------------------------------------


def test_audit_csv_returns_clean_summary(tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text(
        "id,score,label\n"
        "1,0.91,a\n2,0.84,b\n3,0.77,c\n4,0.99,d\n5,0.55,e\n",
        encoding="utf-8",
    )
    summary = audit_data_source(
        {"id": "ds-1", "format": "csv", "path": str(p)}
    )
    assert summary.row_count == 5
    assert summary.column_count == 3
    assert summary.content_hash != ""
    assert summary.schema_hash != ""
    assert summary.duplicates_total == 0
    assert summary.missing_pct_overall == 0.0
    # Per-column
    by_name = {c.name: c for c in summary.columns}
    assert by_name["id"].dtype == "int"
    assert by_name["score"].dtype == "float"
    assert by_name["label"].dtype == "string"


def test_audit_xlsx(tmp_path: Path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["col1", "col2"])
    ws.append([1, "x"])
    ws.append([2, "y"])
    p = tmp_path / "x.xlsx"
    wb.save(p)

    summary = audit_data_source(
        {"id": "ds-x", "format": "xlsx", "path": str(p)}
    )
    assert summary.row_count == 2
    assert summary.column_count == 2


def test_audit_json(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(
        json.dumps([
            {"a": 1, "b": "x"},
            {"a": 2, "b": "y"},
            {"a": 3, "b": "x"},
        ]),
        encoding="utf-8",
    )
    summary = audit_data_source(
        {"id": "ds-j", "format": "json", "path": str(p)}
    )
    assert summary.row_count == 3
    assert summary.column_count == 2
    by_name = {c.name: c for c in summary.columns}
    # "x" appears twice -- 1 duplicate.
    assert by_name["b"].duplicates == 1


def test_audit_missing_file(tmp_path: Path):
    summary = audit_data_source(
        {
            "id": "ds-missing",
            "format": "csv",
            "path": str(tmp_path / "no.csv"),
        }
    )
    assert summary.skip_reason is not None
    assert "not found" in summary.skip_reason
    assert summary.row_count == 0


def test_audit_unsupported_format(tmp_path: Path):
    p = tmp_path / "x.dat"
    p.write_text("...", encoding="utf-8")
    summary = audit_data_source(
        {"id": "ds-x", "format": "pdf", "path": str(p)}
    )
    assert summary.skip_reason is not None
    assert "unsupported" in summary.skip_reason


def test_audit_row_count_cap_returns_skip(tmp_path: Path):
    """A file whose capped row count exceeds the cap
    returns a typed ``skip_reason`` pointing the LLM
    at ``table_scan``.
    """
    p = tmp_path / "big.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["a", "b"])
        for i in range(200):
            w.writerow([i, i * 2])
    # max_rows=50 -> the reader returns all 200 rows
    # (the cap is on the *analyzed* count, which is
    # 200 here). The audit must NOT silently
    # truncate; it returns a typed skip_reason.
    summary = audit_data_source(
        {"id": "ds-big", "format": "csv", "path": str(p)},
        max_rows=50,
    )
    assert summary.skip_reason is not None
    assert "table_scan" in summary.skip_reason


# --------------------------------------------------------------------
# audit_to_dict
# --------------------------------------------------------------------


def test_audit_to_dict_replaces_nan_with_none(tmp_path: Path):
    """A column with stdev=0 produces NaN-free JSON.
    """
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n1\n1\n1\n", encoding="utf-8")
    summary = audit_data_source(
        {"id": "ds-z", "format": "csv", "path": str(p)}
    )
    d = audit_to_dict(summary)
    # Should be JSON-serializable.
    j = json.dumps(d)
    parsed = json.loads(j)
    assert "columns" in parsed
    # The ``stdev`` field must be present (0.0 is OK).
    stdev = parsed["columns"][0]["stdev"]
    assert stdev is not None
    assert stdev == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------
# SourceDataAuditTool wrapper
# --------------------------------------------------------------------


def test_tool_no_data_sources_returns_data_source_missing():
    """When ``ctx.metadata['data_sources']`` is empty,
    the tool returns ``error_kind:
    data_source_missing``.
    """
    tool = SourceDataAuditTool()
    out = json.loads(
        tool.execute({}, ToolContext(trace_id="t"))
    )
    assert out["ok"] is False
    assert out["error_kind"] == "data_source_missing"


def test_tool_no_metadata_returns_data_source_missing():
    tool = SourceDataAuditTool()
    ctx = ToolContext(trace_id="t")  # metadata={}
    out = json.loads(tool.execute({}, ctx))
    assert out["ok"] is False
    assert out["error_kind"] == "data_source_missing"


def test_tool_runs_audit_on_registered_sources(tmp_path: Path):
    """When data sources are registered, the tool
    audits each and returns a JSON report.
    """
    p = tmp_path / "x.csv"
    p.write_text(
        "a,b\n1,2\n3,4\n5,6\n", encoding="utf-8"
    )
    ctx = ToolContext(
        trace_id="t",
        metadata={
            "data_sources": [
                {
                    "id": "ds-1",
                    "format": "csv",
                    "path": str(p),
                }
            ]
        },
    )
    tool = SourceDataAuditTool()
    out = json.loads(tool.execute({}, ctx))
    assert out["ok"] is True
    assert out["audit_count"] == 1
    assert out["duplicates_total"] == 0
    assert out["missing_total"] == 0
    assert out["summaries"][0]["row_count"] == 3
    assert out["summaries"][0]["column_count"] == 2


def test_tool_filter_by_data_source_ids(tmp_path: Path):
    """The ``data_source_ids`` input filters which
    sources to audit.
    """
    a = tmp_path / "a.csv"
    a.write_text("x\n1\n2\n", encoding="utf-8")
    b = tmp_path / "b.csv"
    b.write_text("y\n9\n9\n", encoding="utf-8")
    ctx = ToolContext(
        trace_id="t",
        metadata={
            "data_sources": [
                {"id": "ds-a", "format": "csv", "path": str(a)},
                {"id": "ds-b", "format": "csv", "path": str(b)},
            ]
        },
    )
    tool = SourceDataAuditTool()
    out = json.loads(
        tool.execute({"data_source_ids": ["ds-a"]}, ctx)
    )
    assert out["ok"] is True
    assert out["audit_count"] == 1
    assert out["summaries"][0]["data_source_id"] == "ds-a"


def test_tool_filter_no_match_returns_data_source_missing(
    tmp_path: Path,
):
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n", encoding="utf-8")
    ctx = ToolContext(
        trace_id="t",
        metadata={
            "data_sources": [
                {"id": "ds-1", "format": "csv", "path": str(p)}
            ]
        },
    )
    tool = SourceDataAuditTool()
    out = json.loads(
        tool.execute(
            {"data_source_ids": ["nonexistent"]}, ctx
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "data_source_missing"
    assert "ds-1" in out["data_sources_available"]


def test_tool_in_registry():
    """The new tool is auto-registered.
    """
    from manusift.tools import tool_names
    names = tool_names()
    assert "source_data_audit" in names
