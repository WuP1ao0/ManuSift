"""Shared agent safety nets (cost / progress / tool caps).

Used by ``PydanticAgentLoop`` (and available for tests).
Semantics mirror the legacy ``AgentLoop`` where practical.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..llm.chat import ChatResponse


def cost_for_response(resp: ChatResponse) -> float:
    """USD estimate for one LLM response (audit/dashboard only).

    Cost-cap *protection* was removed (2026-07): this helper
    no longer feeds a loop-stopping budget.
    """
    usage = resp.usage or {}
    in_tok = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or 0
    )
    out_tok = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )
    if in_tok == 0 and out_tok == 0:
        try:
            return float(usage.get("cost_usd", 0) or 0)
        except (TypeError, ValueError):
            return 0.0
    try:
        from ..cost import _cost_for as _cf

        model = resp.model or "mock"
        if model in ("mock", "") or model.startswith("test-"):
            model = "claude-3-5-sonnet-latest"
        return float(_cf(model, in_tok, out_tok))
    except Exception:  # noqa: BLE001
        return float(in_tok + out_tok) * 1e-5


def tool_call_signature(resp: ChatResponse) -> str:
    """Stable signature of tool_use blocks (or ``no_tool``)."""
    if not resp.tool_calls:
        return "no_tool"
    parts: list[str] = []
    for tc in resp.tool_calls:
        name = tc.get("name", "")
        inp = tc.get("input", {}) or {}
        try:
            items = sorted(inp.items())
        except Exception:  # noqa: BLE001
            items = []
        parts.append(f"{name}({items})")
    return "|".join(parts)


@dataclass
class ProgressTracker:
    """Tracks no-progress turns across model responses."""

    limit: int = 3
    last_signature: str | None = None
    no_progress_turns: int = 0

    def update(self, resp: ChatResponse) -> str | None:
        """Return ``\"no_progress\"`` when the limit is hit, else None."""
        if self.limit <= 0:
            return None
        sig = tool_call_signature(resp)
        if sig == self.last_signature:
            self.no_progress_turns += 1
        else:
            self.no_progress_turns = 0
            self.last_signature = sig
        if self.no_progress_turns >= self.limit:
            return "no_progress"
        return None

    def reset_streak(self) -> None:
        self.no_progress_turns = 0


@dataclass
class ToolCallGate:
    """Per-run tool call caps + signature dedup (legacy semantics)."""

    max_same_tool: int = 12
    max_per_turn: int = 50
    max_bash_per_turn: int = 30
    signatures_cap: int = 1000
    exempt: frozenset[str] = field(
        default_factory=lambda: frozenset({"render_report"})
    )
    called_signatures: OrderedDict[str, None] = field(
        default_factory=OrderedDict
    )
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    bash_call_count: int = 0
    turn_call_count: int = 0

    @classmethod
    def from_settings(cls) -> "ToolCallGate":
        try:
            from ..config import get_settings

            s = get_settings()
            return cls(
                max_same_tool=int(
                    getattr(s, "tool_calls_per_name_cap", 12) or 0
                ),
                max_per_turn=int(
                    getattr(s, "tool_calls_per_turn_cap", 50) or 0
                ),
                max_bash_per_turn=int(
                    getattr(s, "bash_max_calls_per_turn", 30) or 0
                ),
            )
        except Exception:  # noqa: BLE001
            return cls()

    def new_turn(self) -> None:
        self.turn_call_count = 0
        self.bash_call_count = 0

    def _sig_key(self, name: str, args: dict[str, Any]) -> str:
        try:
            args_str = json.dumps(
                args, sort_keys=True, ensure_ascii=False, default=str
            )
        except Exception:  # noqa: BLE001
            args_str = repr(args)
        return f"{name}|{args_str}"

    def check(
        self, name: str, args: dict[str, Any] | None
    ) -> str | None:
        """Return an error string if the call is denied, else None."""
        args = args or {}
        key = self._sig_key(name, args)
        if key in self.called_signatures:
            return (
                "error: duplicate tool call -- "
                f"tool={name!r} with the same arguments has already "
                "been executed in this conversation. Pick a different "
                "tool, change the arguments, or write a final summary."
            )
        if (
            self.max_per_turn > 0
            and self.turn_call_count >= self.max_per_turn
        ):
            return (
                f"error: budget_exhausted -- tool calls per turn "
                f"cap ({self.max_per_turn}) reached. "
                "Set MANUSIFT_TOOL_MAX_CALLS_PER_TURN to raise it."
            )
        if name in ("bash", "shell") and self.max_bash_per_turn > 0:
            if self.bash_call_count >= self.max_bash_per_turn:
                return (
                    f"error: budget_exhausted -- bash calls per turn "
                    f"cap ({self.max_bash_per_turn}) reached. "
                    "Set MANUSIFT_BASH_MAX_CALLS_PER_TURN to raise it."
                )
        if name not in self.exempt and self.max_same_tool > 0:
            count = self.tool_call_counts.get(name, 0)
            if count >= self.max_same_tool:
                return (
                    f"error: budget_exhausted -- tool {name!r} called "
                    f"{count} times (cap {self.max_same_tool}). "
                    "Set MANUSIFT_TOOL_MAX_CALLS_PER_NAME to raise it."
                )
        return None

    def record(self, name: str, args: dict[str, Any] | None) -> None:
        args = args or {}
        key = self._sig_key(name, args)
        self.called_signatures[key] = None
        while len(self.called_signatures) > self.signatures_cap:
            self.called_signatures.popitem(last=False)
        self.tool_call_counts[name] = (
            self.tool_call_counts.get(name, 0) + 1
        )
        self.turn_call_count += 1
        if name in ("bash", "shell"):
            self.bash_call_count += 1
