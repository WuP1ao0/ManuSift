"""P4a figure table OCR — pure logic tests (no EasyOCR required)."""
from __future__ import annotations

from manusift.contracts import ExtractedTable, Finding, ParsedDoc
from manusift.detectors.figure_table_ocr import (
    FigureTableOCRDetector,
    cluster_ocr_to_grid,
    grid_numeric_stats,
    is_table_like,
    numbers_from_extracted_tables,
    ocr_vs_source_mismatch,
)


def test_cluster_ocr_to_grid_rows() -> None:
    # two rows by y, two cols by x
    dets = [
        ([[0, 0], [10, 0], [10, 10], [0, 10]], "A", 0.9),
        ([[50, 0], [60, 0], [60, 10], [50, 10]], "B", 0.9),
        ([[0, 40], [10, 40], [10, 50], [0, 50]], "1.2", 0.9),
        ([[50, 40], [60, 40], [60, 50], [50, 50]], "3.4", 0.9),
    ]
    grid = cluster_ocr_to_grid(dets, y_tol=15.0)
    assert len(grid) == 2
    assert grid[0] == ["A", "B"]
    assert grid[1] == ["1.2", "3.4"]


def test_is_table_like_and_stats() -> None:
    grid = [
        ["g1", "g2", "g3"],
        ["1.0", "2.0", "3.0"],
        ["1.1", "2.1", "3.1"],
        ["1.2", "2.2", "3.2"],
    ]
    stats = grid_numeric_stats(grid)
    assert stats["n_numeric"] == 9
    assert is_table_like(stats)


def test_ocr_vs_source_mismatch() -> None:
    ocr = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    src = [1.0, 2.0, 3.0]  # most OCR missing
    mm = ocr_vs_source_mismatch(ocr, src, min_ocr=8)
    assert mm is not None
    assert mm["missing_fraction"] >= 0.45


def test_numbers_from_xlsx_tables() -> None:
    t = ExtractedTable(
        table_id="t1",
        source_kind="xlsx",
        source_path="/tmp/a.xlsx",
        sheet_name="Fig1",
        source_index=0,
        headers=["a", "b"],
        rows=[["1.5", "2.5"], ["3.5", "x"]],
    )
    nums = numbers_from_extracted_tables([t], kinds={"xlsx"})
    assert nums == [1.5, 2.5, 3.5]


def test_detector_no_op_without_easyocr(monkeypatch) -> None:
    import manusift.detectors.figure_table_ocr as mod

    monkeypatch.setattr(mod, "_HAS_EASYOCR", False)
    det = FigureTableOCRDetector()
    doc = ParsedDoc(
        trace_id="t",
        source_path="/tmp/x.pdf",
        images=[],
        text_blocks=[],
        metadata={},
    )
    res = det.run(doc)
    assert res.ok
    assert res.findings == []


def test_zero_variance_column_logic() -> None:
    from manusift.detectors.figure_table_ocr import _column_zero_variance

    grid = [
        ["1", "9"],
        ["1", "8"],
        ["1", "7"],
        ["1", "6"],
    ]
    hits = _column_zero_variance(grid)
    assert any(h["column"] == 1 for h in hits)
