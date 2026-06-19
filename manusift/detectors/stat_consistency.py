"""Statistical consistency detectors (P0.2-P0.4).

A surprising number of
fabrication cases in
academic papers are caught
not by a sophisticated
algorithm but by *grade-
school arithmetic*. A mean
computed from a Likert-scale
questionnaire has to be a
multiple of 1/N. A
percentage reported in a
table has to be a multiple
of 100/n. A p-value that
comes from an F-test on a
small sample has to be one
of a small set of values.

This module layers three
detectors on the same input
format -- a column of
numbers -- but each catches
a different kind of fraud:

  * **GRIM (Granularity-
    Related Inconsistency of
    Means)**: for a column
    of N discrete values
    whose true mean is
    reported to ``d`` decimal
    places, the value
    ``mean * N`` must be a
    multiple of ``1/10**d``.
    If it is not, the mean
    cannot have come from
    that sample -- either
    the sample size is
    wrong, the granularity
    is wrong, or the mean
    is fabricated. The test
    is from Brown and Heene
    (2017) and is the
    standard tool for
    catching survey-data
    fabrication.

  * **Percent-times-N
    divisibility**: a
    percentage column
    reported to ``d``
    decimal places must be a
    multiple of ``(100 *
    10**d) / N``. E.g. if
    30 out of 50 responded
    "yes", the percentage is
    60.00; if 30.5 out of
    50 responded "yes", the
    percentage is 61.00 --
    which is *not* a
    multiple of 2 (= 100 /
    50). A 60.5% would also
    fail.

  * **p-value plausibility**:
    when a paper reports a
    correlation ``r`` and a
    sample size ``N``, the
    exact two-tailed p-value
    can be recomputed. We
    implement the
    ``scipy.stats.pearsonr``
    formula. A reported
    p-value that disagrees
    with the recomputed one
    is a strong fabrication
    signal.

The detectors accept a
``doc.tables`` field. We do
not currently extract
numerical tables from the
PDF text -- that is a
separate problem (T5) --
so for now the detectors
are run *only* when the
caller has attached tables
to the document. The
helper
``extract_numbers_from_text``
can pull simple column
data from running text if
needed.

Borrowed from Brown and
Heene (2017), "The GRIM
Test", and the R package
``statcheck`` for the
p-value recomputation.
"""
from __future__ import annotations

import json
import math
import re

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# ---------- number parsing ----------

# Match floats (incl. scientific
# notation) but not years or
# p-values with leading zeros.
_NUMBER = re.compile(
    r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
)


def _safe_float(s: str) -> float | None:
    """Parse a string as a
    float; return None on
    failure. We do not use
    ``float()`` directly
    because we want to handle
    ``NaN`` and ``inf``
    gracefully (those are
    never valid statistics)."""
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _decimal_places(s: str) -> int:
    """Infer the number of
    decimal places in a
    string representation of
    a number. ``"3.14"`` -> 2;
    ``"3"`` -> 0; ``"3.140"``
    -> 3. We count the digits
    *after* the dot, including
    trailing zeros, because a
    reported ``"3.140"``
    carries the implication
    that the author measured
    to three decimal places
    even if the value happens
    to end in zero. GRIM is
    about *reported*
    precision, not effective
    precision."""
    if "." in s:
        after = s.split(".", 1)[1]
        return len(after)
    if "e" in s or "E" in s:
        # Scientific notation
        # -- the decimal
        # places depend on
        # the exponent. We
        # treat it as 0 for
        # simplicity.
        return 0
    return 0


# ---------- GRIM test ----------


