"""P1-5: TaskTool uses factory; pydantic loop supports interrupt."""
from __future__ import annotations

import inspect

import pytest

from manusift.tools.tool import ToolContext


def test_task_tool_source_uses_factory_not_agentloop_ctor():
    from manusift.tools.agent_tools.task import TaskTool

    src = inspect.getsource(TaskTool.execute)
    assert "create_agent_loop" in src
    assert "AgentLoop(" not in src


def test_pydantic_loop_interrupt_flag():
    pytest.importorskip("pydantic_ai")
    from manusift.agent.pydantic_loop import PydanticAgentLoop
    from manusift.llm.client.mock import MockLLM

    loop = PydanticAgentLoop(
        client=MockLLM(),
        tools=[],
        ctx=ToolContext(trace_id="int"),
        system_prompt="hi",
        max_steps=2,
    )
    assert loop._interrupt_requested is False
    loop.interrupt()
    assert loop._interrupt_requested is True
    # Parent interrupt signal is polled each model turn
    parent_flag = {"stop": False}

    loop2 = PydanticAgentLoop(
        client=MockLLM(),
        tools=[],
        ctx=ToolContext(trace_id="int2"),
        system_prompt="hi",
        max_steps=2,
        parent_interrupt_signal=lambda: parent_flag["stop"],
    )
    parent_flag["stop"] = True
    result = loop2.run("hi")
    assert result.stopped_reason in ("cancelled", "end_turn")
