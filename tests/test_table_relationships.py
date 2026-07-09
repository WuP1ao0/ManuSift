"""Tests for relationship-style tabular anomaly screening."""
from __future__ import annotations

import json

from manusift.contracts import ExtractedTable, ParsedDoc
from manusift.detectors.table_relationships import TableRelationshipDetector


def _table(headers: list[str], rows: list[list[str]]) -> ExtractedTable:
    return ExtractedTable(
        table_id="t-rel",
        source_kind="xlsx",
        source_path="source.xlsx",
        sheet_name="Fig.3",
        source_index=0,
        headers=headers,
        rows=rows,
        fig_name="Fig.3b",
    )


def _named_table(
    table_id: str,
    fig_name: str,
    headers: list[str],
    rows: list[list[str]],
) -> ExtractedTable:
    return ExtractedTable(
        table_id=table_id,
        source_kind="xlsx",
        source_path="source.xlsx",
        sheet_name=fig_name,
        source_index=0,
        headers=headers,
        rows=rows,
        fig_name=fig_name,
    )


def _doc(*tables: ExtractedTable) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-rel",
        source_path="paper.pdf",
        text_blocks=[],
        images=[],
        metadata={},
        tables=list(tables),
    )


def _evidence(finding) -> dict:
    return json.loads(finding.evidence)


def _finding(result, phrase: str):
    return next(f for f in result.findings if phrase in f.title.lower())


