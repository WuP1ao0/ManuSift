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


# ---------- statistical column checks (2026-07) ----------

def _checks(result) -> set[str]:
    return {
        json.loads(f.evidence).get("check", "")
        for f in result.findings
    }


def test_arithmetic_sequence_sorted_caught_scrambled() -> None:
    """A scrambled arithmetic progression (constant step after
    sorting) must fire even though raw-order diffs vary."""
    table = _table(
        ["v"],
        [[str(v)] for v in [10.0, 40.0, 20.0, 50.0, 30.0, 70.0, 60.0, 90.0, 80.0]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "arithmetic sequence")
    assert _evidence(finding)["check"] == "arithmetic_sequence_sorted"
    assert finding.severity == "medium"


def test_arithmetic_sequence_skips_regular_axis() -> None:
    """A monotonic, regularly spaced column (instrument bin axis /
    sampling grid) must NOT be flagged."""
    table = _table(
        ["size"],
        [[str(i * 0.5)] for i in range(12)],
    )

    result = TableRelationshipDetector().run(_doc(table))

    assert "arithmetic_sequence_sorted" not in _checks(result)
    assert "modal_gap_sequence" not in _checks(result)


def test_arithmetic_sequence_skips_pure_index() -> None:
    """Plain 1..n index columns must NOT be flagged."""
    table = _table(["id"], [[str(i)] for i in range(1, 11)])

    result = TableRelationshipDetector().run(_doc(table))

    assert "arithmetic_sequence_sorted" not in _checks(result)
    assert "modal_gap_sequence" not in _checks(result)


def test_modal_gap_sequence_caught_time_schedule() -> None:
    """Fig-1i-like sampling column: dominant 12.0 spacing after an
    irregular start."""
    table = _table(
        ["time"],
        [[str(v)] for v in [0.5, 1, 3, 5, 12, 24, 36, 48, 60, 72, 84, 96, 120]],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "dominant repeated spacing")
    evidence = _evidence(finding)
    assert evidence["check"] == "modal_gap_sequence"
    assert evidence["modal_gap"] == 12
    assert evidence["mode_count"] == 7
    assert evidence["on_quantization_lattice"] is False
    assert finding.severity == "medium"


def test_modal_gap_on_lattice_is_low() -> None:
    """S16-like dense two-decimal column: the modal gap equals the
    quantization step, so severity must drop to low."""
    values = [
        1.08, 1.04, 0.95, 0.97, 0.95, 1.0, 0.96, 1.11,
        1.02, 0.94, 0.99, 1.03, 1.02, 0.98, 0.97,
    ]
    table = _table(["sham"], [[str(v)] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "dominant repeated spacing")
    evidence = _evidence(finding)
    assert evidence["on_quantization_lattice"] is True
    assert finding.severity == "low"


def test_duplicate_excess_caught() -> None:
    """Six identical two-decimal values among 20 must hugely exceed
    the birthday-problem collision expectation."""
    values = [12.34] * 6 + [
        10.01, 11.02, 13.03, 14.04, 15.05, 16.06, 17.07,
        18.08, 19.09, 20.10, 21.11, 22.12, 23.13, 24.14,
    ]
    table = _table(["v"], [[str(v)] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "statistically improbable duplicate values")
    evidence = _evidence(finding)
    assert evidence["check"] == "duplicate_excess"
    assert evidence["duplicate_pairs"] == 15
    assert finding.severity == "high"


def test_duplicate_excess_clean_column_quiet() -> None:
    table = _table(
        ["v"],
        [[f"{10 + i}.{i:02d}"] for i in range(20)],
    )

    result = TableRelationshipDetector().run(_doc(table))

    assert "duplicate_excess" not in _checks(result)


def test_duplicate_excess_excludes_zero_ties() -> None:
    """Instrument floor zeros are legitimately tied; a column with
    8 zeros (below the improbable_repeated fraction gate) must not
    fire duplicate_excess on zero pairs alone."""
    values = [0.0] * 8 + [1.01, 2.02, 3.03, 4.04, 5.05, 6.06, 7.07, 8.08, 9.09, 10.10, 11.11, 12.12]
    table = _table(["v"], [[str(v)] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    assert "duplicate_excess" not in _checks(result)


def test_duplicate_excess_does_not_double_report_dominant_value() -> None:
    """Columns already caught by ``improbable_repeated_values``
    (top fraction >= MIN_DUPLICATE_FRACTION) must not ALSO get a
    duplicate_excess finding."""
    values = [7.5] * 12 + [1.1, 2.2, 3.3, 4.4]
    table = _table(["v"], [[str(v)] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    checks = _checks(result)
    assert "improbable_repeated_values" in checks
    assert "duplicate_excess" not in checks


def test_duplicate_excess_pooled_across_columns() -> None:
    """Fig-1i-like cross-group value reuse: two parallel columns
    sharing many exact values must fire the pooled scope."""
    shared = ["20.15", "21.13", "25.89", "31", "44.94", "50.1"]
    left = shared + ["10.31", "51.63"]
    right = shared + ["18.68", "50.68"]
    table = _table(
        ["a", "b"],
        [[l, r] for l, r in zip(left, right)],
    )

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(
        result, "statistically improbable duplicate values across columns"
    )
    assert _evidence(finding)["duplicate_pairs"] == 6


def test_mixed_decimal_places_caught() -> None:
    """Extended-data-like precision mix: 5 integers / 3 one-decimal
    / 2 two-decimal values in one column."""
    values = ["4", "1", "1", "4", "5", "1.25", "1.75", "4.5", "1.5", "0.8"]
    table = _table(["score"], [[v] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "mixes decimal precision levels")
    evidence = _evidence(finding)
    assert evidence["check"] == "mixed_decimal_places"
    assert evidence["precision_counts"] == {"0": 5, "1": 3, "2": 2}
    assert finding.severity == "low"


def test_mixed_decimal_places_consistent_column_quiet() -> None:
    table = _table(
        ["v"],
        [[f"1.{i:02d}"] for i in range(12)],
    )

    result = TableRelationshipDetector().run(_doc(table))

    assert "mixed_decimal_places" not in _checks(result)


def test_duplicate_excess_excludes_boundary_ties() -> None:
    """Floor/ceiling clamping: many ties at the observed max (e.g.
    P-values rounded to 1.000) must not fire duplicate_excess."""
    values = ["1.000"] * 6 + ["0.012", "0.031", "0.045", "0.058", "0.071", "0.083", "0.094", "0.210"]
    table = _table(["v"], [[v] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    assert "duplicate_excess" not in _checks(result)


def test_duplicate_excess_skips_p_value_columns() -> None:
    values = ["0.050"] * 6 + ["0.012", "0.031", "0.045", "0.058", "0.071", "0.083", "0.094", "0.210"]
    table = _table(["P-values (group A vs B)"], [[v] for v in values])

    result = TableRelationshipDetector().run(_doc(table))

    assert "duplicate_excess" not in _checks(result)


def test_nonzero_clean_offset_is_high_when_n_solid() -> None:
    """s41586-style: A = B + fixed clean offset with n>=8 → high."""
    rows = [[str(1.0 + i * 0.1), str(1.3 + i * 0.1)] for i in range(10)]
    table = _table(["group_a", "group_b"], rows)

    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "fixed offset")
    assert finding.severity == "high"
    assert _evidence(finding)["offset"] == 0.3
    assert _evidence(finding)["match_fraction"] == 1.0


def test_partial_fixed_offset_when_most_rows_share_diff() -> None:
    """90%+ rows share one offset → partial_fixed_offset (not full copy)."""
    rows = []
    for i in range(9):
        rows.append([str(1.0 + i), str(1.1 + i)])  # offset +0.1
    rows.append(["99.0", "0.5"])  # one break

    table = _table(["ctrl", "treat"], rows)
    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "partial fixed offset")
    evidence = _evidence(finding)
    assert evidence["check"] == "partial_fixed_offset"
    assert evidence["matching_pairs"] == 9
    assert evidence["n"] == 10
    assert evidence["match_fraction"] >= 0.9
    assert evidence["offset"] == 0.1


def test_perfect_decimal_tails_high_when_n_ge_6() -> None:
    rows = [
        ["12.37", "18.37"],
        ["15.42", "21.42"],
        ["18.59", "24.59"],
        ["21.64", "27.64"],
        ["11.11", "19.11"],
        ["13.22", "20.22"],
    ]
    table = _table(["rep_a", "rep_b"], rows)
    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "matching decimal tails")
    assert finding.severity == "high"
    assert _evidence(finding)["matching_pairs"] == 6


def test_excel_fabrication_span_across_tables() -> None:
    """Multiple source-data tables with copy/offset → paper-level span."""
    t1 = _named_table(
        "t1",
        "Fig.5b",
        ["a", "b"],
        [[str(1.0 + i), str(1.0 + i)] for i in range(6)],
    )
    t2 = _named_table(
        "t2",
        "Fig.5f",
        ["a", "b"],
        [[str(2.0 + i), str(2.0 + i)] for i in range(6)],
    )
    t3 = _named_table(
        "t3",
        "Fig.5g",
        ["a", "b"],
        [[str(1.23 + i), str(1.23 + i + 1)] for i in range(6)],  # integer shift tails
    )

    result = TableRelationshipDetector().run(_doc(t1, t2, t3))
    span = _finding(result, "excel-style fabricated")
    evidence = _evidence(span)
    assert evidence["check"] == "excel_fabrication_span"
    assert evidence["table_count"] >= 2
    assert evidence["n"] >= 5


def test_identical_parallel_replicates_zero_scatter() -> None:
    """PubPeer: claimed independent replicates with identical numbers."""
    rows = [
        ["1.12", "1.12", "1.12", "2.0"],
        ["1.45", "1.45", "1.45", "2.1"],
        ["1.78", "1.78", "1.78", "2.2"],
        ["2.01", "2.01", "2.01", "2.3"],
    ]
    table = _table(["rep1", "rep2", "rep3", "mean_other"], rows)
    result = TableRelationshipDetector().run(_doc(table))

    finding = _finding(result, "identical parallel replicates")
    evidence = _evidence(finding)
    assert evidence["check"] == "identical_parallel_replicates"
    assert evidence["column_count"] >= 3
    assert evidence.get("pubpeer_pattern") == "source_data_zero_biological_variance"
    assert finding.severity == "high"


def test_sequence_reuse_across_tables() -> None:
    """PubPeer: same multi-cell paste block in another sheet/condition."""
    seq = ["1.11", "2.22", "3.33", "4.44", "5.55", "6.66"]
    t1 = _named_table(
        "t1",
        "Fig.1a",
        ["values"],
        [[v] for v in seq],
    )
    t2 = _named_table(
        "t2",
        "Fig.2b",
        ["other"],
        [[v] for v in (["9.9"] + seq + ["8.8"])],
    )
    result = TableRelationshipDetector().run(_doc(t1, t2))

    finding = _finding(result, "reuse the same")
    evidence = _evidence(finding)
    assert evidence["check"] == "sequence_reuse"
    assert evidence["window"] == 5
    assert evidence.get("pubpeer_pattern") == "source_data_block_paste"
    assert finding.severity == "high"


def test_fixed_ratio_between_columns() -> None:
    """Constant multiplicative fabrication A ≈ k·B."""
    rows = [[str(1.0 + i), str(2.0 * (1.0 + i))] for i in range(8)]
    table = _table(["a", "b"], rows)
    result = TableRelationshipDetector().run(_doc(table))
    finding = _finding(result, "fixed ratio")
    evidence = _evidence(finding)
    assert evidence["check"] == "fixed_ratio"
    assert abs(float(evidence["ratio"]) - 2.0) < 1e-6
    assert finding.severity == "high"