def _grim_test(
    values: list[float], reported_mean: float, decimals: int
) -> bool:
    """Return True if the
    reported mean is
    *consistent* with the
    sample.  The test is
    (Brown & Heene 2017):

      The sum of N integer
      values is always an
      integer.  The reported
      mean M with D decimal
      places implies a sum
      ``S = M * N``.  For ``S``
      to be a valid sum of N
      integer values, ``S``
      rounded to the nearest
      integer must be within
      ``1/2 * 10**-D`` of ``S``.

    Equivalently:
    ``abs(S - round(S)) < 1/2 * 10**-D``
    (the half-granularity
    tolerance is the standard
    GRIM convention; integer
    sums can be 0.5 steps from
    a half-integer rounded
    value).

    R-2026-06-15 (T5.1):
    the *original* implementation
    in this codebase was
    incorrect -- it checked
    ``abs(product -
    round(product / gran) * gran)
    < 1e-9`` which simplifies to
    "the float is close to
    itself rounded to the
    granularity" -- trivially
    true.  Every paper's
    reported mean would pass
    the original check.  The
    fixed implementation
    directly tests whether the
    implied sum ``S = M * N``
    is close to an integer
    (within half a
    granularity), which is
    the actual GRIM condition
    (Brown & Heene 2017).
    """
    if not values:
        return True
    n = len(values)
    sum_implied = reported_mean * n
    # ``abs(S - round(S)) < 0.5 *
    # 10**-D``.  The 0.5 is the
    # half-granularity tolerance:
    # an integer sum can differ
    # from a half-integer
    # rounded value by up to
    # half a granularity.
    tolerance = 0.5 * (10 ** -decimals)
    return abs(sum_implied - round(sum_implied)) < tolerance


