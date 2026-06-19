"""Tests for LLMClient.chat() with tools (Step J2).

Borrowed design from Anthropic's Messages API and the leaked
Claude Code v2.1.88 source. The AgentLoop (Step J3) will call
``client.chat(messages, tools)`` and get back a normalized
``ChatResponse``. These tests pin the wire format for each
provider, and confirm the mock is enough to exercise the
agent loop end-to-end.

The tests use ``monkeypatch.setattr`` to swap the lazy SDK
client method with a fake that returns a pre-built response.
This is the same testing discipline used by the openai/anthropic
SDKs' own test suites.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from manusift.config import Settings
from manusift.llm import MockLLM
from manusift.llm.chat import ChatResponse
from manusift.llm.client import AnthropicLLM, OpenAILLM


# ---------- 1. ChatResponse shape ----------

def test_chat_response_text_concatenation() -> None:
    r = ChatResponse(
        content_blocks=[
            {"type": "text", "text": "Hello "},
            {"type": "tool_use", "name": "x", "id": "i", "input": {}},
            {"type": "text", "text": "world"},
        ]
    )
    assert r.text == "Hello world"


def test_chat_response_tool_calls_filter() -> None:
    r = ChatResponse(
        content_blocks=[
            {"type": "text", "text": "x"},
            {"type": "tool_use", "id": "i1", "name": "a", "input": {}},
            {"type": "tool_use", "id": "i2", "name": "b", "input": {}},
        ]
    )
    tcs = r.tool_calls
    assert len(tcs) == 2
    assert tcs[0]["name"] == "a"
    assert tcs[1]["name"] == "b"


# ---------- 2. MockLLM.chat is end-to-end testable ----------

def test_mock_chat_echoes_last_user_message() -> None:
    client = MockLLM()
    resp = client.chat(
        messages=[{"role": "user", "content": "analyze this paper"}]
    )
    assert resp.stop_reason == "end_turn"
    assert "analyze this paper" in resp.text


def test_mock_chat_handles_no_user_message() -> None:
    client = MockLLM()
    resp = client.chat(messages=[{"role": "system", "content": "be helpful"}])
    assert resp.stop_reason == "end_turn"
    assert resp.tool_calls == []


# ---------- 3. OpenAI SDK path ----------

def _openai_chat_response() -> Any:
    """A real-shape OpenAI ChatCompletion. We use the
    real ``openai`` types so the client code's
    attribute access works without surprises."""
    from openai.types.chat import ChatCompletion
    from openai.types.chat.chat_completion import Choice
    from openai.types.chat.chat_completion_message import ChatCompletionMessage
    from openai.types.chat.chat_completion_message_tool_call import (
        ChatCompletionMessageToolCall,
        Function,
    )
    from openai.types.completion_usage import CompletionUsage

    return ChatCompletion(
        id="chatcmpl-1",
        object="chat.completion",
        created=0,
        model="gpt-test",
        choices=[
            Choice(
                index=0,
                finish_reason="tool_calls",
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id="call_abc123",
                            type="function",
                            function=Function(
                                name="metadata",
                                arguments=json.dumps({"trace_id": "t-1"}),
                            ),
                        )
                    ],
                ),
            )
        ],
        usage=CompletionUsage(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        ),
    )


def test_openai_chat_translates_tool_call_to_content_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """We monkeypatch ``_sdk`` to return a fake OpenAI
    client whose ``chat.completions.create`` returns a
    canned response. This is the same pattern the
    openai SDK's own test suite uses."""
    captured: dict[str, Any] = {}

    @dataclass
    class FakeCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _openai_chat_response()

    @dataclass
    class FakeChat:
        completions: Any = field(default_factory=FakeCompletions)

    @dataclass
    class FakeSDK:
        chat: Any = field(default_factory=FakeChat)

    settings = Settings(openai_api_key="test-key", openai_base_url="https://mock")
    client = OpenAILLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: FakeSDK())

    resp = client.chat(
        messages=[{"role": "user", "content": "analyze"}],
        tools=[
            {
                "name": "metadata",
                "description": "...",
                "input_schema": {
                    "type": "object",
                    "properties": {"trace_id": {"type": "string"}},
                    "required": ["trace_id"],
                },
            }
        ],
    )
    # The body sent to the SDK must wrap our input_schema
    # in {"type": "function", "function": {"parameters": ...}}.
    tools_arg = captured["tools"]
    assert tools_arg[0]["type"] == "function"
    assert tools_arg[0]["function"]["name"] == "metadata"
    assert "parameters" in tools_arg[0]["function"]
    # The response is normalized to our flat shape.
    assert resp.stop_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc["name"] == "metadata"
    assert tc["input"] == {"trace_id": "t-1"}
    assert tc["id"] == "call_abc123"


