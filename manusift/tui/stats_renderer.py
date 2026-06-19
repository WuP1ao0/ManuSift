"""R-2026-06-15 (Phase 3 + P3-7):
format ``DetectorResult.stats``
as a TUI-friendly string.

The audit flagged that
the TUI shows a "running"
spinner during detector
execution, with no
indication of *what* the
detector is doing.  The
fix is to read
``DetectorResult.stats``
and render a compact
human-readable string
like:

  * "8 figures scanned, 2 dup-pairs"
  * "12 cells analyzed"
  * "2400 tokens checked"
  * "0 stats reported"
    (the default / empty case)

The TUI's
``#detector-count``
segment (a Textual
Static widget) calls
``format_stats_for_tui()``
after each detector
finishes and updates
its renderable.

The function is
**deterministic**: the
same ``stats`` dict
always produces the same
string, so the TUI can
diff consecutive
renders cheaply.

We use a small
**canonical key order**
to avoid the TUI
"jumping" as the
detector adds keys:

  1. ``figures_scanned``
  2. ``figures_with_concerns``
  3. ``dup_pairs_found``
  4. ``cells_analyzed``
  5. ``tokens_checked``
  6. ``p_values_checked``
  7. ``rows_checked``
  8. ``elapsed_ms``
  9. any other keys
     (alphabetical)

This is a *visual*
contract: a detector
that publishes
``{"figures_scanned": 5, "tokens_checked": 1000}``
renders as
``"5 figures scanned, 1000 tokens checked"``,
not as
``"1000 tokens checked, 5 figures scanned"``
(the order of dict
insertion in Python
3.7+ would otherwise
be the order of
``__init__`` calls in
the detector, which is
fragile).
"""
from __future__ import annotations

from typing import Any

# Canonical key order for
# the TUI's
# ``#detector-count``
# segment.  R-2026-06-15
# (Phase 3 + P3-7):
# the order is part of
# the visual contract.
_CANONICAL_KEY_ORDER: tuple[str, ...] = (
    "figures_scanned",
    "figures_with_concerns",
    "dup_pairs_found",
    "cells_analyzed",
    "tokens_checked",
    "p_values_checked",
    "rows_checked",
    "elapsed_ms",
)


def _format_key_value(
    key: str,
    value: Any,
) -> str:
    """Render a single
    ``(key, value)`` pair
    as a human-readable
    fragment.

    Examples:
      * ``("figures_scanned", 8)`` ->
        ``"8 figures scanned"``
      * ``("dup_pairs_found", 2)`` ->
        ``"2 dup-pairs"``
      * ``("cells_analyzed", 1200)`` ->
        ``"1200 cells analyzed"``
      * ``("tokens_checked", 2400)`` ->
        ``"2400 tokens checked"``
      * ``("p_values_checked", 5)`` ->
        ``"5 p-values checked"``
      * ``("elapsed_ms", 120)`` ->
        ``"120ms"``
      * ``("custom_key", 3)`` ->
        ``"custom_key=3"``
    """
    # Known keys have a
    # canonical
    # rendering.  Unknown
    # keys fall back to
    # ``key=value``.
    canonical_renderings: dict[
        str, str
    ] = {
        "figures_scanned": (
            "{v} figures scanned"
        ),
        "figures_with_concerns": (
            "{v} figures with concerns"
        ),
        "dup_pairs_found": (
            "{v} dup-pairs"
        ),
        "cells_analyzed": (
            "{v} cells analyzed"
        ),
        "tokens_checked": (
            "{v} tokens checked"
        ),
        "p_values_checked": (
            "{v} p-values checked"
        ),
        "rows_checked": (
            "{v} rows checked"
        ),
        "elapsed_ms": "{v}ms",
    }
    template = canonical_renderings.get(key)
    if template is None:
        return f"{key}={value}"
    return template.format(v=value)


def format_stats_for_tui(
    stats: dict[str, Any] | None,
) -> str:
    """Format a
    ``DetectorResult.stats``
    dict for the TUI's
    ``#detector-count``
    segment.

    Examples:
      * ``{}`` -> ``"0 stats reported"``
      * ``{"figures_scanned": 8}`` ->
        ``"8 figures scanned"``
      * ``{"figures_scanned": 8, "dup_pairs_found": 2}`` ->
        ``"8 figures scanned, 2 dup-pairs"``
      * ``None`` -> ``"0 stats reported"``
        (treated as empty)
    """
    if not stats:
        return "0 stats reported"
    # Build the parts in
    # canonical order.
    parts: list[str] = []
    seen: set[str] = set()
    for key in _CANONICAL_KEY_ORDER:
        if key in stats:
            parts.append(
                _format_key_value(key, stats[key])
            )
            seen.add(key)
    # Append unknown
    # keys (sorted) so
    # the rendering is
    # deterministic.
    for key in sorted(
        k for k in stats if k not in seen
    ):
        parts.append(
            _format_key_value(key, stats[key])
        )
    return ", ".join(parts)


# Convenience: a
# sentinel for "no stats
# yet" (used by the TUI
# before any detector
# has run).
NO_STATS = "0 stats reported"