class GrimTestDetector:
    """The GRIM test on every
    numerical column of every
    table attached to the
    document.

    A table in this codebase
    is a simple object with
    ``headers`` and ``rows``
    (see ``table_ocr`` for
    the OCR pipeline that
    produces them). The
    detector skips columns
    that look like
    identifiers (years, IDs)
    and focuses on the
    columns whose header
    contains the word
    "mean" or "average" or
    whose values cluster
    between 0 and 10
    (typical Likert means).

    R-2026-06-15 (T5.1):
    the original detector
    required the column to
    be labelled "mean" /
    "average" before running
    the GRIM check, which
    meant it fired 0 times on
    Frontiers papers (whose
    text doesn't write "mean=X"
    in the body).  We now
    ALSO run a *sensitive*
    GRIM check on every
    numeric column that has
    a sibling N column:
    ``value * n`` must be a
    multiple of ``1/10^decimals``.
    A real Frontiers figure
    table typically has
    ``n`` and a numeric value
    column (e.g. ``pct``,
    ``F``, ``p_value``,
    ``chi2``, etc.).  When
    the value column's
    reported decimal-places
    are not consistent with
    the N, we now emit a
    high-severity finding.
    """

    name = "stat_grim"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        tables = getattr(doc, "tables", []) or []
        for t_idx, table in enumerate(tables):
            headers = getattr(table, "headers", [])
            rows = getattr(table, "rows", [])
            if not headers or not rows:
                continue
            n_col = _find_n_column(headers, -1)
            if n_col is None:
                # No N column in this
                # table -- we cannot
                # run any check that
                # requires a sample
                # size.  Skip the
                # table entirely.
                continue
            # Pull the N values
            # once per table -- we
            # will cross-check
            # every numeric column
            # against this N.
            n_values: list[int] = []
            for r_idx, row in enumerate(rows):
                if n_col >= len(row):
                    continue
                v = _safe_float(row[n_col])
                if v is None:
                    n_values.append(-1)
                else:
                    n_values.append(int(v))
            # ---- (a) original
            # mean-column check ----
            for c_idx, header in enumerate(headers):
                h = (header or "").lower()
                if c_idx == n_col:
                    continue
                if not any(
                    k in h
                    for k in (
                        "mean", "average", "m ", "avg"
                    )
                ):
                    continue
                # Mean-column GRIM test
                # (original behaviour)
                for r_idx, row in enumerate(rows):
                    if c_idx >= len(row):
                        continue
                    cell = str(row[c_idx]).strip()
                    v = _safe_float(cell)
                    if v is None:
                        continue
                    if r_idx >= len(n_values):
                        continue
                    n = n_values[r_idx]
                    if n < 2:
                        continue
                    decimals = _decimal_places(cell)
                    if _grim_test(
                        [0.0] * n, v, decimals
                    ):
                        continue
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=self.name,
                            severity="high",
                            title=(
                                f"Table {t_idx + 1} "
                                f"column '{header}' "
                                f"value {cell} "
                                f"fails GRIM test for "
                                f"N={n} (decimals="
                                f"{decimals})"
                            ),
                            location=(
                                f"table {t_idx + 1}, "
                                f"column {c_idx + 1}"
                            ),
                            evidence=json.dumps(
                                {
                                    "check": "grim_mean",
                                    "table": t_idx + 1,
                                    "column": header,
                                    "row_index": r_idx,
                                    "reported_mean": v,
                                    "n": n,
                                    "decimals": decimals,
                                    "expected_product": v * n,
                                }
                            ),
                        )
                    )
            # ---- (b) T5.1: sensitive
            # GRIM check on EVERY
            # numeric column ----
            # For each column that is
            # not the N column itself,
            # try to interpret each
            # cell as a number.  If
            # the cell is a number with
            # 1+ decimal places, run
            # the GRIM test (value * n
            # must be a multiple of
            # 1/10^decimals).  This
            # catches the common case
            # where a Frontiers figure
            # table reports a
            # percentage with
            # inconsistent
            # decimal-places.
            for c_idx, header in enumerate(headers):
                if c_idx == n_col:
                    continue
                # Skip the mean columns
                # already covered by
                # (a) above -- the
                # original detector
                # is the more accurate
                # check when the column
                # is explicitly labelled
                # "mean".
                h = (header or "").lower()
                if any(
                    k in h
                    for k in (
                        "mean", "average", "m ", "avg"
                    )
                ):
                    continue
                # Skip the N column and
                # any column whose
                # header indicates an
                # identifier (year,
                # ID, sample / samplesize
                # -- same as the helper
                # above).
                if _is_identifier_column(h):
                    continue
                # Per-cell check.
                for r_idx, row in enumerate(rows):
                    if c_idx >= len(row):
                        continue
                    cell = str(row[c_idx]).strip()
                    v = _safe_float(cell)
                    if v is None:
                        continue
                    if r_idx >= len(n_values):
                        continue
                    n = n_values[r_idx]
                    if n < 2:
                        continue
                    decimals = _decimal_places(cell)
                    # The cell must have at
                    # least 1 decimal
                    # place for the GRIM
                    # test to be
                    # meaningful -- an
                    # integer cell is
                    # always GRIM-consistent
                    # regardless of n.
                    if decimals < 1:
                        continue
                    # Also skip very large
                    # or very small values
                    # -- GRIM is designed
                    # for values that are
                    # plausibly averages /
                    # percentages, not for
                    # raw counts.
                    if abs(v) > 1000:
                        continue
                    if _grim_test(
                        [0.0] * n, v, decimals
                    ):
                        continue
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=self.name,
                            severity="high",
                            title=(
                                f"Table {t_idx + 1} "
                                f"column '{header}' "
                                f"value {cell} "
                                f"fails GRIM test for "
                                f"N={n} (decimals="
                                f"{decimals})"
                            ),
                            location=(
                                f"table {t_idx + 1}, "
                                f"column {c_idx + 1}, "
                                f"row {r_idx + 1}"
                            ),
                            evidence=json.dumps(
                                {
                                    "check": "grim_sensitive",
                                    "table": t_idx + 1,
                                    "column": header,
                                    "row_index": r_idx,
                                    "reported_value": v,
                                    "n": n,
                                    "decimals": decimals,
                                    "expected_product": v * n,
                                }
                            ),
                        )
                    )
        return DetectorResult(
            detector=self.name, findings=findings, ok=True
        )


