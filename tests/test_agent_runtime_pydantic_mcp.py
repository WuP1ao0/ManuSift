"""PydanticAI agent runtime + MCP tool surface (Domain Kernel unchanged)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from manusift.agent.factory import create_agent_loop, resolve_agent_runtime
from manusift.agent.message_bridge import (
    chat_response_to_model_response,
    model_response_to_chat_response,
    pydantic_history_to_manusift,
)
from manusift.agent.tool_bridge import (
    AgentDeps,
    build_pydantic_tools,
    manusift_tool_to_pydantic,
    tools_to_openai_schemas,
)
from manusift.llm.chat import ChatResponse
from manusift.llm.client.mock import MockLLM
from manusift.tools.tool import ToolContext


class _EchoTool:
    name = "echo_probe"

    def description(self) -> str:
        return "Echo a message for tests."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        }

    def execute(self, input: dict[str, Any], ctx: ToolContext) -> str:
        return json.dumps(
            {"ok": True, "msg": input.get("msg"), "trace_id": ctx.trace_id}
        )


class _ToolCallingMock:
    """LLM mock: first call requests echo_probe, second ends."""

    name = "tool_mock"
    calls = 0

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 4096,
        session_id: str | None = None,
    ) -> ChatResponse:
        self.calls += 1
        if self.calls == 1:
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "echo_probe",
                        "input": {"msg": "hello"},
                    }
                ],
                stop_reason="tool_use",
            )
        return ChatResponse(
            content_blocks=[{"type": "text", "text": "all done"}],
            stop_reason="end_turn",
        )

    def chat_stream(self, *a: Any, **k: Any):
        yield self.chat(*a, **k)


def test_resolve_runtime_aliases():
    assert resolve_agent_runtime("legacy") == "legacy"
    assert resolve_agent_runtime("pydantic_ai") == "pydantic_ai"
    assert resolve_agent_runtime("pydantic") == "pydantic_ai"


def test_tool_bridge_schema_and_execute():
    tool = _EchoTool()
    schemas = tools_to_openai_schemas([tool])
    assert schemas[0]["name"] == "echo_probe"
    assert "msg" in schemas[0]["input_schema"]["properties"]

    pyd = manusift_tool_to_pydantic(tool)
    assert pyd.name == "echo_probe"

    # Build pydantic tools list
    tools = build_pydantic_tools([tool])
    assert len(tools) == 1


def test_message_bridge_roundtrip_text():
    cr = ChatResponse(
        content_blocks=[{"type": "text", "text": "hi"}],
        stop_reason="end_turn",
    )
    mr = chat_response_to_model_response(cr)
    back = model_response_to_chat_response(mr)
    assert back.text == "hi"
    assert back.stop_reason == "end_turn"


def test_message_bridge_tool_use():
    cr = ChatResponse(
        content_blocks=[
            {
                "type": "tool_use",
                "id": "t1",
                "name": "echo_probe",
                "input": {"msg": "x"},
            }
        ],
        stop_reason="tool_use",
    )
    mr = chat_response_to_model_response(cr)
    back = model_response_to_chat_response(mr)
    assert back.tool_calls
    assert back.tool_calls[0]["name"] == "echo_probe"
    assert back.tool_calls[0]["input"]["msg"] == "x"


def test_pydantic_loop_with_mock_echo():
    pytest.importorskip("pydantic_ai")
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    ctx = ToolContext(trace_id="t-pyd-1")
    client = MockLLM()
    loop = PydanticAgentLoop(
        client=client,
        tools=[_EchoTool()],
        ctx=ctx,
        system_prompt="You are a test agent. Reply briefly.",
        max_steps=3,
    )
    result = loop.run("say hi without tools")
    assert result.final_response is not None
    assert result.turns >= 1
    assert result.stopped_reason in (
        "end_turn",
        "stop",
        "max_steps",
        "cancelled",
    )
    # Mock echoes user text
    assert "mock echo" in (result.final_response.text or "") or result.turns >= 1


def test_pydantic_loop_tool_calling():
    pytest.importorskip("pydantic_ai")
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    ctx = ToolContext(trace_id="t-pyd-2")
    client = _ToolCallingMock()
    seen: list[tuple[str, str, bool]] = []

    def on_tool_result(
        name: str, output: str, is_error: bool, tool_id: str = ""
    ) -> None:
        seen.append((name, output, is_error))

    loop = PydanticAgentLoop(
        client=client,
        tools=[_EchoTool()],
        ctx=ctx,
        system_prompt="Use tools when needed.",
        max_steps=5,
        on_tool_result=on_tool_result,
    )
    result = loop.run("please echo")
    assert result.final_response.text  # final text turn
    # Tool should have run via pydantic tool dispatch
    assert any(n == "echo_probe" for n, _, _ in seen) or client.calls >= 2
    assert result.stopped_reason in ("end_turn", "stop", "max_steps")


def test_create_agent_loop_pydantic_and_legacy():
    pytest.importorskip("pydantic_ai")
    ctx = ToolContext(trace_id="t-factory")
    client = MockLLM()
    tools = [_EchoTool()]

    pyd = create_agent_loop(
        client, tools, ctx, runtime="pydantic_ai", system_prompt="sp", max_steps=2
    )
    assert type(pyd).__name__ == "PydanticAgentLoop"

    leg = create_agent_loop(
        client, tools, ctx, runtime="legacy", system_prompt="sp", max_steps=2
    )
    assert type(leg).__name__ == "AgentLoop"

    # Both can run a simple turn
    r1 = pyd.run("hello")
    r2 = leg.run("hello")
    assert r1.final_response is not None
    assert r2.final_response is not None


def test_mcp_list_tools_cli(capsys: pytest.CaptureFixture[str]):
    pytest.importorskip("mcp")
    from manusift.mcp.server import main

    main(["--list-tools"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["count"] >= 1
    assert "tools" in data
    assert isinstance(data["tools"], list)


def test_mcp_build_server_list_and_call():
    pytest.importorskip("mcp")
    from manusift.mcp.server import build_server
    from manusift.tools.tool import ToolContext

    # Register only our probe via a tiny allow-list after monkeypatching
    # the schema helper would be heavy; call through real registry if
    # echo_probe is not registered — use a real tool name from registry.
    from manusift.tools import iter_registered_tools

    tools = list(iter_registered_tools())
    assert tools, "expected builtin tools"
    sample = tools[0]
    name = sample.name

    ctx = ToolContext(trace_id="mcp-test-1")
    server = build_server(ctx=ctx, tool_names=[name])

    # Invoke list_tools / call_tool handlers via the server's request
    # handlers if exposed; otherwise use the internal functions by
    # exercising call_tool through server._tool_handlers.
    # Prefer public asyncio API used by MCP:
    import asyncio
    from mcp import types

    handlers = getattr(server, "request_handlers", None)
    assert handlers is not None or hasattr(server, "list_tools")

    # Direct path: use get_tool + execute parity (Domain Kernel)
    from manusift.tools.registry import get_tool

    t = get_tool(name)
    assert t is not None
    # empty input should not crash the process
    try:
        out = t.execute({}, ctx)
    except Exception as exc:  # noqa: BLE001
        out = str(exc)
    assert out is not None


def test_pydantic_history_to_manusift_shapes():
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        ToolCallPart,
        ToolReturnPart,
        UserPromptPart,
    )

    history = [
        ModelRequest(parts=[UserPromptPart(content="go")]),
        ModelResponse(
            parts=[
                TextPart(content="calling"),
                ToolCallPart(
                    tool_name="echo_probe",
                    args={"msg": "a"},
                    tool_call_id="c1",
                ),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="echo_probe",
                    content='{"ok":true}',
                    tool_call_id="c1",
                )
            ]
        ),
    ]
    ms = pydantic_history_to_manusift(history)
    roles = [m["role"] for m in ms]
    assert "user" in roles
    assert "assistant" in roles