def test_detects_fixed_offset_copy_between_columns() -> None:
    table = _table(
        ["control", "treated"],
        [["1.23", "1.33"], ["2.44", "2.54"], ["3.65", "3.75"], ["4.86", "4.96"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "fixed offset")
    assert _evidence(finding)["offset"] == 0.1
    assert "Fig.3b" in finding.location


def test_detects_matching_decimal_tails_across_columns() -> None:
    table = _table(
        ["group_a", "group_b"],
        [["12.37", "13.37"], ["15.42", "16.42"], ["18.59", "19.59"], ["21.64", "22.64"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "matching decimal tails")
    assert _evidence(finding)["matching_pairs"] == 4


def test_detects_integer_shift_with_identical_decimal_tails() -> None:
    table = _table(
        ["parallel_a", "parallel_b"],
        [["12.37", "13.37"], ["15.42", "16.42"], ["18.59", "19.59"], ["21.64", "22.64"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "integer-shift decimal-tail reuse")
    evidence = _evidence(finding)
    assert evidence["integer_offset"] == 1
    assert evidence["matching_pairs"] == 4
    assert evidence["decimal_places"] == 2


def test_detects_one_digit_integer_part_change_with_identical_decimal_tails() -> None:
    table = _table(
        ["parallel_a", "parallel_b"],
        [
            ["12.37", "22.37"],
            ["15.42", "25.42"],
            ["18.59", "28.59"],
            ["21.64", "31.64"],
        ],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "integer-part digit-change decimal-tail reuse")
    evidence = _evidence(finding)
    assert evidence["matching_pairs"] == 4
    assert evidence["changed_integer_digits"] == 1
    assert evidence["decimal_places"] == 2


def test_detects_arithmetic_progression_column() -> None:
    table = _table("dose".split(), [["1.2"], ["1.5"], ["1.8"], ["2.1"], ["2.4"], ["2.7"]])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "arithmetic progression")
    assert _evidence(finding)["step"] == 0.3


def test_detects_near_perfect_arithmetic_progression_column() -> None:
    table = _table(
        ["dose"],
        [["1.2"], ["1.5"], ["1.8"], ["2.1"], ["2.4"], ["2.75"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "near-perfect arithmetic progression")
    evidence = _evidence(finding)
    assert evidence["step"] == 0.3
    assert evidence["matching_diffs"] == 4
    assert evidence["total_diffs"] == 5


def test_detects_terminal_digit_concentration_not_only_zero_or_five() -> None:
    table = _table(["measurement"], [[f"{i}.7"] for i in range(10, 24)])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "terminal digit concentration")
    assert _evidence(finding)["top_digits"] == [["7", 14]]


def test_detects_terminal_digit_pair_concentration() -> None:
    table = _table(
        ["measurement"],
        [["10.0"], ["11.5"], ["12.0"], ["13.5"], ["14.0"], ["15.5"], ["16.0"], ["17.5"], ["18.0"], ["19.5"], ["20.0"], ["21.5"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "terminal digit pair concentration")
    evidence = _evidence(finding)
    assert evidence["top_digits"] == [["0", 6], ["5", 6]]
    assert evidence["combined_fraction"] == 1.0


def test_detects_ones_digit_matching_first_decimal_digit() -> None:
    table = _table(["measurement"], [["11.1"], ["22.2"], ["33.3"], ["44.4"], ["55.5"], ["66.6"]])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "ones digit mirrors first decimal")
    assert _evidence(finding)["matches"] == 6


def test_detects_mirror_symmetric_columns_and_zero_variance() -> None:
    table = _table(
        ["left", "right", "sd"],
        [["1.2", "8.8", "0.10"], ["2.4", "7.6", "0.10"], ["3.6", "6.4", "0.10"], ["4.8", "5.2", "0.10"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    assert _finding(result, "mirror-symmetric")
    assert _finding(result, "zero variance")


def test_detects_zero_standard_deviation_entries() -> None:
    table = _table(
        ["mean", "SD"],
        [["1.20", "0.10"], ["1.40", "0.00"], ["1.70", "0.12"], ["1.90", "0.09"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "zero standard deviation")
    evidence = _evidence(finding)
    assert evidence["zero_count"] == 1
    assert evidence["rows"] == [2]
    assert evidence["column"] == "SD"


def test_detects_constant_standard_deviation_column() -> None:
    table = _table(
        ["mean", "SD"],
        [["1.20", "0.10"], ["1.40", "0.10"], ["1.70", "0.10"], ["1.90", "0.10"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "constant standard deviation")
    evidence = _evidence(finding)
    assert evidence["column"] == "SD"
    assert evidence["value"] == 0.1


def test_detects_improbable_repeated_values_within_column() -> None:
    table = _table(
        ["response"],
        [["5.12"], ["5.12"], ["5.12"], ["5.12"], ["7.44"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "improbable repeated values")
    evidence = _evidence(finding)
    assert evidence["repeated_value"] == 5.12
    assert evidence["repeat_count"] == 4
    assert evidence["n"] == 5


def test_detects_high_duplicate_rate_between_columns() -> None:
    table = _table(
        ["control", "parallel"],
        [
            ["1.23", "1.23"],
            ["2.34", "2.34"],
            ["3.45", "3.45"],
            ["4.56", "4.56"],
            ["5.67", "9.99"],
        ],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "high duplicate rate")
    evidence = _evidence(finding)
    assert evidence["matching_pairs"] == 4
    assert evidence["n"] == 5
    assert evidence["left_column"] == "control"
    assert evidence["right_column"] == "parallel"


def test_detects_high_duplicate_rate_across_multiple_columns() -> None:
    table = _table(
        ["control", "treated_a", "treated_b"],
        [
            ["1.23", "1.23", "1.23"],
            ["2.34", "2.34", "2.34"],
            ["3.45", "3.45", "3.45"],
            ["4.56", "4.56", "4.56"],
            ["5.67", "8.90", "9.01"],
        ],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "multi-column high duplicate rate")
    evidence = _evidence(finding)
    assert evidence["columns"] == ["control", "treated_a", "treated_b"]
    assert evidence["matching_rows"] == 4
    assert evidence["n"] == 5


def test_detects_three_column_additive_relationship() -> None:
    table = _table(
        ["baseline", "delta", "reported"],
        [
            ["1.20", "0.30", "1.50"],
            ["2.10", "0.40", "2.50"],
            ["3.25", "0.50", "3.75"],
            ["4.80", "0.20", "5.00"],
        ],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "additive relationship")
    evidence = _evidence(finding)
    assert evidence["formula"] == "baseline + delta = reported"
    assert evidence["n"] == 4


def test_detects_three_column_subtractive_relationship() -> None:
    table = _table(
        ["total", "baseline", "delta"],
        [
            ["1.50", "1.20", "0.30"],
            ["2.50", "2.10", "0.40"],
            ["3.75", "3.25", "0.50"],
            ["5.00", "4.80", "0.20"],
        ],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "subtractive relationship")
    evidence = _evidence(finding)
    assert evidence["formula"] == "total - baseline = delta"
    assert evidence["n"] == 4


def test_clean_small_table_is_quiet() -> None:
    table = _table(
        ["a", "b", "c"],
        [["1.21", "2.48", "9.13"], ["3.04", "4.19", "8.71"], ["6.52", "1.83", "7.36"], ["2.77", "8.41", "5.92"]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    assert result.findings == []


def test_detects_cross_table_repeated_control_values() -> None:
    left = _named_table(
        "fig3b",
        "Fig.3b",
        ["control"],
        [["5.11"], ["6.22"], ["7.33"], ["8.44"], ["9.55"]],
    )
    right = _named_table(
        "fig4c",
        "Fig.4c",
        ["control"],
        [["5.11"], ["6.22"], ["7.33"], ["8.44"], ["10.66"]],
    )

    result = TableRelationshipDetector().run(_doc(left, right))

    finding = _finding(result, "cross-table repeated values")
    evidence = _evidence(finding)
    assert evidence["matching_pairs"] == 4
    assert "Fig.3b" in evidence["left_table"]
    assert "Fig.4c" in evidence["right_table"]


def test_detects_cross_table_matching_decimal_tails() -> None:
    left = _named_table(
        "fig3b",
        "Fig.3b",
        ["control"],
        [["11.37"], ["14.42"], ["18.59"], ["21.64"]],
    )
    right = _named_table(
        "fig4c",
        "Fig.4c",
        ["treated"],
        [["12.37"], ["15.42"], ["19.59"], ["22.64"]],
    )

    result = TableRelationshipDetector().run(_doc(left, right))

    finding = _finding(result, "cross-table matching decimal tails")
    evidence = _evidence(finding)
    assert evidence["matching_pairs"] == 4
    assert evidence["left_column"] == "control"
    assert evidence["right_column"] == "treated"


def test_detects_cross_table_fixed_offset() -> None:
    left = _named_table(
        "fig3b",
        "Fig.3b",
        ["control"],
        [["1.20"], ["2.10"], ["3.25"], ["4.80"]],
    )
    right = _named_table(
        "fig4c",
        "Fig.4c",
        ["treated"],
        [["1.50"], ["2.40"], ["3.55"], ["5.10"]],
    )

    result = TableRelationshipDetector().run(_doc(left, right))

    finding = _finding(result, "cross-table fixed offset")
    evidence = _evidence(finding)
    assert evidence["offset"] == 0.3
    assert evidence["left_table"] == "Fig.3b in Fig.3b"
    assert evidence["right_table"] == "Fig.4c in Fig.4c"


def test_detects_cross_table_terminal_digit_concentration() -> None:
    left = _named_table(
        "fig3b",
        "Fig.3b",
        ["control"],
        [["10.0"], ["11.5"], ["12.0"], ["13.5"]],
    )
    right = _named_table(
        "fig3c",
        "Fig.3c",
        ["treated"],
        [["14.0"], ["15.5"], ["16.0"], ["17.5"]],
    )

    result = TableRelationshipDetector().run(_doc(left, right))

    finding = _finding(result, "cross-table terminal digit concentration")
    evidence = _evidence(finding)
    assert evidence["top_digits"] == [["0", 4], ["5", 4]]
    assert evidence["combined_fraction"] == 1.0
    assert evidence["n"] == 8
    assert "Fig.3b" in evidence["tables"][0]
    assert "Fig.3c" in evidence["tables"][1]