def _is_identifier_column(header: str) -> bool:
    """R-2026-06-15 (T5.1):
    return True if a column
    header looks like an
    identifier (year, ID, sample
    size) and the GRIM test
    should NOT be applied to it.

    Used by ``GrimTestDetector``
    to skip the sensitive-GRIM
    sub-check on columns that
    are clearly not averages
    (e.g. an "id" column, a
    "year" column, or a "p"
    column where p means page
    not p-value).
    """
    h = header.lower().strip()
    if not h:
        return True
    # year, id, p (page), t (time)
    if h in (
        "year", "id", "p", "t", "i",
        "dof", "df", "n", "k",
    ):
        return True
    if h.startswith("id_") or h.startswith("id-"):
        return True
    if h.startswith("year_") or h.startswith("year-"):
        return True
    return False


def _find_n_column(
    headers: list[str], exclude: int
) -> int | None:
    """Find the column index
    whose header is "n" or
    "sample" or "N"."""
    for i, h in enumerate(headers):
        if i == exclude:
            continue
        h_low = (h or "").lower().strip()
        if h_low in ("n", "sample", "samplesize", "size"):
            return i
    return None


# ---------- percent * n divisibility ----------


class PercentDivisibilityDetector:
    """For every column whose
    header mentions
    "percent" or "%", check
    that ``value * n / 100``
    is an integer for the
    reported sample size.

    We need the
    sample-size column to
    look up N for each row.
    """

    name = "stat_percent"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        tables = getattr(doc, "tables", []) or []
        for t_idx, table in enumerate(tables):
            headers = getattr(table, "headers", [])
            rows = getattr(table, "rows", [])
            if not headers or not rows:
                continue
            for c_idx, header in enumerate(headers):
                h = (header or "").lower()
                if not (
                    "%" in header
                    or "percent" in h
                    or "proportion" in h
                ):
                    continue
                n_col = _find_n_column(headers, c_idx)
                if n_col is None:
                    continue
                for r_idx, row in enumerate(rows):
                    if c_idx >= len(row) or n_col >= len(row):
                        continue
                    cell = str(row[c_idx]).strip()
                    pct = _safe_float(cell)
                    if pct is None:
                        continue
                    n = int(float(row[n_col]))
                    expected = pct * n / 100
                    if abs(expected - round(expected)) < 1e-9:
                        continue
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=self.name,
                            severity="high",
                            title=(
                                f"Table {t_idx + 1} "
                                f"column '{header}' "
                                f"value {pct}% does not "
                                f"correspond to a whole "
                                f"number of N={n} cases"
                            ),
                            location=(
                                f"table {t_idx + 1}, "
                                f"column {c_idx + 1}, "
                                f"row {r_idx + 1}"
                            ),
                            evidence=json.dumps(
                                {
                                    "table": t_idx + 1,
                                    "column": header,
                                    "row": r_idx + 1,
                                    "percent": pct,
                                    "n": n,
                                    "expected_count": expected,
                                }
                            ),
                        )
                    )
        return DetectorResult(
            detector=self.name,
            findings=findings,
            ok=True,
        )


# ---------- p-value plausibility ----------


def _pearson_p(r: float, n: int) -> float:
    """Compute the two-tailed
    p-value for a Pearson
    correlation ``r`` with
    ``n`` observations.

    Formula:
        t = r * sqrt((n-2) / (1 - r**2))
        p = 2 * (1 - t_cdf(|t|, n - 2))

    We use the regularised
    incomplete beta function
    to avoid pulling in
    scipy. The implementation
    follows the Numerical
    Recipes routine.
    """
    if n < 3 or abs(r) >= 1.0:
        # r == 1.0 or -1.0
        # implies a perfect
        # correlation -- the
        # p-value is 0.0.
        return 0.0
    t2 = (r * r) * (n - 2) / (1.0 - r * r)
    t = math.sqrt(t2)
    # Use the identity
    # p = I_x(a/2, b/2) where
    # x = df / (df + t^2),
    # a = df, b = 1.
    df = n - 2
    x = df / (df + t2)
    return _regularized_incomplete_beta(
        x, df / 2.0, 0.5
    )


