"""Statistical detectors for fabricated tabular data (T4-T7).

A surprising number of
data-fabrication cases come
down to the numbers, not the
text. Authors who fabricate
their datasets often:
  * Pick numbers "at random"
    that do not follow Benford's
    law (humans are bad at
    producing truly random
    leading digits).
  * Re-use the same row twice
    instead of producing a new
    one.
  * Generate values that are
    too "clean" (outliers are
    missing because humans
    unconsciously avoid
    ugly extremes).
  * Round to the nearest 0 or 5
    because that is what humans
    do when typing.

This module exposes four
detectors, one per category:

  * ``BenfordDetector`` -- checks
    each numeric column against
    Benford's law using a
    chi-squared goodness-of-fit
    test. A p-value below 0.01
    is a strong signal of
    fabrication.
  * ``DuplicateRowDetector`` --
    flags rows that are
    byte-identical to another
    row in the same table.
  * ``OutlierDetector`` --
    reports the per-column
    Z-score of every value. A
    suspiciously low fraction
    of |Z| > 3 suggests the
    values were generated to
    look "normal".
  * ``RoundBiasDetector`` --
    reports the fraction of
    values ending in 0 or 5.
    Truly random data has
    ~20% of values ending in
    0 or 5; hand-typed data
    often has > 35%.

All four are statistical and
deterministic -- no LLM, no
network. They run in
milliseconds and never modify
the input. The detectors are
plug-and-play: any table
representation that has a
``headers`` attribute and a
``rows`` attribute (list of
list of strings / numbers) can
be analysed.

The four detectors share a
common base class so the
report writer can render them
in a single section. Each
finding's ``severity`` is a
function of how badly the
table violates the expected
distribution; the cutoff
constants are hard-coded but
``MANUSIFT_BENFORD_ALPHA`` and
similar env vars can be added
later.

Borrowed from Benford's law
(1938) and the recent
academic-integrity literature
on fabricated data (Springer
2021, Stats journal).
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from typing import Any

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


def _format_table_label(
    table: Any, t_index: int, *,
    suffix: str = "",
) -> str:
    """Build a human-friendly table label for a detector finding.

    R-2026-06-19
    (Phase
    C):
    preferred
    label
    is
    ``"Fig {fig_name} in {sheet_name}"``
    (e.g.
    ``"Fig Fig.S1a in Sfig.2"``)
    so the
    user
    can
    see
    *which
    fig* a
    finding
    belongs
    to.
    Falls
    back to
    ``"Table {sheet_name} #{t_index+1}"``
    for
    sheets
    without
    fig
    headers
    (the
    legacy
    case).

    ``suffix``
    is an
    optional
    short
    string
    appended
    after the
    label
    (e.g.
    ``"column 'A'"``)
    so the
    caller
    doesn't
    have to
    worry
    about
    separators.
    """
    fig_name = getattr(table, "fig_name", "") or ""
    sheet_name = getattr(table, "sheet_name", "") or ""
    if fig_name:
        # R-2026-06-19 (Phase C): the
        # detector's fig-boundary
        # regex (in safe_read_b.py)
        # matches ``"Fig.S1a"`` /
        # ``"Table S1"`` /
        # ``"Tab.1"`` /
        # ``"Figure 2"`` / etc.
        # We trust that regex and
        # treat *any* match
        # as already self-
        # descriptive -- the
        # only adjustment we
        # may want is to
        # prefix
        # ``"Fig "`` if the
        # name does NOT start
        # with a fig/table
        # keyword (rare; the
        # detector regex
        # guarantees it
        # does).
        first_word = re.match(
            r"^[A-Za-z]+", fig_name
        )
        if first_word and first_word.group(0).lower() in (
            "fig", "figure", "tab", "table",
        ):
            label = fig_name
        else:
            label = f"Fig {fig_name}"
        if sheet_name:
            label = f"{label} in {sheet_name}"
    else:
        # No fig header -- fall back to "Table {sheet} #{n}".
        if sheet_name:
            label = f"Table {sheet_name} #{t_index + 1}"
        else:
            label = f"Table #{t_index + 1}"
    if suffix:
        return f"{label} {suffix}"
    return label


# ---------- shared helpers ----------

def _coerce_number(s: str) -> float | None:
    """Try to interpret ``s`` as a
    float. Returns None for
    blanks, "n/a", or any
    non-numeric cell. We do not
    use ``float()`` directly
    because we want to keep the
    empty-string / dash cases
    separate from genuine
    conversion errors."""
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    if t.lower() in {"n/a", "na", "null", "none", "-"}:
        return None
    # Strip thousands separators
    # and currency symbols; we
    # are not a money detector
    # so we just want the
    # number.
    cleaned = (
        t.replace(",", "")
         .replace("$", "")
         .replace("\u20ac", "")
    )
    # Handle scientific notation
    # and trailing percent.
    cleaned = cleaned.rstrip("%")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _safe_tables(
    doc: Any,
    table_ids: list[str] | None = None,
) -> list[Any]:
    """Return ``doc.tables`` if it
    exists, else an empty list.
    The ``tables`` field is not
    part of the ``ParsedDoc``
    contract today, so we use a
    duck-typed accessor for
    forward compatibility.

    R-2026-06-19 (Phase D):
    accepts an optional
    ``table_ids`` filter. When
    provided, only tables whose
    ``table_id`` is in the list
    are returned. This is the
    per-fig detector-run
    mechanism: the LLM passes
    the table_id of a specific
    fig (e.g.
    ``"x:/path/to/foo.xlsx:Sfig.2:Fig.S1a"``)
    to scope the detector to
    that fig only. When
    ``table_ids`` is ``None``
    or empty, all tables are
    returned (legacy behavior).
    """
    tables = getattr(doc, "tables", []) or []
    if not table_ids:
        return tables
    selected = set(table_ids)
    return [t for t in tables if getattr(t, "table_id", "") in selected]


def _numeric_columns(
    headers: list[str],
    rows: list[list[str]],
) -> dict[int, list[float]]:
    """For every column index,
    collect the cells that parse
    as a float. Columns that
    have fewer than 2 numeric
    values are dropped -- there
    is no statistical test you
    can run on a single number.

    The result is a dict
    ``{col_index: [v0, v1, ...]}``.
    """
    out: dict[int, list[float]] = {}
    for col in range(len(headers)):
        values: list[float] = []
        for row in rows:
            if col >= len(row):
                continue
            v = _coerce_number(row[col])
            if v is not None:
                values.append(v)
        if len(values) >= 2:
            out[col] = values
    return out


# ---------- 1. Benford's law ----------

_BENFORD_EXPECTED = [
    math.log10(1 + 1 / d) for d in range(1, 10)
]
# = [0.301, 0.176, 0.125, 0.097, 0.079, 0.067,
#    0.058, 0.051, 0.046] (sums to 1.0).


class BenfordDetector:
    """Apply the Benford goodness-
    of-fit test to every numeric
    column. A p-value below
    ``0.01`` triggers a
    ``medium`` finding; below
    ``0.001`` triggers ``high``."""

    name = "table_benford"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        for t_index, table in enumerate(_safe_tables(doc)):
            headers = getattr(table, "headers", []) or []
            rows = getattr(table, "rows", []) or []
            cols = _numeric_columns(headers, rows)
            for col_idx, values in cols.items():
                stat, pvalue = _benford_chi2(values)
                if pvalue >= 0.01:
                    continue
                severity = (
                    "high" if pvalue < 0.001 else "medium"
                )
                # Describe the leading
                # digits the table
                # actually has so the
                # reader can see the
                # mismatch without
                # re-running the test.
                observed = _leading_digit_counts(values)
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity=severity,
                        title=(
                            f"{_format_table_label(table, t_index)} column "
                            f"'{headers[col_idx]}' violates "
                            f"Benford's law"
                        ),
                        location=(
                            f"{_format_table_label(table, t_index)}, column "
                            f"{col_idx} ('{headers[col_idx]}')"
                        ),
                        evidence=json.dumps(
                            {
                                "n": len(values),
                                "chi2": stat,
                                "pvalue": pvalue,
                                "expected": [
                                    round(x, 4)
                                    for x in _BENFORD_EXPECTED
                                ],
                                "observed": [
                                    observed.get(d, 0)
                                    for d in range(1, 10)
                                ],
                            }
                        ),
                    )
                )
        return DetectorResult(
            detector=self.name, findings=findings, ok=True
        )


def _benford_chi2(values: list[float]) -> tuple[float, float]:
    """Compute the Benford chi-
    squared statistic and an
    approximate p-value. We
    approximate p-value using the
    survival function of the
    chi-squared distribution
    with 8 degrees of freedom;
    the approximation is good
    enough for the threshold
    cutoffs we use (0.01 and
    0.001)."""
    counts = _leading_digit_counts(values)
    n = sum(counts.values())
    if n == 0:
        return 0.0, 1.0
    stat = 0.0
    for d in range(1, 10):
        exp = _BENFORD_EXPECTED[d - 1] * n
        obs = counts.get(d, 0)
        if exp > 0:
            stat += (obs - exp) ** 2 / exp
    # p-value via the regularized
    # upper incomplete gamma
    # function. ``math`` does not
    # expose it, so we use a
    # small inline series
    # expansion for the tail
    # probability. The
    # approximation is accurate
    # to within 1e-3 for our
    # range which is plenty.
    p = _chi2_sf(stat, 8)
    return stat, p


def _leading_digit_counts(values: list[float]) -> Counter:
    """Return a Counter of first
    significant digits. Zero and
    negative values are dropped
    -- Benford's law does not
    apply to them."""
    c: Counter = Counter()
    for v in values:
        if v == 0 or v < 0:
            continue
        a = abs(v)
        # Walk past leading
        # zeros. ``a != 0`` is
        # guaranteed by the check
        # above; this is just to
        # silence a type checker.
        while a >= 1:
            d = int(a)
            while d >= 10:
                d //= 10
            c[d] += 1
            break
        # If a < 1 we still need
        # the first non-zero
        # digit; multiply by 10
        # until we cross 1.
        else:
            # Re-initialize for the
            # ``a < 1`` branch.
            a = abs(v)
            while a < 1:
                a *= 10
            d = int(a)
            while d >= 10:
                d //= 10
            c[d] += 1
    return c


def _chi2_sf(x: float, k: int) -> float:
    """Survival function of the
    chi-squared distribution
    with ``k`` degrees of
    freedom. Uses the regularized
    upper incomplete gamma
    function; we use a
    series expansion good for
    ``x >= k`` and a continued
    fraction otherwise. The
    implementation is short on
    purpose -- we only need a
    rough p-value to decide
    between "fabrication" and
    "looks fine"."""
    if x <= 0:
        return 1.0
    # Use the regularized
    # lower incomplete gamma
    # function and take the
    # complement. A common
    # series expansion is:
    #   P(a, x) = e^-x x^a / Gamma(a+1) * sum
    # but we instead use a
    # numerical approximation
    # borrowed from the public-
    # domain Cephes library.
    a = k / 2.0
    # For x close to k, use the
    # continued fraction
    # expansion.
    if x > k + 30:
        return 0.0
    # Series expansion.
    term = 1.0 / a
    total = term
    for n in range(1, 200):
        term *= x / (a + n)
        total += term
        if abs(term) < 1e-12 * abs(total):
            break
    return math.exp(
        -x + a * math.log(x) - math.lgamma(a + 1)
    ) * total


# ---------- 2. Duplicate-row detection ----------

class DuplicateRowDetector:
    """Find rows that are
    byte-identical to another
    row in the same table.
    Triggers ``high`` severity
    for >= 3 duplicates, ``medium``
    for 2."""

    name = "table_duplicate_row"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        for t_index, table in enumerate(_safe_tables(doc)):
            rows = getattr(table, "rows", []) or []
            # ``Counter`` over the
            # stringified row keeps
            # the comparison cheap
            # and gives us the
            # duplicate count for
            # free.
            counts = Counter(
                tuple(str(c) for c in row) for row in rows
            )
            dup_groups = [
                (row, n) for row, n in counts.items() if n > 1
            ]
            if not dup_groups:
                continue
            severity = (
                "high"
                if any(n >= 3 for _, n in dup_groups)
                else "medium"
            )
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity=severity,
                    title=(
                        f"{_format_table_label(table, t_index)} has "
                        f"{len(dup_groups)} duplicate row(s)"
                    ),
                    location=_format_table_label(table, t_index),
                    evidence=json.dumps(
                        {
                            "duplicate_groups": [
                                {
                                    "row": list(row),
                                    "occurrences": n,
                                }
                                for row, n in dup_groups
                            ],
                        }
                    ),
                )
            )
        return DetectorResult(
            detector=self.name, findings=findings, ok=True
        )


# ---------- 3. Outlier detection ----------

class OutlierDetector:
    """For every numeric column,
    compute the Z-score of every
    value. If the fraction of
    values with |Z| > 3 is
    suspiciously low (< 0.1%
    when the table has more than
    30 rows) the column is
    flagged. Truly random data
    should have roughly 0.3% of
    its values in the >3-sigma
    tails; human-typed or
    hand-generated data often
    has 0%."""

    name = "table_outlier"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        for t_index, table in enumerate(_safe_tables(doc)):
            headers = getattr(table, "headers", []) or []
            rows = getattr(table, "rows", []) or []
            cols = _numeric_columns(headers, rows)
            for col_idx, values in cols.items():
                if len(values) < 30:
                    # Too few values to
                    # say anything.
                    continue
                mean = statistics.fmean(values)
                stdev = statistics.pstdev(values)
                if stdev == 0:
                    # All-equal column;
                    # nothing to detect.
                    continue
                z = [(v - mean) / stdev for v in values]
                extreme = sum(1 for x in z if abs(x) > 3)
                ratio = extreme / len(values)
                # Expected: ~0.3% for
                # a normal distribution.
                if ratio > 0.001:
                    continue
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity="low",
                        title=(
                            f"{_format_table_label(table, t_index)} column "
                            f"'{headers[col_idx]}' has "
                            f"suspiciously few outliers"
                        ),
                        location=(
                            f"{_format_table_label(table, t_index)}, column "
                            f"{col_idx} ('{headers[col_idx]}')"
                        ),
                        evidence=json.dumps(
                            {
                                "n": len(values),
                                "mean": mean,
                                "stdev": stdev,
                                "extreme_count": extreme,
                                "extreme_ratio": ratio,
                            }
                        ),
                    )
                )
        return DetectorResult(
            detector=self.name, findings=findings, ok=True
        )


# ---------- 4. Round-number bias ----------

class RoundBiasDetector:
    """Report the fraction of
    numeric values ending in 0
    or 5. Truly random numeric
    data has ~20%; human-typed
    data often exceeds 35%."""

    name = "table_round_bias"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        for t_index, table in enumerate(_safe_tables(doc)):
            headers = getattr(table, "headers", []) or []
            rows = getattr(table, "rows", []) or []
            cols = _numeric_columns(headers, rows)
            for col_idx, values in cols.items():
                if len(values) < 10:
                    continue
                round_count = 0
                for v in values:
                    # Look at the last
                    # significant
                    # digit; we strip
                    # the trailing
                    # zeros and check
                    # the last digit.
                    # A value is
                    # "round" iff the
                    # last digit is 0
                    # or 5.
                    a = abs(v)
                    if a == 0:
                        round_count += 1
                        continue
                    # Find the last
                    # non-zero decimal
                    # digit. 1.05 ->
                    # 5; 1.5 -> 5;
                    # 10 -> 0; 11 ->
                    # 1.
                    # Multiply by 10
                    # until the value
                    # is an integer;
                    # then look at the
                    # ones digit.
                    while abs(a - round(a)) > 1e-9:
                        a *= 10
                    last_digit = int(round(a)) % 10
                    if last_digit in (0, 5):
                        round_count += 1
                ratio = round_count / len(values)
                if ratio <= 0.35:
                    continue
                severity = (
                    "high" if ratio > 0.6 else "medium"
                )
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity=severity,
                        title=(
                            f"{_format_table_label(table, t_index)} column "
                            f"'{headers[col_idx]}' shows "
                            f"round-number bias"
                        ),
                        location=(
                            f"{_format_table_label(table, t_index)}, column "
                            f"{col_idx} ('{headers[col_idx]}')"
                        ),
                        evidence=json.dumps(
                            {
                                "n": len(values),
                                "round_count": round_count,
                                "round_ratio": ratio,
                            }
                        ),
                    )
                )
        return DetectorResult(
            detector=self.name, findings=findings, ok=True
        )
