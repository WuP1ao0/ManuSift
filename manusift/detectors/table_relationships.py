"""Relationship checks for suspicious tabular data patterns.

These checks are screening signals, not misconduct findings. They point a
reviewer to table relationships that are unusually exact for independent
experimental data: copied columns, fixed offsets, mirror symmetry, repeated
decimal tails, integer-shift decimal-tail reuse, concentrated one- or two-digit
terminal patterns within and across tables, high duplicate rates, improbable
repeated values, three-column arithmetic identities, and zero-variance columns.
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult
from .table_stats import _format_table_label, _safe_tables

MIN_COLUMN_VALUES = 4
MIN_DIGIT_VALUES = 6
MIN_DUPLICATE_FRACTION = 0.75
MIN_PAIR_DIGIT_FRACTION = 0.9


def _decimal_cell(cell: Any) -> Decimal | None:
    text = str(cell).strip()
    if not text:
        return None
    try:
        return Decimal(text.replace(",", "").rstrip("%"))
    except InvalidOperation:
        return None


def _numeric_columns(table: Any) -> dict[int, list[Decimal]]:
    headers = getattr(table, "headers", []) or []
    rows = getattr(table, "rows", []) or []
    out: dict[int, list[Decimal]] = {}
    for col in range(len(headers)):
        values: list[Decimal] = []
        for row in rows:
            if col >= len(row):
                continue
            value = _decimal_cell(row[col])
            if value is not None:
                values.append(value)
        if len(values) >= MIN_COLUMN_VALUES:
            out[col] = values
    return out


def _cell_texts(table: Any, col: int) -> list[str]:
    rows = getattr(table, "rows", []) or []
    out: list[str] = []
    for row in rows:
        if col < len(row):
            text = str(row[col]).strip()
            if text:
                out.append(text)
    return out


def _decimal_tail(text: str, places: int = 2) -> str | None:
    if "." not in text:
        return None
    tail = text.split(".", 1)[1]
    if len(tail) < places:
        return None
    return tail[:places]


def _integer_digit_changes(left: str, right: str) -> int | None:
    left_digits = [c for c in left.split(".", 1)[0] if c.isdigit()]
    right_digits = [c for c in right.split(".", 1)[0] if c.isdigit()]
    # ponytail: equal-length integer-part heuristic; upgrade path is a
    # Levenshtein-style digit edit distance if source data show inserted
    # or deleted integer digits with copied decimal tails.
    if not left_digits or len(left_digits) != len(right_digits):
        return None
    return sum(a != b for a, b in zip(left_digits, right_digits))


def _terminal_digit(text: str) -> str | None:
    for char in reversed(text.strip()):
        if char.isdigit():
            return char
    return None


def _ones_matches_first_decimal(text: str) -> bool:
    if "." not in text:
        return False
    left, right = text.split(".", 1)
    left_digits = [c for c in left if c.isdigit()]
    right_digits = [c for c in right if c.isdigit()]
    return bool(left_digits and right_digits and left_digits[-1] == right_digits[0])


def _round_decimal(value: Decimal, places: str = "0.000001") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _is_variability_header(header: str) -> bool:
    # ponytail: header-name heuristic; upgrade path is a configurable
    # variability-column vocabulary from labeled manuscript tables.
    normalized = "".join(char.lower() if char.isalnum() else " " for char in header)
    tokens = set(normalized.split())
    compact = "".join(normalized.split())
    return bool(tokens & {"sd", "std", "stdev", "sem"} or "standarddeviation" in compact)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        as_int = int(value)
        if value == as_int:
            return as_int
        return float(value)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    return value


def _as_json(payload: dict[str, Any]) -> str:
    return json.dumps(_json_ready(payload), ensure_ascii=False)


class TableRelationshipDetector:
    """Flag exact arithmetic relationships across manuscript data tables."""

    name = "table_relationships"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        tables = _safe_tables(doc)
        for t_index, table in enumerate(tables):
            headers = getattr(table, "headers", []) or []
            cols = _numeric_columns(table)
            label = _format_table_label(table, t_index)
            findings.extend(self._column_findings(doc, table, t_index, label, headers, cols))
            findings.extend(self._pair_findings(doc, table, t_index, label, headers, cols))
            findings.extend(self._multi_column_findings(doc, label, headers, cols))
            findings.extend(self._triple_findings(doc, label, headers, cols))
        findings.extend(self._cross_table_findings(doc, tables))
        findings.extend(self._cross_table_terminal_digit_findings(doc, tables))
        return DetectorResult(detector=self.name, findings=findings, ok=True)

    def _column_findings(
        self,
        doc: ParsedDoc,
        table: Any,
        t_index: int,
        label: str,
        headers: list[str],
        cols: dict[int, list[Decimal]],
    ) -> list[Finding]:
        findings: list[Finding] = []
        for col, values in cols.items():
            header = headers[col] if col < len(headers) else f"col_{col + 1}"
            if _is_variability_header(header):
                zero_rows = [row_index + 1 for row_index, value in enumerate(values) if value == 0]
                if zero_rows:
                    findings.append(
                        self._finding(
                            doc,
                            "high",
                            f"{label} column '{header}' contains zero standard deviation entries",
                            f"{label}, column {col + 1} ('{header}')",
                            {
                                "check": "zero_standard_deviation_entries",
                                "n": len(values),
                                "column": header,
                                "zero_count": len(zero_rows),
                                "rows": zero_rows,
                            },
                        )
                    )
                if len(set(values)) == 1 and values[0] != 0:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} column '{header}' has constant standard deviation",
                            f"{label}, column {col + 1} ('{header}')",
                            {
                                "check": "constant_standard_deviation",
                                "n": len(values),
                                "column": header,
                                "value": values[0],
                            },
                        )
                    )
            if len(set(values)) == 1:
                findings.append(
                    self._finding(
                        doc,
                        "medium",
                        f"{label} column '{header}' has zero variance",
                        f"{label}, column {col + 1} ('{header}')",
                        {"check": "zero_variance", "n": len(values), "value": values[0]},
                    )
                )
            else:
                value, count = Counter(values).most_common(1)[0]
                if count / len(values) >= MIN_DUPLICATE_FRACTION:
                    findings.append(
                        self._finding(
                            doc,
                            "high",
                            f"{label} column '{header}' has improbable repeated values",
                            f"{label}, column {col + 1} ('{header}')",
                            {
                                "check": "improbable_repeated_values",
                                "n": len(values),
                                "repeated_value": value,
                                "repeat_count": count,
                            },
                        )
                    )

            if len(values) >= 6:
                diffs = [_round_decimal(values[i + 1] - values[i]) for i in range(len(values) - 1)]
                if len(set(diffs)) == 1 and diffs[0] != 0:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} column '{header}' forms an arithmetic progression",
                            f"{label}, column {col + 1} ('{header}')",
                            {"check": "arithmetic_progression", "n": len(values), "step": diffs[0]},
                        )
                    )
                else:
                    step, matching = Counter(diffs).most_common(1)[0]
                    # ponytail: one-mode-diff heuristic; upgrade path is a
                    # calibrated residual model if labeled table cases show
                    # too many near-linear experimental series.
                    if step != 0 and matching / len(diffs) >= 0.8:
                        findings.append(
                            self._finding(
                                doc,
                                "medium",
                                (
                                    f"{label} column '{header}' forms a "
                                    "near-perfect arithmetic progression"
                                ),
                                f"{label}, column {col + 1} ('{header}')",
                                {
                                    "check": "near_perfect_arithmetic_progression",
                                    "n": len(values),
                                    "step": step,
                                    "matching_diffs": matching,
                                    "total_diffs": len(diffs),
                                },
                            )
                        )

            texts = _cell_texts(table, col)
            digit_counts = Counter(d for d in (_terminal_digit(t) for t in texts) if d is not None)
            total_digits = sum(digit_counts.values())
            if total_digits >= MIN_DIGIT_VALUES:
                digit, count = digit_counts.most_common(1)[0]
                if count / total_digits >= 0.75:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} column '{header}' shows terminal digit concentration",
                            f"{label}, column {col + 1} ('{header}')",
                            {
                                "check": "terminal_digit_concentration",
                                "n": total_digits,
                                "top_digits": [[digit, count]],
                            },
                        )
                    )
                elif len(digit_counts) >= 2:
                    top_two = digit_counts.most_common(2)
                    combined = sum(count for _, count in top_two)
                    if combined / total_digits >= MIN_PAIR_DIGIT_FRACTION:
                        findings.append(
                            self._finding(
                                doc,
                                "medium",
                                f"{label} column '{header}' shows terminal digit pair concentration",
                                f"{label}, column {col + 1} ('{header}')",
                                {
                                    "check": "terminal_digit_pair_concentration",
                                    "n": total_digits,
                                    "top_digits": [[digit, count] for digit, count in top_two],
                                    "combined_fraction": combined / total_digits,
                                },
                            )
                        )
                matches = sum(1 for text in texts if _ones_matches_first_decimal(text))
                if matches >= MIN_DIGIT_VALUES and matches / len(texts) >= 0.75:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} column '{header}' ones digit mirrors first decimal digit",
                            f"{label}, column {col + 1} ('{header}')",
                            {
                                "check": "ones_decimal_mirror",
                                "n": len(texts),
                                "matches": matches,
                            },
                        )
                    )
        return findings

    def _pair_findings(
        self,
        doc: ParsedDoc,
        table: Any,
        t_index: int,
        label: str,
        headers: list[str],
        cols: dict[int, list[Decimal]],
    ) -> list[Finding]:
        findings: list[Finding] = []
        items = sorted(cols.items())
        for left_i, (left_col, left_values) in enumerate(items):
            for right_col, right_values in items[left_i + 1 :]:
                n = min(len(left_values), len(right_values))
                if n < MIN_COLUMN_VALUES:
                    continue
                left = left_values[:n]
                right = right_values[:n]
                left_header = headers[left_col] if left_col < len(headers) else f"col_{left_col + 1}"
                right_header = headers[right_col] if right_col < len(headers) else f"col_{right_col + 1}"
                diffs = [_round_decimal(right[i] - left[i]) for i in range(n)]
                if len(set(diffs)) == 1:
                    findings.append(
                        self._finding(
                            doc,
                            "high" if diffs[0] == 0 else "medium",
                            f"{label} columns '{left_header}' and '{right_header}' have a fixed offset",
                            f"{label}, columns {left_col + 1} and {right_col + 1}",
                            {
                                "check": "fixed_offset",
                                "n": n,
                                "left_column": left_header,
                                "right_column": right_header,
                                "offset": diffs[0],
                            },
                        )
                    )

                exact = sum(1 for i in range(n) if left[i] == right[i])
                if n > exact >= MIN_COLUMN_VALUES and exact / n >= MIN_DUPLICATE_FRACTION:
                    findings.append(
                        self._finding(
                            doc,
                            "high",
                            f"{label} columns '{left_header}' and '{right_header}' have a high duplicate rate",
                            f"{label}, columns {left_col + 1} and {right_col + 1}",
                            {
                                "check": "high_duplicate_rate",
                                "n": n,
                                "matching_pairs": exact,
                                "left_column": left_header,
                                "right_column": right_header,
                            },
                        )
                    )

                sums = [_round_decimal(right[i] + left[i]) for i in range(n)]
                if len(set(sums)) == 1:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} columns '{left_header}' and '{right_header}' are mirror-symmetric",
                            f"{label}, columns {left_col + 1} and {right_col + 1}",
                            {
                                "check": "mirror_symmetry",
                                "n": n,
                                "left_column": left_header,
                                "right_column": right_header,
                                "sum": sums[0],
                            },
                        )
                    )

                left_tails = [_decimal_tail(t) for t in _cell_texts(table, left_col)]
                right_tails = [_decimal_tail(t) for t in _cell_texts(table, right_col)]
                left_texts = _cell_texts(table, left_col)
                right_texts = _cell_texts(table, right_col)
                tail_pairs = [
                    (a, b) for a, b in zip(left_tails, right_tails) if a is not None and b is not None
                ]
                matching = sum(1 for a, b in tail_pairs if a == b)
                if len(tail_pairs) >= MIN_COLUMN_VALUES and matching / len(tail_pairs) >= 0.75:
                    findings.append(
                        self._finding(
                            doc,
                            "medium",
                            f"{label} columns '{left_header}' and '{right_header}' have matching decimal tails",
                            f"{label}, columns {left_col + 1} and {right_col + 1}",
                            {
                                "check": "matching_decimal_tails",
                                "n": len(tail_pairs),
                                "matching_pairs": matching,
                            },
                        )
                    )
                    integer_offset = diffs[0]
                    if (
                        matching == len(tail_pairs)
                        and len(set(diffs)) == 1
                        and integer_offset == integer_offset.to_integral_value()
                        and 0 < abs(integer_offset) <= 9
                    ):
                        findings.append(
                            self._finding(
                                doc,
                                "medium",
                                (
                                    f"{label} columns '{left_header}' and '{right_header}' "
                                    "show integer-shift decimal-tail reuse"
                                ),
                                f"{label}, columns {left_col + 1} and {right_col + 1}",
                                {
                                    "check": "integer_shift_decimal_tail_reuse",
                                    "n": len(tail_pairs),
                                    "matching_pairs": matching,
                                    "left_column": left_header,
                                    "right_column": right_header,
                                    "integer_offset": integer_offset,
                                    "decimal_places": 2,
                                },
                            )
                        )
                    digit_changes = [
                        _integer_digit_changes(a, b)
                        for a, b in zip(left_texts, right_texts)
                    ]
                    if (
                        matching == len(tail_pairs)
                        and digit_changes
                        and all(change == 1 for change in digit_changes)
                    ):
                        findings.append(
                            self._finding(
                                doc,
                                "medium",
                                (
                                    f"{label} columns '{left_header}' and '{right_header}' "
                                    "show integer-part digit-change decimal-tail reuse"
                                ),
                                f"{label}, columns {left_col + 1} and {right_col + 1}",
                                {
                                    "check": "integer_part_digit_change_decimal_tail_reuse",
                                    "n": len(tail_pairs),
                                    "matching_pairs": matching,
                                    "left_column": left_header,
                                    "right_column": right_header,
                                    "changed_integer_digits": 1,
                                    "decimal_places": 2,
                                },
                            )
                        )
        return findings

    def _multi_column_findings(
        self,
        doc: ParsedDoc,
        label: str,
        headers: list[str],
        cols: dict[int, list[Decimal]],
    ) -> list[Finding]:
        findings: list[Finding] = []
        items = sorted(cols.items())
        # ponytail: cubic scan over manuscript table columns; upgrade path is
        # connected-component clustering if source-data workbooks show dozens
        # of numeric columns where this becomes noisy or slow.
        for left_i, (a_col, a_values) in enumerate(items):
            for right_i in range(left_i + 1, len(items)):
                b_col, b_values = items[right_i]
                for c_col, c_values in items[right_i + 1 :]:
                    n = min(len(a_values), len(b_values), len(c_values))
                    if n < MIN_COLUMN_VALUES:
                        continue
                    matching = sum(
                        1
                        for i in range(n)
                        if a_values[i] == b_values[i] == c_values[i]
                    )
                    if matching / n < MIN_DUPLICATE_FRACTION:
                        continue
                    col_indices = [a_col, b_col, c_col]
                    col_names = [
                        headers[col] if col < len(headers) else f"col_{col + 1}"
                        for col in col_indices
                    ]
                    findings.append(
                        self._finding(
                            doc,
                            "high",
                            f"{label} columns {col_names} show multi-column high duplicate rate",
                            f"{label}, columns {a_col + 1}, {b_col + 1}, {c_col + 1}",
                            {
                                "check": "multi_column_high_duplicate_rate",
                                "n": n,
                                "matching_rows": matching,
                                "columns": col_names,
                            },
                        )
                    )
        return findings

    def _triple_findings(
        self,
        doc: ParsedDoc,
        label: str,
        headers: list[str],
        cols: dict[int, list[Decimal]],
    ) -> list[Finding]:
        findings: list[Finding] = []
        items = sorted(cols.items())
        for a_i, (a_col, a_values) in enumerate(items):
            for b_i, (b_col, b_values) in enumerate(items):
                if b_i == a_i:
                    continue
                for c_col, c_values in items:
                    if c_col in {a_col, b_col}:
                        continue
                    n = min(len(a_values), len(b_values), len(c_values))
                    if n < MIN_COLUMN_VALUES:
                        continue
                    a_header = headers[a_col] if a_col < len(headers) else f"col_{a_col + 1}"
                    b_header = headers[b_col] if b_col < len(headers) else f"col_{b_col + 1}"
                    c_header = headers[c_col] if c_col < len(headers) else f"col_{c_col + 1}"
                    additive = all(
                        _round_decimal(a_values[i] + b_values[i]) == c_values[i]
                        for i in range(n)
                    )
                    if additive:
                        findings.append(
                            self._finding(
                                doc,
                                "high",
                                (
                                    f"{label} columns '{a_header}', '{b_header}', "
                                    f"and '{c_header}' show an additive relationship"
                                ),
                                f"{label}, columns {a_col + 1}, {b_col + 1}, {c_col + 1}",
                                {
                                    "check": "three_column_additive_relationship",
                                    "n": n,
                                    "formula": f"{a_header} + {b_header} = {c_header}",
                                    "left_column": a_header,
                                    "right_column": b_header,
                                    "result_column": c_header,
                                },
                            )
                        )
                    subtractive = all(
                        _round_decimal(a_values[i] - b_values[i]) == c_values[i]
                        for i in range(n)
                    )
                    if subtractive:
                        findings.append(
                            self._finding(
                                doc,
                                "high",
                                (
                                    f"{label} columns '{a_header}', '{b_header}', "
                                    f"and '{c_header}' show a subtractive relationship"
                                ),
                                f"{label}, columns {a_col + 1}, {b_col + 1}, {c_col + 1}",
                                {
                                    "check": "three_column_subtractive_relationship",
                                    "n": n,
                                    "formula": f"{a_header} - {b_header} = {c_header}",
                                    "left_column": a_header,
                                    "right_column": b_header,
                                    "result_column": c_header,
                                },
                            )
                        )
        return findings

    def _cross_table_findings(
        self,
        doc: ParsedDoc,
        tables: list[Any],
    ) -> list[Finding]:
        findings: list[Finding] = []
        prepared: list[tuple[int, Any, str, list[str], dict[int, list[Decimal]]]] = []
        for t_index, table in enumerate(tables):
            cols = _numeric_columns(table)
            if cols:
                prepared.append(
                    (
                        t_index,
                        table,
                        _format_table_label(table, t_index),
                        getattr(table, "headers", []) or [],
                        cols,
                    )
                )
        for left_i, (left_idx, left_table, left_label, left_headers, left_cols) in enumerate(prepared):
            for right_idx, right_table, right_label, right_headers, right_cols in prepared[left_i + 1 :]:
                for left_col, left_values in left_cols.items():
                    for right_col, right_values in right_cols.items():
                        n = min(len(left_values), len(right_values))
                        if n < MIN_COLUMN_VALUES:
                            continue
                        left_header = (
                            left_headers[left_col]
                            if left_col < len(left_headers)
                            else f"col_{left_col + 1}"
                        )
                        right_header = (
                            right_headers[right_col]
                            if right_col < len(right_headers)
                            else f"col_{right_col + 1}"
                        )
                        exact = sum(
                            1
                            for i in range(n)
                            if left_values[i] == right_values[i]
                        )
                        diffs = [
                            _round_decimal(right_values[i] - left_values[i])
                            for i in range(n)
                        ]
                        if len(set(diffs)) == 1:
                            findings.append(
                                self._finding(
                                    doc,
                                    "high" if diffs[0] == 0 else "medium",
                                    (
                                        f"{left_label} and {right_label} "
                                        "show cross-table fixed offset"
                                    ),
                                    (
                                        f"{left_label}, column {left_col + 1} "
                                        f"to {right_label}, column {right_col + 1}"
                                    ),
                                    {
                                        "check": "cross_table_fixed_offset",
                                        "n": n,
                                        "offset": diffs[0],
                                        "left_table": left_label,
                                        "right_table": right_label,
                                        "left_column": left_header,
                                        "right_column": right_header,
                                    },
                                )
                            )
                        if exact / n >= 0.75:
                            findings.append(
                                self._finding(
                                    doc,
                                    "high",
                                    (
                                        f"{left_label} and {right_label} "
                                        "show cross-table repeated values"
                                    ),
                                    (
                                        f"{left_label}, column {left_col + 1} "
                                        f"to {right_label}, column {right_col + 1}"
                                    ),
                                    {
                                        "check": "cross_table_repeated_values",
                                        "n": n,
                                        "matching_pairs": exact,
                                        "left_table": left_label,
                                        "right_table": right_label,
                                        "left_column": left_header,
                                        "right_column": right_header,
                                    },
                                )
                            )

                        left_tails = [_decimal_tail(t) for t in _cell_texts(left_table, left_col)]
                        right_tails = [_decimal_tail(t) for t in _cell_texts(right_table, right_col)]
                        tail_pairs = [
                            (a, b)
                            for a, b in zip(left_tails, right_tails)
                            if a is not None and b is not None
                        ]
                        matching = sum(1 for a, b in tail_pairs if a == b)
                        if len(tail_pairs) >= MIN_COLUMN_VALUES and matching / len(tail_pairs) >= 0.75:
                            findings.append(
                                self._finding(
                                    doc,
                                    "medium",
                                    (
                                        f"{left_label} and {right_label} "
                                        "show cross-table matching decimal tails"
                                    ),
                                    (
                                        f"{left_label}, column {left_col + 1} "
                                        f"to {right_label}, column {right_col + 1}"
                                    ),
                                    {
                                        "check": "cross_table_matching_decimal_tails",
                                        "n": len(tail_pairs),
                                        "matching_pairs": matching,
                                        "left_table": left_label,
                                        "right_table": right_label,
                                        "left_column": left_header,
                                        "right_column": right_header,
                                    },
                                )
                            )
        return findings

    def _cross_table_terminal_digit_findings(
        self,
        doc: ParsedDoc,
        tables: list[Any],
    ) -> list[Finding]:
        labels: list[str] = []
        digit_counts: Counter[str] = Counter()
        for t_index, table in enumerate(tables):
            table_has_digits = False
            for col in _numeric_columns(table):
                for text in _cell_texts(table, col):
                    if _decimal_cell(text) is None:
                        continue
                    digit = _terminal_digit(text)
                    if digit is None:
                        continue
                    digit_counts[digit] += 1
                    table_has_digits = True
            if table_has_digits:
                labels.append(_format_table_label(table, t_index))

        total_digits = sum(digit_counts.values())
        if len(labels) < 2 or total_digits < MIN_DIGIT_VALUES:
            return []

        top_digits = digit_counts.most_common(2)
        combined = sum(count for _, count in top_digits)
        threshold = 0.75 if len(top_digits) == 1 else MIN_PAIR_DIGIT_FRACTION
        if combined / total_digits < threshold:
            return []

        return [
            self._finding(
                doc,
                "medium",
                "Cross-table terminal digit concentration across source tables",
                ", ".join(labels),
                {
                    "check": "cross_table_terminal_digit_concentration",
                    "n": total_digits,
                    "top_digits": [[digit, count] for digit, count in top_digits],
                    "combined_fraction": combined / total_digits,
                    "tables": labels,
                },
            )
        ]

    def _finding(
        self,
        doc: ParsedDoc,
        severity: str,
        title: str,
        location: str,
        evidence: dict[str, Any],
    ) -> Finding:
        # ponytail: deterministic heuristics only; upgrade path is calibrated
        # per-domain thresholds once ManuSift has labeled table-forensics cases.
        return Finding.make(
            trace_id=doc.trace_id,
            detector=self.name,
            severity=severity,  # type: ignore[arg-type]
            title=title,
            location=location,
            evidence=_as_json(evidence),
            raw=_json_ready(evidence),
        )
