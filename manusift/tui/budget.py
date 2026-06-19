"""Budget snapshot for the chat TUI (R-2026-06-15,
Phase 0.4).

The user reported that the
``MANUSIFT_TOOL_CALLS_PER_NAME_CAP``
and other budget env vars were
invisible from the chat TUI.
``/cost`` showed the running
tokens but not the caps.
``/budget`` shows both.

This module exposes a pure
``render_budget_snapshot()``
function that tests can pin
without spinning up a
textual App.
"""
from __future__ import annotations

from typing import Any, Mapping


def render_budget_snapshot(
    consumed: Mapping[str, int] | None = None,
    settings: Any = None,
) -> str:
    """Render a multi-line
    budget snapshot.

    The contract:

      * Lines are stable
        (``key: value``) so
        tests can pin
        individual lines.
      * Unknown env vars in
        ``consumed`` are not
        shown (defensive: a
        stale snapshot from a
        previous version is
        tolerated).
      * The function does
        NOT import
        ``manusift.config``
        directly (the tests
        want to pass a mock
        settings object).
    """
    consumed = consumed or {}
    lines: list[str] = []
    lines.append("=== Budget Snapshot ===")
    if settings is not None:
        caps = [
            (
                "tool_calls_per_name_cap",
                getattr(
                    settings,
                    "tool_calls_per_name_cap",
                    None,
                ),
            ),
            (
                "tool_calls_per_turn_cap",
                getattr(
                    settings,
                    "tool_calls_per_turn_cap",
                    None,
                ),
            ),
            (
                "bash_max_calls_per_turn",
                getattr(
                    settings,
                    "bash_max_calls_per_turn",
                    None,
                ),
            ),
            (
                "data_source_max_files",
                getattr(
                    settings,
                    "data_source_max_files",
                    None,
                ),
            ),
            (
                "subagent_timeout_seconds",
                getattr(
                    settings,
                    "subagent_timeout_seconds",
                    None,
                ),
            ),
        ]
        for key, cap in caps:
            if cap is None:
                continue
            used = consumed.get(key, 0)
            line = f"  {key}: {used} / {cap}"
            lines.append(line)
    # Always show the consumed
    # map even if no settings
    # were passed. When
    # ``settings`` is provided,
    # we only show extras that
    # are known to the settings
    # model. Unknown keys
    # (stale snapshots from
    # previous versions) are
    # silently dropped to
    # keep the output
    # deterministic.
    if consumed and settings is None:
        lines.append("")
        lines.append("=== Consumed (no cap set) ===")
        for key, value in consumed.items():
            lines.append(
                f"  {key}: {value}"
            )
    return "\n".join(lines)