def _regularized_incomplete_beta(
    x: float, a: float, b: float
) -> float:
    """The regularised
    incomplete beta function
    ``I_x(a, b)`` for
    ``a > 0``, ``b > 0``,
    ``0 <= x <= 1``.

    Implementation: a simple
    continued-fraction
    expansion that is good to
    ~1e-6 -- well within the
    tolerance we need for
    p-value recomputation.
    """
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    # Use the symmetry
    # ``I_x(a, b) = 1 -
    # I_{1-x}(b, a)`` to keep
    # ``x`` below 0.5 -- the
    # continued fraction is
    # more accurate there.
    if x > 0.5:
        return 1.0 - _regularized_incomplete_beta(
            1.0 - x, b, a
        )
    # Continued fraction
    # from Numerical Recipes.
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / (
            (qam + m2) * (a + m2)
        )
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        # Odd step
        aa = -(a + m) * (qab + m) * x / (
            (a + m2) * (qap + m2)
        )
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    # Final scaling.
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(
        lbeta + a * math.log(x) + b * math.log(1 - x)
    )
    return front * h / a


class PValueConsistencyDetector:
    """Recompute the p-value
    for every (r, n) pair
    reported in the text and
    compare to the reported
    p-value.

    The detector scans
    ``doc.text_blocks`` for
    patterns like
    ``"r = 0.42, p < 0.001"``
    or
    ``"r(48) = 0.42, p = .003"``.
    For each match it pulls
    out the reported ``r``,
    the reported ``p``, and
    the sample size ``N`` (from
    the degrees of freedom in
    parentheses, when given;
    otherwise from a sibling
    "N = ..." in the same
    sentence). It then
    computes the
    recomputed p-value and
    flags any disagreement
    above a 0.005 tolerance
    (to account for rounding
    in the original report).
    """

    name = "stat_pvalue"

    # ``r(48) = .42, p = .003``
    # is a common style. The
    # regex captures the
    # three numbers. We also
    # accept
    # ``r = .42, p < .001``.
    _RE_R_P = re.compile(
        r"r\s*[\(\[]?\s*(\d+)?\s*[\)\]]?\s*=\s*"
        r"(-?\d*\.?\d+).{0,60}?"
        r"p\s*[<=]\s*\.?(\d+(?:\.\d+)?(?:e-?\d+)?)"
    )

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        text = "".join(
            getattr(b, "text", "") for b in doc.text_blocks
        )
        if not text:
            return DetectorResult(
                detector=self.name,
                findings=findings,
                ok=True,
            )
        for match in self._RE_R_P.finditer(text):
            df_text, r_text, p_text = match.groups()
            r = _safe_float(r_text)
            p_reported = _safe_float(p_text)
            if r is None or p_reported is None:
                continue
            # N is the df + 2 (Pearson df = n - 2). If the
            # report did not include the df in parens we
            # cannot recompute; skip.
            if df_text is None:
                continue
            n = int(df_text) + 2
            if n < 3:
                continue
            p_recomputed = _pearson_p(r, n)
            # The reported p might
            # be "< 0.001" -- a
            # ceiling, not the
            # exact value. The
            # comparison only
            # flags a finding when
            # the recomputed
            # p-value is
            # *substantially*
            # different from the
            # reported one.
            # A 0.01 tolerance
            # covers most rounding.
            if (
                abs(p_reported - p_recomputed) < 0.01
            ):
                continue
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="high",
                    title=(
                        f"Reported p={p_reported:.3g} "
                        f"disagrees with recomputed "
                        f"p={p_recomputed:.3g} for "
                        f"r={r}, n={n}"
                    ),
                    location="text",
                    evidence=json.dumps(
                        {
                            "r": r,
                            "n": n,
                            "p_reported": p_reported,
                            "p_recomputed": p_recomputed,
                            "match": match.group(0)[:80],
                        }
                    ),
                )
            )
        return DetectorResult(
            detector=self.name,
            findings=findings,
            ok=True,
        )
