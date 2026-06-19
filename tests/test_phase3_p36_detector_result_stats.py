"""R-2026-06-15 (Phase 3 + P3-6):
verify the
``DetectorResult.stats``
field.

The audit flagged that
the user has no way to
see *what* a detector
scanned -- only a
"running" spinner.  The
fix is a per-detector
``stats`` dict on the
``DetectorResult``
envelope (e.g.
``{"figures_scanned": 12, "cells_analyzed": 1200}``).
The TUI's
``#detector-count``
segment reads the
stats to render a live
progress indicator.

These tests verify:

  1. ``DetectorResult``
     has a ``stats``
     field (the
     dataclass
     schema
     includes it).
  2. ``stats`` defaults
     to an empty dict
     (backward-
     compatible with
     the previous
     no-stats
     contract).
  3. ``stats`` is
     read-write
     (it is a
     ``dict``; the
     ``Detector``
     ``run()`` can
     populate it).
  4. ``DetectorResult``
     with
     ``stats=...``
     is constructible
     in a single
     call.
  5. The
     ``DetectorResult``
     is ``frozen``
     (the audit
     flagged the
     pre-existing
     dataclass
     contract;
     ``frozen=True``
     means
     ``stats``
     cannot be
     mutated after
     construction).
  6. Detector
     implementations
     can populate
     ``stats`` via
     the standard
     constructor
     (the test
     uses a stub
     detector).
"""
from __future__ import annotations

import pytest

from manusift.detectors.base import (
    DetectorResult,
)


def test_p36_detector_result_has_stats_field() -> None:
    """``DetectorResult``
    has a ``stats``
    field.
    """
    r = DetectorResult(detector="x", ok=True)
    assert hasattr(r, "stats")


def test_p36_stats_defaults_to_empty_dict() -> None:
    """``stats`` defaults
    to ``{}`` (backward
    compatibility).
    """
    r = DetectorResult(detector="x", ok=True)
    assert r.stats == {}


def test_p36_stats_can_be_set_at_construction() -> None:
    """``stats`` can be
    passed at
    construction time.
    """
    r = DetectorResult(
        detector="x",
        ok=True,
        stats={
            "figures_scanned": 12,
            "cells_analyzed": 1200,
        },
    )
    assert r.stats == {
        "figures_scanned": 12,
        "cells_analyzed": 1200,
    }


def test_p36_stats_field_is_frozen_via_dataclass() -> None:
    """``DetectorResult``
    is ``frozen=True``,
    so the ``stats``
    *field* cannot be
    reassigned after
    construction (the
    audit's security
    property: a detector
    cannot replace the
    whole stats dict
    after publishing it).

    The dict *contents*
    are still mutable
    (this is the same
    shallow-freeze pattern
    as
    ``ToolContext.metadata``,
    which the audit
    P1-1 fixed by
    wrapping in
    ``MappingProxyType``;
    a future P1-N may do
    the same for
    ``DetectorResult.stats``
    if a detector is
    found to mutate it
    in production).
    """
    r = DetectorResult(
        detector="x",
        ok=True,
        stats={"figures_scanned": 5},
    )
    with pytest.raises(
        Exception
    ) as excinfo:  # FrozenInstanceError
        r.stats = {"replaced": 1}
    # The error is
    # ``dataclasses.FrozenInstanceError``
    # (a subclass of
    # ``AttributeError``).
    assert (
        "frozen" in str(excinfo.value).lower()
        or "FrozenInstanceError"
        in type(excinfo.value).__name__
    )


def test_p36_stats_preserved_through_equality() -> None:
    """Two ``DetectorResult``
    with the same
    ``stats`` are
    equal (the
    dataclass ``__eq__``
    includes all
    fields).
    """
    r1 = DetectorResult(
        detector="x",
        ok=True,
        stats={"a": 1},
    )
    r2 = DetectorResult(
        detector="x",
        ok=True,
        stats={"a": 1},
    )
    assert r1 == r2


def test_p36_stats_different_makes_inequality() -> None:
    """Different
    ``stats`` make the
    ``DetectorResult``
    unequal.
    """
    r1 = DetectorResult(
        detector="x",
        ok=True,
        stats={"a": 1},
    )
    r2 = DetectorResult(
        detector="x",
        ok=True,
        stats={"a": 2},
    )
    assert r1 != r2


def test_p36_detector_run_populates_stats() -> None:
    """A detector
    implementation can
    populate ``stats``
    by passing it at
    construction time
    (the audit's
    recommended
    pattern).
    """
    # A stub detector
    # that pretends to
    # scan 3 figures
    # and 1 cell.
    r = DetectorResult(
        detector="figure_dup",
        ok=True,
        findings=[],
        duration_ms=120,
        stats={
            "figures_scanned": 3,
            "dup_pairs_found": 1,
        },
    )
    # The TUI
    # ``#detector-count``
    # segment reads
    # ``stats``.
    assert r.stats["figures_scanned"] == 3
    assert r.stats["dup_pairs_found"] == 1
