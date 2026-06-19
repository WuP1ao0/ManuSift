"""Figure-text vs. table cross-check (P2.5).

A common fraud signal is
that the *prose* of the
paper claims one value
("60% of patients
recovered") while the
*table* shows a different
value (58% or 65%). The
detector pulls every
percentage-like number
from the prose and the
table column, then matches
them by rounding to the
nearest 1%.

The detector does not
attempt to *align* prose
to table cells by name --
that would require a
proper table-parse +
semantic-matching
pipeline. The detector
*only* checks that the
distribution of
percentages in the prose
is consistent with the
distribution in the
table. If the prose
mentions "60%" three
times but the table has
no values around 60%, the
detector flags the
disagreement.

The detector is read-only
and uses a small list of
heuristics. It is not a
substitute for a human
reviewer; it surfaces
*likely* discrepancies so
the reviewer can
investigate.

Borrowed from the
``statcheck`` R package's
table-text cross-check.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# Regexes for percentage
# values in text. The
# first matches plain
# ``60%``; the second
# matches the spelled-out
# form ``60 percent``.
_PCT_TEXT = re.compile(
    r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)"
)


def _extract_pcts_from_text(text: str) -> list[float]:
    """Return the list of
    percentage values in
    the prose (in [0, 100]
    only)."""
    out: list[float] = []
    for m in _PCT_TEXT.finditer(text):
        try:
            v = float(m.group(1))
        except (TypeError, ValueError):
            continue
        if 0 <= v <= 100:
            out.append(v)
    return out


def _extract_pcts_from_tables(
    tables: list[Any],
) -> list[float]:
    """Return the list of
    percentage values in
    every table cell. A
    cell is counted as a
    percentage if its header
    contains "%" or "percent"
    OR if the value lies in
    [0, 100] AND the column
    header suggests a
    proportion."""
    out: list[float] = []
    for table in tables:
        headers = getattr(table, "headers", [])
        rows = getattr(table, "rows", [])
        for c_idx, header in enumerate(headers):
            h = (header or "").lower()
            header_says_pct = (
                "%" in header
                or "percent" in h
            )
            for row in rows:
                if c_idx >= len(row):
                    continue
                cell = str(row[c_idx]).strip()
                # Strip a trailing
                # "%" if present.
                cell = cell.rstrip("%").strip()
                try:
                    v = float(cell)
                except (TypeError, ValueError):
                    continue
                if 0 <= v <= 100:
                    if header_says_pct:
                        out.append(v)
                    elif 0 <= v <= 1.0:
                        # Treat as a
                        # 0-1 proportion
                        # and convert.
                        out.append(v * 100.0)
                    else:
                        # Header is
                        # unknown; the
                        # value is in
                        # [1, 100] which
                        # is consistent
                        # with a
                        # percentage --
                        # accept.
                        out.append(v)
    return out


def _round_to(v: float, step: float) -> int:
    """Round a value to the
    nearest ``step`` and
    return the integer
    bucket."""
    return int(round(v / step)) * int(step)


class FigureTextCrossCheckDetector:
    """Check that the
    distribution of
    percentages in the
    prose matches the
    distribution in the
    tables."""

    name = "figure_table_consistency"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        text = " ".join(
            getattr(b, "text", "") for b in doc.text_blocks
        )
        tables = getattr(doc, "tables", []) or []
        text_pcts = _extract_pcts_from_text(text)
        table_pcts = _extract_pcts_from_tables(tables)
        if not text_pcts or not table_pcts:
            # Without both
            # numbers we cannot
            # compare. The
            # detector is silent.
            return DetectorResult(
                detector=self.name, findings=[], ok=True
            )
        # Round each
        # percentage to the
        # nearest 1% and
        # compare the
        # distributions.
        text_buckets = Counter(
            _round_to(v, 1) for v in text_pcts
        )
        table_buckets = Counter(
            _round_to(v, 1) for v in table_pcts
        )
        # Find the top 3
        # text values. If
        # none of them
        # appear in the
        # table, flag.
        common: list[int] = []
        for bucket, _ in text_buckets.most_common(5):
            if table_buckets.get(bucket, 0) > 0:
                common.append(bucket)
        if len(common) >= max(1, len(text_pcts) // 5):
            return DetectorResult(
                detector=self.name, findings=[], ok=True
            )
        # No overlap at all
        # between the top
        # text percentages
        # and the table
        # percentages.
        finding = Finding.make(
            trace_id=doc.trace_id,
            detector=self.name,
            severity="medium",
            title=(
                "Prose percentages and table "
                "percentages disagree"
            ),
            location="text vs tables",
            evidence=json.dumps(
                {
                    "text_pcts": text_pcts,
                    "text_buckets": dict(text_buckets),
                    "table_buckets": dict(table_buckets),
                    "common_buckets": common,
                }
            ),
        )
        return DetectorResult(
            detector=self.name,
            findings=[finding],
            ok=True,
        )
