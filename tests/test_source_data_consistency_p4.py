"""P4b PDF vs Source Data consistency."""
from __future__ import annotations

from manusift.contracts import ExtractedTable, ParsedDoc
from manusift.detectors.source_data_consistency import (
    SourceDataConsistencyDetector,
    collect_numbers,
    multiset_missing_fraction,
)


def _table(kind: str, rows: list[list[str]], *, headers: list[str] | None = None) -> ExtractedTable:
    return ExtractedTable(
        table_id=f"{kind}-1",
        source_kind=kind,
        source_path=f"/tmp/{kind}.dat",
        sheet_name="S1",
        source_index=0,
        headers=headers or ["c1", "c2"],
        rows=rows,
    )


def test_multiset_missing() -> None:
    frac, miss, total = multiset_missing_fraction(
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        [1, 2, 3],
    )
    assert total == 10
    assert miss >= 7
    assert frac >= 0.5


def test_collect_by_kind() -> None:
    tables = [
        _table("pdf_native", [["1.0", "2.0"]]),
        _table("xlsx", [["1.0", "9.0"]]),
    ]
    pdf, _ = collect_numbers(tables, kinds=frozenset({"pdf_native"}))
    src, _ = collect_numbers(tables, kinds=frozenset({"xlsx"}))
    assert 1.0 in pdf and 2.0 in pdf
    assert 9.0 in src


def test_detector_flags_pdf_missing_in_source() -> None:
    # PDF has many unique values; source only a few overlapping
    pdf_rows = [[str(float(i)), str(float(i + 0.1))] for i in range(20)]
    src_rows = [["0.0", "0.1"], ["1.0", "1.1"]]
    doc = ParsedDoc(
        trace_id="t",
        source_path="/tmp/x.pdf",
        images=[],
        text_blocks=[],
        metadata={},
        tables=[
            _table("pdf_native", pdf_rows),
            _table("xlsx", src_rows),
        ],
    )
    res = SourceDataConsistencyDetector().run(doc)
    assert res.ok
    kinds = {
        (f.raw or {}).get("kind")
        for f in res.findings
        if isinstance(f.raw, dict)
    }
    assert "pdf_missing_in_source" in kinds
    high_or_med = [f for f in res.findings if f.severity in ("high", "medium")]
    assert high_or_med


def test_detector_no_source_info() -> None:
    pdf_rows = [[str(float(i)), str(float(i + 1))] for i in range(15)]
    doc = ParsedDoc(
        trace_id="t",
        source_path="/tmp/x.pdf",
        images=[],
        text_blocks=[],
        metadata={},
        tables=[_table("pdf_native", pdf_rows)],
    )
    res = SourceDataConsistencyDetector().run(doc)
    assert any(
        isinstance(f.raw, dict) and f.raw.get("kind") == "no_source_data"
        for f in res.findings
    )


def test_detector_registered() -> None:
    from manusift.detectors import detector_name_for_class

    assert (
        detector_name_for_class("SourceDataConsistencyDetector")
        == "source_data_consistency"
    )
    assert detector_name_for_class("FigureTableOCRDetector") == "figure_table_ocr"
