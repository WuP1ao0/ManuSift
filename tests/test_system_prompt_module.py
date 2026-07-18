"""Shared system_prompt module + TaskTool factory wiring."""
from __future__ import annotations

from manusift.agent.system_prompt import (
    DEFAULT_SYSTEM_PROMPT,
    append_conversation_state,
    build_system_prompt,
)
from manusift.tools.tool import ToolContext


def test_default_system_prompt_is_nonempty_and_branded():
    assert "ManuSift" in DEFAULT_SYSTEM_PROMPT
    assert "render_report" in DEFAULT_SYSTEM_PROMPT
    assert len(DEFAULT_SYSTEM_PROMPT) > 1000


def test_build_system_prompt_appends_conversation_state():
    ctx = ToolContext(
        trace_id="t1",
        metadata={
            "conversation_state": {
                "active_trace_id": "job-abc",
                "current_pdf": "C:/paper.pdf",
                "data_sources": ["a.xlsx", "b.csv"],
                "last_assistant_offer": "generate report?",
            }
        },
    )
    sp = build_system_prompt([], ctx=ctx)
    assert "Conversation State Reminder" in sp
    assert "job-abc" in sp
    assert "paper.pdf" in sp
    assert "a.xlsx" in sp


def test_build_system_prompt_respects_override():
    sp = build_system_prompt([], system_prompt="custom only")
    assert sp.startswith("custom only")
    assert "ManuSift" not in sp


def test_append_conversation_state_noop_without_meta():
    assert append_conversation_state("base", None) == "base"
    assert append_conversation_state("base", {}) == "base"


def test_legacy_agentloop_uses_shared_prompt():
    from manusift.agent import AgentLoop
    from manusift.llm.client.mock import MockLLM

    loop = AgentLoop(
        client=MockLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
        max_steps=1,
    )
    assert "ManuSift" in loop._system_prompt
    assert "paper-integrity" in loop._system_prompt or "诚信" in loop._system_prompt


def test_pydantic_loop_uses_shared_prompt():
    from manusift.agent.pydantic_loop import PydanticAgentLoop
    from manusift.llm.client.mock import MockLLM

    loop = PydanticAgentLoop(
        client=MockLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
        max_steps=1,
    )
    assert loop._system_prompt == build_system_prompt(
        [], ctx=ToolContext(trace_id="t")
    )


def test_task_tool_imports_factory_not_agentloop_class():
    import inspect

    from manusift.tools.agent_tools import task as task_mod

    src = inspect.getsource(task_mod.TaskTool.execute)
    assert "create_agent_loop" in src
    assert "from ...agent import AgentLoop" not in src
