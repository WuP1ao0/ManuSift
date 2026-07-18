"""P0-1: PydanticAgentLoop safety nets (cost / progress / tool caps)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from manusift.agent.safety import (
    ProgressTracker,
    ToolCallGate,
    cost_for_response,
)
from manusift.llm.chat import ChatResponse
from manusift.tools.tool import ToolContext

pytest.importorskip("pydantic_ai")


class _Echo:
    name = "echo_probe"

    def description(self) -> str:
        return "echo"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        }

    def execute(self, input: dict[str, Any], ctx: ToolContext) -> str:
        return json.dumps({"ok": True, "msg": input.get("msg")})


class _ScriptLLM:
    """chat_stream script of ChatResponses."""

    name = "script"

    def __init__(self, script: list[ChatResponse]) -> None:
        self._script = list(script)
        self._i = 0

    def is_available(self) -> bool:
        return True

    def chat_stream(self, *a: Any, **k: Any):
        if self._i >= len(self._script):
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "(done)"}],
                stop_reason="end_turn",
            )
            return
        resp = self._script[self._i]
        self._i += 1
        yield resp

    def chat(self, *a: Any, **k: Any) -> ChatResponse:
        for c in self.chat_stream(*a, **k):
            return c
        return ChatResponse(
            content_blocks=[{"type": "text", "text": ""}],
            stop_reason="end_turn",
        )


def test_cost_for_response_uses_tokens():
    resp = ChatResponse(
        content_blocks=[{"type": "text", "text": "x"}],
        stop_reason="end_turn",
        usage={"prompt_tokens": 1000, "completion_tokens": 1000},
        model="mock",
    )
    c = cost_for_response(resp)
    assert c > 0


def test_tool_call_gate_duplicate_and_per_name():
    gate = ToolCallGate(max_same_tool=2, max_per_turn=10, max_bash_per_turn=5)
    assert gate.check("echo_probe", {"msg": "a"}) is None
    gate.record("echo_probe", {"msg": "a"})
    err = gate.check("echo_probe", {"msg": "a"})
    assert err is not None
    assert "duplicate" in err

    gate2 = ToolCallGate(max_same_tool=1, max_per_turn=50, max_bash_per_turn=30)
    gate2.record("echo_probe", {"msg": "1"})
    # different args still hit per-name cap
    err2 = gate2.check("echo_probe", {"msg": "2"})
    assert err2 is not None
    assert "budget_exhausted" in err2


def test_progress_tracker_no_progress():
    pt = ProgressTracker(limit=2)
    r = ChatResponse(
        content_blocks=[{"type": "text", "text": "narrating"}],
        stop_reason="end_turn",
    )
    # First call establishes the signature (streak=0).
    assert pt.update(r) is None
    # Second identical → streak=1 (still below limit 2).
    assert pt.update(r) is None
    # Third identical → streak=2 ≥ limit → fire.
    assert pt.update(r) == "no_progress"


def test_pydantic_loop_ignores_max_cost_usd():
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    expensive = ChatResponse(
        content_blocks=[
            {
                "type": "tool_use",
                "id": "c1",
                "name": "echo_probe",
                "input": {"msg": "x"},
            }
        ],
        stop_reason="tool_use",
        usage={"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
        model="mock",
    )
    done = ChatResponse(
        content_blocks=[{"type": "text", "text": "all done"}],
        stop_reason="end_turn",
    )
    client = _ScriptLLM([expensive, done])
    loop = PydanticAgentLoop(
        client=client,
        tools=[_Echo()],
        ctx=ToolContext(trace_id="t-cost"),
        system_prompt="Use tools sparingly.",
        max_steps=10,
        max_cost_usd=0.0001,  # ignored
    )
    result = loop.run("go")
    assert result.stopped_reason != "cost_cap"
    assert loop._streaming_cost_cap_reached is False


def test_pydantic_loop_tool_gate_blocks_duplicate():
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    # Turn 1: call echo; turn 2: call same again (should be denied by gate
    # inside tool execution); turn 3: end.
    script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "echo_probe",
                    "input": {"msg": "same"},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "c2",
                    "name": "echo_probe",
                    "input": {"msg": "same"},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "finished"}],
            stop_reason="end_turn",
        ),
    ]
    results: list[str] = []

    def on_tool(
        name: str, output: str, is_error: bool, tool_id: str = ""
    ) -> None:
        results.append(output)

    loop = PydanticAgentLoop(
        client=_ScriptLLM(script),
        tools=[_Echo()],
        ctx=ToolContext(trace_id="t-dup"),
        system_prompt="tools ok",
        max_steps=8,
        on_tool_result=on_tool,
    )
    loop.run("go")
    # At least one successful + one duplicate denial
    assert any('"ok": true' in r or '"ok": true' in r.replace(" ", "") for r in results) or any(
        "ok" in r and "same" in r for r in results
    )
    assert any("duplicate" in r for r in results)


def test_dual_runtime_end_turn_parity():
    """P1-3: both runtimes end with end_turn on plain MockLLM."""
    from manusift.agent.factory import create_agent_loop
    from manusift.llm.client.mock import MockLLM

    ctx = ToolContext(trace_id="parity")
    client = MockLLM()
    tools = [_Echo()]
    pyd = create_agent_loop(
        client,
        tools,
        ctx,
        runtime="pydantic_ai",
        system_prompt="reply briefly",
        max_steps=3,
    )
    leg = create_agent_loop(
        client,
        tools,
        ctx,
        runtime="legacy",
        system_prompt="reply briefly",
        max_steps=3,
    )
    r1 = pyd.run("hello")
    # fresh mock for second (MockLLM is stateless enough)
    r2 = leg.run("hello")
    assert r1.stopped_reason in ("end_turn", "stop")
    assert r2.stopped_reason in ("end_turn", "stop")
    assert r1.turns >= 1 and r2.turns >= 1
