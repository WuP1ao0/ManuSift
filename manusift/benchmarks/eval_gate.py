"""R-2026-06-15 (Phase 3 + P3-8):
the eval-gate pytest.

The audit recommended
gating Phase 4 on a
hard pytest:

  ``(partial + exact) /
  (partial + exact +
  missed) >= 0.7``

across the 30-case v2
benchmark.  In words: at
least 70% of the
"testable" official
targets must be
detected by some
ManuSift detector.  The
gate is **per-case**: a
case with no
``not_testable`` items
contributes its full
``(partial + exact) /
total`` ratio; a case
with ``not_testable``
items has those targets
subtracted from the
denominator (we don't
penalise the system for
official targets that
public material cannot
verify).

This module is the
test runner that:

  1. Reads each
     ``cases/<domain>/<id>/official_gold.json``
     (the 30-case v2
     benchmark).
  2. Reads each
     ``cases/<domain>/<id>/manusift_run/tool_summary.json``
     (the detector
     output from the
     most recent
     ``run_manusift.py``
     invocation).
  3. For each case,
     computes
     ``exact`` /
     ``partial`` /
     ``missed`` /
     ``not_testable``
     counts based on
     whether the
     expected detectors
     fired.
  4. Aggregates the
     ratio and asserts
     it is ``>= 0.7``.

The module is exposed as
a pytest via
``tests/test_phase3_p38_eval_gate.py``
which imports the
helpers and runs the
gate.

Usage:
    pytest tests/test_phase3_p38_eval_gate.py -v
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The default root for
# the 30-case v2
# benchmark.  Tests
# can override via
# ``compute_eval_ratio(root=...)``.
DEFAULT_BENCH_ROOT = (
    Path(__file__).parent.parent.parent
    / "manusift_benchmarks"
    / "officially_flagged_cases_v2"
)

# The audit's recommended
# gate threshold.  A
# case passes the gate
# if its detection
# ratio is >= this
# value.
EVAL_GATE_THRESHOLD = 0.7


@dataclass
class CaseEval:
    """Per-case
    eval-gate result.

    Fields:
      case_id
      domain
      n_expected: count of
        ``expected_manusift_detectors``
        (the detectors
        the official
        gold says should
        fire).
      n_exact: count of
        expected detectors
        that DID fire
        in the run.
      n_partial: count of
        expected detectors
        that fired but
        with a low
        confidence (we
        treat partial as
        half-credit in
        the ratio).
      n_missed: count of
        expected detectors
        that did NOT fire.
      n_not_testable: count
        of official targets
        the public
        material cannot
        verify (excluded
        from the
        denominator).
      ratio: the audit's
        metric,
        ``(exact + 0.5*partial) /
        (exact + partial + missed)``
        (not_testable
        excluded).
    """

    case_id: str
    domain: str
    n_expected: int
    n_exact: int
    n_partial: int = 0
    n_missed: int = 0
    n_not_testable: int = 0
    ratio: float = 0.0

    @property
    def passes_gate(self) -> bool:
        return self.ratio >= EVAL_GATE_THRESHOLD


@dataclass
class AggregateEval:
    """The 30-case
    aggregate result.

    Fields:
      cases: list of
        ``CaseEval`` (one
        per case).
      overall_ratio:
        weighted average
        across cases
        (the simple
        average is
        misleading when
        cases have
        different
        numbers of
        expected
        detectors; we
        use the
        weighted
        average).
      passes: ``True``
        if
        ``overall_ratio >= EVAL_GATE_THRESHOLD``.
    """

    cases: list[CaseEval] = field(
        default_factory=list
    )
    overall_ratio: float = 0.0
    passes: bool = False


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(
        encoding="utf-8"
    ) as f:
        return json.load(f)


def _case_paths(
    root: Path,
) -> list[tuple[Path, Path]]:
    """Return
    ``[(gold_path, run_dir), ...]``
    for every case under
    ``root`` that has
    both an
    ``official_gold.json``
    and a
    ``manusift_run/tool_summary.json``.
    """
    pairs: list[
        tuple[Path, Path]
    ] = []
    for case_dir in sorted(
        (root / "cases").glob("*/*")
    ):
        if not case_dir.is_dir():
            continue
        gold = (
            case_dir / "official_gold.json"
        )
        run_dir = (
            case_dir / "manusift_run"
        )
        tool_summary = (
            run_dir / "tool_summary.json"
        )
        if gold.exists() and tool_summary.exists():
            pairs.append((gold, tool_summary))
    return pairs


def evaluate_case(
    gold: dict[str, Any],
    run: dict[str, Any],
) -> CaseEval:
    """Compute the
    per-case eval-gate
    result.

    Algorithm:
      1. ``expected`` =
        ``gold["expected_manusift_detectors"]``.
      2. ``fired`` = set
        of detector names
        with
        ``findings_by_detector[name] > 0``.
      3. ``exact`` = count
        of ``expected``
        that are in
        ``fired``.
      4. ``missed`` =
        ``len(expected) - exact``.
      5. ``not_testable`` =
        ``len(gold.get("not_testable_items", []))``.
      6. ``ratio`` = ``exact
        / max(1, exact + missed)``
        (the audit's metric
        with partial
        = 0 for now;
        partial counting
        is a future
        enhancement
        once detectors
        report a
        confidence
        score).

    Note: this
    implementation
    treats *every*
    expected detector
    that fired as
    ``exact`` (binary).
    The audit's
    ``partial``
    category would
    require
    per-finding
    confidence
    scoring, which is
    out of scope for
    P3-8 (the
    detectors do not
    yet report a
    confidence score
    in the
    ``tool_summary``).
    """
    expected = gold.get(
        "expected_manusift_detectors", []
    )
    fired_dict = run.get(
        "findings_by_detector", {}
    )
    fired = {
        name
        for name, count in fired_dict.items()
        if count and count > 0
    }
    expected_set = set(expected)
    exact = len(expected_set & fired)
    missed = len(expected_set - fired)
    not_testable = len(
        gold.get("not_testable_items", [])
    )
    n = exact + missed
    ratio = (
        exact / n if n > 0 else 0.0
    )
    return CaseEval(
        case_id=gold.get(
            "case_id", "unknown"
        ),
        domain=gold.get(
            "domain", "unknown"
        ),
        n_expected=len(expected_set),
        n_exact=exact,
        n_missed=missed,
        n_not_testable=not_testable,
        ratio=ratio,
    )


def evaluate_benchmark(
    root: Path | None = None,
) -> AggregateEval:
    """Aggregate the
    per-case eval-gate
    results across all
    30 cases.
    """
    root = root or DEFAULT_BENCH_ROOT
    pairs = _case_paths(root)
    cases: list[CaseEval] = []
    for gold_path, run_path in pairs:
        gold = _load_json(gold_path)
        run = _load_json(run_path)
        cases.append(evaluate_case(gold, run))
    # Weighted average
    # (so cases with
    # more expected
    # detectors
    # contribute more).
    total = sum(c.n_exact + c.n_missed for c in cases)
    weighted_num = sum(
        c.n_exact for c in cases
    )
    overall = (
        weighted_num / total
        if total > 0
        else 0.0
    )
    return AggregateEval(
        cases=cases,
        overall_ratio=overall,
        passes=(
            overall >= EVAL_GATE_THRESHOLD
        ),
    )
