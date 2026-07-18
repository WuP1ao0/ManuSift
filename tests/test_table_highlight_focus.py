"""P0: table highlight-focus detector + deep suite defaults."""
from __future__ import annotations

from manusift.contracts import ExtractedTable, ParsedDoc
from manusift.detectors.table_highlight import (
    TableHighlightFocusDetector,
    _is_yellow_like,
)


def _table(
    *,
    headers: list[str],
    rows: list[list[str]],
    highlighted: list[dict],
    fig_name: str = "Fig.3b",
) -> ExtractedTable:
    return ExtractedTable(
        table_id="t-hl-1",
        source_kind="xlsx",
        source_path="/tmp/si.xlsx",
        sheet_name="Source Data",
        source_index=0,
        headers=headers,
        rows=rows,
        fig_name=fig_name,
        highlighted_cells=highlighted,
    )


def _doc(*tables: ExtractedTable) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-hl",
        source_path="<test>",
        text_blocks=[],
        images=[],
        tables=list(tables),
        metadata={},
    )


def test_yellow_like_detects_common_fills() -> None:
    assert _is_yellow_like("FFFF00") is True
    assert _is_yellow_like("FFEB9C") is True
    assert _is_yellow_like("0000FF") is False
    assert _is_yellow_like(None) is False


def test_no_highlights_empty_result() -> None:
    t = _table(
        headers=["A", "B"],
        rows=[["1.0", "2.0"], ["1.1", "2.1"]],
        highlighted=[],
    )
    # strip highlights
    t = ExtractedTable(
        table_id="t0",
        source_kind="xlsx",
        source_path="/tmp/x.xlsx",
        sheet_name="S",
        source_index=0,
        headers=["A", "B"],
        rows=[["1", "2"], ["3", "4"]],
        fig_name="",
        highlighted_cells=[],
    )
    res = TableHighlightFocusDetector().run(_doc(t))
    assert res.ok
    assert res.findings == []


def test_inventory_and_summary_on_yellow_cells() -> None:
    hl = [
        {
            "row": i,
            "col": 0,
            "source_row": i + 2,
            "source_col": 1,
            "value": "1.23",
            "fill": "FFFF00",
        }
        for i in range(4)
    ]
    t = _table(
        headers=["ctrl", "treat"],
        rows=[[str(1.0 + i * 0.1), "0"] for i in range(4)],
        highlighted=hl,
        fig_name="Fig.3b",
    )
    res = TableHighlightFocusDetector().run(_doc(t))
    kinds = {f.raw.get("kind") for f in res.findings}
    assert "highlight_summary" in kinds
    assert "highlight_inventory" in kinds
    inv = next(f for f in res.findings if f.raw.get("kind") == "highlight_inventory")
    assert inv.raw["n_yellow_like"] == 4
    assert "Fig" in inv.title or "Fig.3b" in inv.title or "3b" in inv.location


def test_highlighted_column_repeated_values() -> None:
    # All yellow cells share the same numeric value
    hl = [
        {
            "row": i,
            "col": 0,
            "value": "5.50",
            "fill": "FFFF00",
            "source_row": i + 2,
            "source_col": 1,
        }
        for i in range(4)
    ]
    t = _table(
        headers=["ctrl", "x"],
        rows=[["5.50", "1"], ["5.50", "2"], ["5.50", "3"], ["5.50", "4"]],
        highlighted=hl,
    )
    res = TableHighlightFocusDetector().run(_doc(t))
    reps = [
        f
        for f in res.findings
        if f.raw.get("kind") == "highlight_column_repeated_values"
    ]
    assert len(reps) == 1
    assert reps[0].severity == "high"


def test_highlighted_columns_fixed_offset() -> None:
    hl = []
    rows = []
    for i in range(4):
        a = 1.0 + i
        b = a + 0.3
        rows.append([f"{a:.1f}", f"{b:.1f}"])
        hl.append(
            {
                "row": i,
                "col": 0,
                "value": f"{a:.1f}",
                "fill": "FFFF00",
                "source_row": i + 2,
                "source_col": 1,
            }
        )
        hl.append(
            {
                "row": i,
                "col": 1,
                "value": f"{b:.1f}",
                "fill": "FFFF00",
                "source_row": i + 2,
                "source_col": 2,
            }
        )
    t = _table(headers=["col3", "col4"], rows=rows, highlighted=hl)
    res = TableHighlightFocusDetector().run(_doc(t))
    offs = [f for f in res.findings if f.raw.get("kind") == "highlight_fixed_offset"]
    assert len(offs) >= 1
    assert "0.3" in offs[0].title or offs[0].raw.get("offset") in {"0.3", "0.300000"}


def test_detector_registered() -> None:
    from manusift.detectors import TableHighlightFocusDetector as Cls
    from manusift.detectors import detector_name_for_class

    assert Cls().name == "table_highlight_focus"
    assert detector_name_for_class("TableHighlightFocusDetector") == (
        "table_highlight_focus"
    )


def test_deep_suite_is_full_pipeline() -> None:
    from manusift.cli import SUITE_DETECTORS

    assert SUITE_DETECTORS["deep"] is None
    assert SUITE_DETECTORS["full"] is None
    assert "table_highlight_focus" in SUITE_DETECTORS["core"]
    assert "table_highlight_focus" in SUITE_DETECTORS["table"]


def test_default_screen_suite_is_deep() -> None:
    from manusift.cli import build_parser

    p = build_parser()
    ns = p.parse_args(["screen", "paper.pdf"])
    assert ns.suites == "deep"
    assert getattr(ns, "deep", False) is False
    ns2 = p.parse_args(["screen", "paper.pdf", "--deep"])
    assert ns2.deep is True


def test_pipeline_includes_highlight_detector() -> None:
    from manusift.pipeline import _BUILTIN_DETECTOR_CLASS_NAMES

    assert "TableHighlightFocusDetector" in _BUILTIN_DETECTOR_CLASS_NAMES
