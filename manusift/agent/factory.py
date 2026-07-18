"""Agent-loop factory: PydanticAI runtime with legacy fallback.

Domain Kernel tools and ``ToolContext`` are passed through unchanged.
Only the ReAct driver implementation is selected here.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..tools import ToolContext

log = logging.getLogger(__name__)


def resolve_agent_runtime(explicit: str | None = None) -> str:
    """Return ``pydantic_ai`` or ``legacy``.

    Resolution order:
      1. explicit argument
      2. ``Settings.agent_runtime``
      3. default ``pydantic_ai`` when the package imports cleanly,
         otherwise ``legacy``
    """
    if explicit in ("pydantic_ai", "legacy"):
        return explicit
    try:
        from ..config import get_settings

        val = (get_settings().agent_runtime or "").strip().lower()
        if val in ("pydantic_ai", "legacy", "pydantic", "pyd"):
            if val in ("pydantic", "pyd"):
                return "pydantic_ai"
            return val
    except Exception:  # noqa: BLE001
        pass
    try:
        import pydantic_ai  # noqa: F401

        return "pydantic_ai"
    except Exception:  # noqa: BLE001
        return "legacy"


def create_agent_loop(
    client: Any,
    tools: list[Any],
    ctx: ToolContext,
    *,
    runtime: str | None = None,
    system_prompt: str | None = None,
    max_steps: int = 0,
    max_cost_usd: float = 0,
    no_progress_turn_limit: int = 3,
    on_step: Callable[..., None] | None = None,
    audit_sink: Callable[..., None] | None = None,
    on_tool_result: Callable[[str, str, bool, str], None] | None = None,
    parent_interrupt_signal: Callable[[], bool] | None = None,
) -> Any:
    """Construct the configured agent loop implementation.

    Public kwargs mirror ``AgentLoop.__init__`` so call sites can
    switch with a single import change.
    """
    chosen = resolve_agent_runtime(runtime)
    kwargs = dict(
        client=client,
        tools=tools,
        ctx=ctx,
        system_prompt=system_prompt,
        max_steps=max_steps,
        max_cost_usd=max_cost_usd,
        no_progress_turn_limit=no_progress_turn_limit,
        on_step=on_step,
        audit_sink=audit_sink,
        on_tool_result=on_tool_result,
        parent_interrupt_signal=parent_interrupt_signal,
    )
    if chosen == "pydantic_ai":
        try:
            from .pydantic_loop import PydanticAgentLoop

            log.debug("create_agent_loop: using PydanticAgentLoop")
            return PydanticAgentLoop(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "PydanticAI runtime unavailable; falling back to legacy",
                extra={"err": str(exc)},
            )
    from .legacy_loop import AgentLoop

    log.debug("create_agent_loop: using legacy AgentLoop")
    return AgentLoop(**kwargs)
