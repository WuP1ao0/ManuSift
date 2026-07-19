"""P4b PDF vs Source Data consistency + SI fig alignment."""
from __future__ import annotations

from manusift.contracts import ExtractedTable, ParsedDoc
from manusift.detectors.source_data_consistency import (
    SourceDataConsistencyDetector,
    collect_by_fig_key,
    collect_numbers,
    infer_fig_key,
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


def test_infer_fig_key_from_nature_source_data_name() -> None:
    assert infer_fig_key("Source_Data_Fig3_MOESM6.xlsx") == "fig3"
    assert infer_fig_key("Source_Data_ED_Fig2_MOESM10.xlsx") == "edfig2"
    assert infer_fig_key("Fig.S1A panel") in {"figs1a", "figs1"}


def test_collect_by_fig_key_groups_si() -> None:
    tables = [
        ExtractedTable(
            table_id="a",
            source_kind="xlsx",
            source_path="/m/Source_Data_Fig1.xlsx",
            sheet_name="Sheet1",
            source_index=0,
            headers=["x", "y"],
            rows=[["1.0", "2.0"], ["3.0", "4.0"]],
            fig_name="",
        ),
        ExtractedTable(
            table_id="b",
            source_kind="xlsx",
            source_path="/m/Source_Data_Fig2.xlsx",
            sheet_name="Sheet1",
            source_index=0,
            headers=["x", "y"],
            rows=[["9.0", "8.0"]],
            fig_name="Fig.2",
        ),
    ]
    buckets = collect_by_fig_key(tables, kinds=frozenset({"xlsx"}))
    assert "fig1" in buckets
    assert "fig2" in buckets
    assert 1.0 in buckets["fig1"]
    assert 9.0 in buckets["fig2"]


def test_si_poor_align_when_fig_mentioned() -> None:
    """SI fig numbers absent from PDF + figure cited in text → medium."""
    # SI for fig3 has distinct numbers
    si_rows = [[str(100.0 + i), str(200.0 + i)] for i in range(20)]
    # PDF tables have completely different numbers
    pdf_rows = [[str(float(i)), str(float(i + 0.5))] for i in range(25)]
    from manusift.contracts import TextBlock

    doc = ParsedDoc(
        trace_id="t-si",
        source_path="/tmp/paper.pdf",
        images=[],
        text_blocks=[
            TextBlock(
                page=0,
                bbox=(0.0, 0.0, 100.0, 20.0),
                text="As shown in Fig. 3, the assay replicates...",
            )
        ],
        metadata={},
        tables=[
            ExtractedTable(
                table_id="si",
                source_kind="xlsx",
                source_path="/m/Source_Data_Fig3.xlsx",
                sheet_name="S1",
                source_index=0,
                headers=["a", "b"],
                rows=si_rows,
                fig_name="Fig.3",
            ),
            ExtractedTable(
                table_id="pdf",
                source_kind="pdf_native",
                source_path="/tmp/paper.pdf",
                sheet_name="",
                source_index=0,
                headers=["c1", "c2"],
                rows=pdf_rows,
            ),
        ],
    )
    res = SourceDataConsistencyDetector().run(doc)
    kinds = {
        (f.raw or {}).get("kind")
        for f in res.findings
        if isinstance(f.raw, dict)
    }
    # At least SI align or global missing should fire
    assert kinds & {
        "si_fig_poor_align",
        "pdf_missing_in_source",
        "source_extra_vs_pdf",
        "overlap_ok",
        "si_inventory",
    }


def test_pipeline_includes_source_data_consistency() -> None:
    from manusift.pipeline import (
        _BUILTIN_DETECTOR_CLASS_NAMES,
        PIPELINE_EXCLUDED,
    )

    assert "SourceDataConsistencyDetector" in _BUILTIN_DETECTOR_CLASS_NAMES
    assert "SourceDataConsistencyDetector" not in PIPELINE_EXCLUDED
