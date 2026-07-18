"""P2: mid-run pydantic stream + legacy modularization smoke."""
from __future__ import annotations

from typing import Any

import pytest

from manusift.llm.chat import ChatResponse
from manusift.tools.tool import ToolContext


class _TwoChunkLLM:
    name = "two-chunk"

    def is_available(self) -> bool:
        return True

    def chat_stream(self, *a: Any, **k: Any):
        yield ChatResponse(
            content_blocks=[{"type": "text", "text": "Hel"}],
            stop_reason="",
        )
        yield ChatResponse(
            content_blocks=[{"type": "text", "text": "lo!"}],
            stop_reason="end_turn",
        )

    def chat(self, *a: Any, **k: Any) -> ChatResponse:
        return ChatResponse(
            content_blocks=[{"type": "text", "text": "Hello!"}],
            stop_reason="end_turn",
        )


def test_legacy_audit_emit_helper():
    from manusift.agent.legacy_audit import emit_tool_audit

    rows: list[dict] = []
    emit_tool_audit(
        rows.append,
        tool_name="t",
        tool_input={"a": 1},
        output="ok",
        error=None,
        duration_ms=12,
    )
    assert len(rows) == 1
    assert rows[0]["tool"] == "t"
    assert rows[0]["ok"] is True
    assert rows[0]["duration_ms"] == 12


def test_legacy_cost_delegates_to_safety():
    from manusift.agent.legacy_loop import AgentLoop
    from manusift.llm.client.mock import MockLLM

    loop = AgentLoop(
        client=MockLLM(),
        tools=[],
        ctx=ToolContext(trace_id="c"),
        max_steps=1,
    )
    resp = ChatResponse(
        content_blocks=[{"type": "text", "text": "x"}],
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        model="mock",
    )
    c = loop._cost_for_response(resp)
    assert c > 0


def test_pydantic_mid_run_yields_chunks_and_turn():
    pytest.importorskip("pydantic_ai")
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    loop = PydanticAgentLoop(
        client=_TwoChunkLLM(),
        tools=[],
        ctx=ToolContext(trace_id="stream"),
        system_prompt="be brief",
        max_steps=3,
    )
    yields = list(loop.run_stream("hi"))
    # At least one live chunk (partial) and one turn snapshot.
    assert len(yields) >= 2
    texts = [y.text for y in yields if y.text]
    # Accumulated stream should eventually contain Hello
    assert any("Hel" in t or "lo" in t or "Hello" in t for t in texts)


def test_pydantic_run_still_returns_result():
    pytest.importorskip("pydantic_ai")
    from manusift.agent.pydantic_loop import PydanticAgentLoop

    loop = PydanticAgentLoop(
        client=_TwoChunkLLM(),
        tools=[],
        ctx=ToolContext(trace_id="stream2"),
        system_prompt="be brief",
        max_steps=3,
    )
    result = loop.run("hi")
    assert result.final_response is not None
    assert result.turns >= 1
    assert "lo" in (result.final_response.text or "") or "Hel" in (
        result.final_response.text or ""
    )


def test_legacy_warn_suppressed_under_pytest():
    """_warn_legacy_once is a no-op under pytest env."""
    from manusift.agent import legacy_loop as ll

    ll._legacy_warned = False
    # Should not raise; under pytest env it returns early.
    ll._warn_legacy_once()
    # Still false because pytest suppressed
    assert ll._legacy_warned is False