def test_openai_chat_with_no_tools_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plain text chat with no tools. Confirms the
    no-tools code path still works through the SDK."""

    @dataclass
    class FakeMessage:
        content: str = "hello"
        tool_calls: list = field(default_factory=list)

    @dataclass
    class FakeChoice:
        finish_reason: str = "stop"
        message: Any = field(default_factory=FakeMessage)

    @dataclass
    class FakeResp:
        choices: list = field(default_factory=lambda: [FakeChoice()])
        usage: Any = None

    @dataclass
    class FakeCompletions:
        def create(self, **kwargs: Any) -> Any:
            return FakeResp()

    @dataclass
    class FakeChat:
        completions: Any = field(default_factory=FakeCompletions)

    @dataclass
    class FakeSDK:
        chat: Any = field(default_factory=FakeChat)

    settings = Settings(openai_api_key="test-key", openai_base_url="https://mock")
    client = OpenAILLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: FakeSDK())

    resp = client.chat(messages=[{"role": "user", "content": "hi"}])
    assert resp.stop_reason == "stop"
    assert resp.text == "hello"
    assert resp.tool_calls == []


def test_openai_chat_without_api_key_returns_soft_response() -> None:
    settings = Settings(openai_api_key="")
    client = OpenAILLM(settings)
    resp = client.chat(messages=[{"role": "user", "content": "x"}])
    assert resp.stop_reason == "end_turn"
    assert "no api key" in resp.text.lower()


# ---------- 4. Anthropic SDK path ----------

def _anthropic_message_response() -> Any:
    """A real-shape Anthropic Message. We use ``BaseModel``
    from pydantic so the response object has the same
    attribute access our client code uses."""
    from anthropic.types import (
        Message,
        TextBlock,
        ToolUseBlock,
        Usage,
    )

    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-test",
        content=[
            TextBlock(type="text", text="Let me run metadata."),
            ToolUseBlock(
                type="tool_use",
                id="toolu_abc123",
                name="metadata",
                input={"trace_id": "t-2"},
            ),
        ],
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def test_anthropic_chat_passes_through_content_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    @dataclass
    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return _anthropic_message_response()

    @dataclass
    class FakeSDK:
        messages: Any = field(default_factory=FakeMessages)

    settings = Settings(
        anthropic_api_key="k", anthropic_base_url="https://mock"
    )
    client = AnthropicLLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: FakeSDK())

    resp = client.chat(
        messages=[{"role": "user", "content": "analyze"}],
        tools=[
            {
                "name": "metadata",
                "description": "...",
                "input_schema": {
                    "type": "object",
                    "properties": {"trace_id": {"type": "string"}},
                    "required": ["trace_id"],
                },
            }
        ],
    )
    # Body must NOT have a role=system inside messages
    # (Anthropic has a top-level system field).
    assert "system" not in captured
    assert captured["messages"] == [
        {"role": "user", "content": "analyze"}
    ]
    assert captured["tools"][0]["name"] == "metadata"
    # Response normalized.
    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["id"] == "toolu_abc123"
    assert resp.tool_calls[0]["name"] == "metadata"


def test_anthropic_chat_promotes_system_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """role=system messages must be promoted to the
    top-level ``system`` field on the body."""
    captured: dict[str, Any] = {}

    @dataclass
    class FakeMessage:
        content: list = field(default_factory=list)
        stop_reason: str = "end_turn"

    @dataclass
    class FakeMessages:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return FakeMessage()

    @dataclass
    class FakeSDK:
        messages: Any = field(default_factory=FakeMessages)

    settings = Settings(
        anthropic_api_key="k", anthropic_base_url="https://mock"
    )
    client = AnthropicLLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: FakeSDK())

    client.chat(
        messages=[
            {"role": "system", "content": "You are a paper-integrity checker."},
            {"role": "user", "content": "analyze"},
        ]
    )
    body = captured
    # R-2026-06-15 (Phase 0 + 3c):
    # Anthropic's system
    # prompt is now a list
    # of content blocks
    # (not a bare string)
    # so we can attach
    # ``cache_control`` to
    # the system block and
    # get prompt caching
    # for free. The text
    # content of the
    # first block is what
    # the LLM sees as the
    # system prompt.
    system_blocks = body["system"]
    assert isinstance(system_blocks, list)
    assert len(system_blocks) == 1
    assert (
        system_blocks[0]["text"]
        == "You are a paper-integrity checker."
    )
    # The block carries a
    # ``cache_control``
    # marker (default
    # ``ephemeral``).
    assert system_blocks[0].get(
        "cache_control"
    ) == {"type": "ephemeral"}
    roles = [m["role"] for m in body["messages"]]
    assert "system" not in roles
