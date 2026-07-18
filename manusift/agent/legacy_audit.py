"""Audit-sink helper extracted from the legacy AgentLoop.

Keeps the package surface modular without changing audit JSONL shape.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


def emit_tool_audit(
    audit_sink: Callable[[dict[str, Any]], None] | None,
    *,
    tool_name: str,
    tool_input: Any,
    output: Any,
    error: str | None,
    duration_ms: int = 0,
) -> None:
    """Forward one tool-call record to the audit sink (never raises)."""
    if audit_sink is None:
        return
    try:
        from ..tools.redactor import redact_input, redact_output

        redacted_input = redact_input(tool_input)
        redacted_output = redact_output(output)
        audit_sink(
            {
                "ts": time.time(),
                "tool": tool_name,
                "input": redacted_input,
                "output_preview": (
                    redacted_output[:200]
                    if isinstance(redacted_output, str)
                    else str(redacted_output)[:200]
                ),
                "error": error,
                "ok": error is None,
                "duration_ms": int(duration_ms),
            }
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "audit_sink raised",
            extra={"tool": tool_name, "err": str(exc)},
        )
