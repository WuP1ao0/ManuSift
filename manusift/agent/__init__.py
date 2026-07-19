"""ManuSift agent package — public surface.

**Supported entry:** ``create_agent_loop`` → PydanticAI by default.

  * **pydantic_ai** (default) — ``PydanticAgentLoop`` (maintained)
  * **legacy** — frozen ``AgentLoop`` in ``legacy_loop.py``
    (``MANUSIFT_AGENT_RUNTIME=legacy`` only; do not extend)

Backward-compatible re-exports::

    from manusift.agent import create_agent_loop
    from manusift.agent import AgentLoop, AgentLoopResult  # legacy
"""
from __future__ import annotations

# Legacy loop (tests + explicit legacy runtime).
from .legacy_loop import AgentLoop, AgentLoopResult

# Factory (preferred production entry).
from .factory import create_agent_loop, resolve_agent_runtime

# Re-export get_tool so historical monkeypatches of
# ``manusift.agent.get_tool`` still resolve; the legacy
# loop binds ``get_tool`` from ``legacy_loop`` (see tests).
from ..tools import get_tool

# Optional helpers used by callers / docs.
from .system_prompt import build_system_prompt, DEFAULT_SYSTEM_PROMPT

__all__ = [
    "AgentLoop",
    "AgentLoopResult",
    "create_agent_loop",
    "resolve_agent_runtime",
    "build_system_prompt",
    "DEFAULT_SYSTEM_PROMPT",
    "get_tool",
]
