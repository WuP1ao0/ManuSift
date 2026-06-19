"""R-2026-06-15 (Phase 3 + P3-7):
test the
``format_stats_for_tui``
helper.

The audit flagged that
the TUI has no live
indication of detector
progress.  The fix is a
small helper that turns
a
``DetectorResult.stats``
dict into a compact
human-readable string
for the TUI's
``#detector-count``
segment.

The function is
deterministic: the
same input dict
always produces the
same output, with a
canonical key order
that does not depend
on dict insertion
order (the audit's
visual contract).

These tests verify:

  1. Empty / None stats
     produce
     ``"0 stats reported"``
     (the sentinel).
  2. A single known
     key renders with
     the canonical
     template
     (e.g. ``"8 figures scanned"``).
  3. Multiple known
     keys render in
     canonical order
     (not dict
     insertion order).
  4. Unknown keys
     render as
     ``key=value``
     (fallback).
  5. Mixed known +
     unknown keys
     render in
     canonical order
     for the known,
     then sorted
     alphabetical for
     the unknown.
  6. The
     ``NO_STATS``
     sentinel is the
     same string the
     function returns
     for empty input
     (so the TUI can
     use ``is``
     comparison for
     an early-return).
  7. Non-int values
     (e.g. ``str``,
     ``float``) render
     correctly.
"""
from __future__ import annotations

import pytest

from manusift.tui.stats_renderer import (
    NO_STATS,
    format_stats_for_tui,
)


def test_p37_empty_dict_returns_no_stats() -> None:
    """An empty
    ``stats`` dict
    renders as
    ``"0 stats reported"``.
    """
    assert format_stats_for_tui({}) == NO_STATS


def test_p37_none_returns_no_stats() -> None:
    """``None`` is
    treated as empty
    and renders as
    ``"0 stats reported"``.
    """
    assert format_stats_for_tui(None) == NO_STATS


def test_p37_single_known_key_uses_canonical_template() -> None:
    """A single known
    key renders with
    the canonical
    template.
    """
    s = format_stats_for_tui(
        {"figures_scanned": 8}
    )
    assert s == "8 figures scanned"


def test_p37_multiple_known_keys_in_canonical_order() -> None:
    """Multiple known
    keys render in
    canonical order
    (not dict
    insertion order).
    """
    # Insert in
    # REVERSE canonical
    # order to verify
    # the helper does
    # not just preserve
    # insertion order.
    s = format_stats_for_tui(
        {
            "dup_pairs_found": 2,
            "figures_scanned": 8,
        }
    )
    assert s == (
        "8 figures scanned, 2 dup-pairs"
    )


def test_p37_unknown_key_renders_as_key_equals_value() -> None:
    """Unknown keys
    fall back to
    ``key=value``.
    """
    s = format_stats_for_tui(
        {"custom_metric": 42}
    )
    assert s == "custom_metric=42"


def test_p37_mixed_known_and_unknown_keys() -> None:
    """Mixed known and
    unknown keys
    render in
    canonical order
    for the known,
    then alphabetical
    for the unknown.
    """
    s = format_stats_for_tui(
        {
            "z_unknown": 1,
            "figures_scanned": 5,
            "a_custom": 2,
        }
    )
    # Canonical first
    # (``figures_scanned``),
    # then alphabetical
    # unknown keys
    # (``a_custom`` < ``z_unknown``).
    assert s == (
        "5 figures scanned, "
        "a_custom=2, z_unknown=1"
    )


def test_p37_all_canonical_keys() -> None:
    """All canonical
    keys render in
    their canonical
    order, joined by
    ``", "``.
    """
    s = format_stats_for_tui(
        {
            "figures_scanned": 8,
            "figures_with_concerns": 2,
            "dup_pairs_found": 1,
            "cells_analyzed": 1200,
            "tokens_checked": 2400,
            "p_values_checked": 5,
            "rows_checked": 100,
            "elapsed_ms": 120,
        }
    )
    assert s == (
        "8 figures scanned, "
        "2 figures with concerns, "
        "1 dup-pairs, "
        "1200 cells analyzed, "
        "2400 tokens checked, "
        "5 p-values checked, "
        "100 rows checked, "
        "120ms"
    )


def test_p37_no_stats_sentinel_is_correct() -> None:
    """The
    ``NO_STATS``
    sentinel matches
    the function
    output for empty
    input.
    """
    assert NO_STATS == "0 stats reported"
    assert format_stats_for_tui({}) == NO_STATS


def test_p37_non_int_values_render() -> None:
    """Non-int values
    (e.g. ``str``,
    ``float``) render
    correctly.
    """
    s = format_stats_for_tui(
        {"custom_metric": "high"}
    )
    assert s == "custom_metric=high"
    s2 = format_stats_for_tui(
        {"custom_metric": 1.5}
    )
    assert s2 == "custom_metric=1.5"


def test_p37_dup_pairs_uses_hyphenated_form() -> None:
    """The
    ``dup_pairs_found``
    key uses the
    hyphenated form
    ``"dup-pairs"``
    (the visual
    contract).
    """
    s = format_stats_for_tui(
        {"dup_pairs_found": 3}
    )
    assert s == "3 dup-pairs"
    assert "dup-pairs" in s
    assert "dup_pairs" not in s
