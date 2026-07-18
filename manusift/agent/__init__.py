"""ManuSift agent package — public surface.

Domain Kernel tools stay outside this package. Runtime selection:

  * **default** — ``create_agent_loop`` → PydanticAI (``PydanticAgentLoop``)
  * **legacy** — hand-rolled ``AgentLoop`` in ``legacy_loop.py``
    (``MANUSIFT_AGENT_RUNTIME=legacy``)

Backward-compatible re-exports (keep existing imports working)::

    from manusift.agent import AgentLoop, AgentLoopResult
    from manusift.agent import create_agent_loop
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
