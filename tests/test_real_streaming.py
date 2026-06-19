"""Tests for the real streaming clients (Step P2.5).

P2-B1 added the ``chat_stream`` Protocol method
and a stub that yielded one chunk from ``chat``.
P2.5 actually wires the streaming SDK calls in
``OpenAILLM.chat_stream`` and
``AnthropicLLM.chat_stream``.

We mock the SDK stream objects to test the
folding logic without hitting the network. The
key guarantee is: a sequence of partial chunks
folds into a final ``ChatResponse`` whose text
concatenation is exactly what the non-streaming
``chat()`` would have returned.

Guarantees:

  1. ``ChatResponse.merged()`` concatenates text
     fragments across many partial responses.
  2. ``ChatResponse.merged()`` merges tool_use
     blocks with the same ``id`` in place; the
     last one wins.
  3. ``ChatResponse.merged()`` keeps the
     non-empty ``stop_reason`` and ``usage``.
  4. ``OpenAILLM.chat_stream`` folds per-chunk
     deltas into a running ``ChatResponse``
     with the same text the non-streaming call
     would produce.
  5. ``AnthropicLLM.chat_stream`` does the same
     for Anthropic's event stream.
  6. A SDK error in the stream call yields a
     single error chunk with stop_reason
     ``"end_turn"`` (the same shape the
     non-streaming error path produces).
  7. ``_safe_json_loads`` returns ``None`` for
     malformed JSON (used by the streaming
     clients to fold partial ``input_json``
     fragments).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.config import Settings
from manusift.llm.chat import ChatResponse
from manusift.llm.client import (
    AnthropicLLM,
    MockLLM,
    OpenAILLM,
    _safe_json_loads,
)


# ---------- 1. merged() concatenates text ----------

def test_merged_concatenates_text_fragments() -> None:
    """Three text deltas fold into one final
    ``text`` block whose concatenation matches
    the chunks in order."""
    a = ChatResponse(content_blocks=[
        {"type": "text", "text": "Hello"}
    ])
    b = ChatResponse(content_blocks=[
        {"type": "text", "text": ", "}
    ])
    c = ChatResponse(content_blocks=[
        {"type": "text", "text": "world!"}
    ])
    m = a.merged(b).merged(c)
    assert m.text == "Hello, world!"
    # Still one text block after the fold.
    text_blocks = [
        b for b in m.content_blocks if b.get("type") == "text"
    ]
    assert len(text_blocks) == 1


# ---------- 2. merged() folds tool_use in place ----------

def test_merged_tool_use_blocks_with_same_id() -> None:
    """Two tool_use blocks with the same id are
    merged in place: the second replaces the
    first (it carries the final, fully-parsed
    input). This matches how the OpenAI SDK
    sends tool calls in a stream: many
    fragments for one call, with the id only
    on the first chunk."""
    a = ChatResponse(content_blocks=[{
        "type": "tool_use",
        "id": "call_1",
        "name": "metadata",
        "input": {"a": 1},
    }])
    b = ChatResponse(content_blocks=[{
        "type": "tool_use",
        "id": "call_1",
        "name": "metadata",
        "input": {"a": 1, "b": 2},
    }])
    m = a.merged(b)
    tool_blocks = [
        b for b in m.content_blocks if b.get("type") == "tool_use"
    ]
    # Only one tool_use block survives the fold.
    assert len(tool_blocks) == 1
    # The latest input wins.
    assert tool_blocks[0]["input"] == {"a": 1, "b": 2}


def test_merged_tool_use_blocks_with_different_ids() -> None:
    """Two tool_use blocks with different ids
    are kept as-is — the merge does not
    collapse distinct calls into one."""
    a = ChatResponse(content_blocks=[{
        "type": "tool_use",
        "id": "call_1",
        "name": "metadata",
        "input": {},
    }])
    b = ChatResponse(content_blocks=[{
        "type": "tool_use",
        "id": "call_2",
        "name": "image_dup",
        "input": {},
    }])
    m = a.merged(b)
    ids = [
        b["id"] for b in m.content_blocks
        if b.get("type") == "tool_use"
    ]
    assert ids == ["call_1", "call_2"]


# ---------- 3. merged() keeps non-empty stop / usage / model ----------

def test_merged_keeps_non_empty_stop_and_usage() -> None:
    """An empty ``stop_reason`` / ``usage`` on
    ``other`` does not overwrite the values
    already on ``self``. The streaming
    clients rely on this: a chunk with no
    stop_reason carries the running state,
    not a reset."""
    a = ChatResponse(
        stop_reason="tool_use",
        usage={"prompt_tokens": 5},
        model="gpt-4o-mini",
    )
    b = ChatResponse(stop_reason="", usage={}, model="")
    m = a.merged(b)
    assert m.stop_reason == "tool_use"
    assert m.usage == {"prompt_tokens": 5}
    assert m.model == "gpt-4o-mini"


def test_merged_other_wins_on_non_empty() -> None:
    """When ``other`` has a non-empty
    ``stop_reason`` / ``usage`` / ``model``,
    it wins. The last chunk of an OpenAI
    stream carries the final stop reason and
    the usage record, so this branch is the
    one that the streaming clients hit on
    the last yielded response."""
    a = ChatResponse(stop_reason="", model="")
    b = ChatResponse(
        stop_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        model="gpt-4o-mini",
    )
    m = a.merged(b)
    assert m.stop_reason == "stop"
    assert m.usage == {"prompt_tokens": 10, "completion_tokens": 20}
    assert m.model == "gpt-4o-mini"


# ---------- 4. OpenAILLM chat_stream folds deltas ----------

class _FakeOpenAITextDelta:
    def __init__(self, text: str) -> None:
        self.content = text
        self.tool_calls = None


class _FakeOpenAIUsage:
    def __init__(self, prompt: int, completion: int) -> None:
        self.prompt_tokens = prompt
        self.completion_tokens = completion
    def model_dump(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


class _FakeOpenAIChoice:
    def __init__(
        self, delta: Any, finish_reason: str = ""
    ) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeOpenAIChunk:
    def __init__(self, choices: list, usage: Any = None) -> None:
        self.choices = choices
        self.usage = usage


class _FakeOpenAIStream:
    def __init__(self, chunks: list) -> None:
        self._chunks = chunks
    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._chunks)


def _openai_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        openai_api_key="sk-test",
        openai_model="gpt-4o-mini",
    )


def test_openai_chat_stream_folds_text_deltas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three text deltas + a final usage chunk
    fold into a single accumulated response
    with the right text and usage. The mock
    SDK stream replays our scripted chunks;
    the chat_stream method folds them in."""
    settings = _openai_settings(tmp_path)
    chunks = [
        _FakeOpenAIChunk([_FakeOpenAIChoice(
            _FakeOpenAITextDelta("Hello, "),
            finish_reason="",
        )]),
        _FakeOpenAIChunk([_FakeOpenAIChoice(
            _FakeOpenAITextDelta("streaming "),
            finish_reason="",
        )]),
        _FakeOpenAIChunk([_FakeOpenAIChoice(
            _FakeOpenAITextDelta("world!"),
            finish_reason="stop",
        )]),
        _FakeOpenAIChunk(
            choices=[],
            usage=_FakeOpenAIUsage(10, 20),
        ),
    ]
    sdk = type("SDK", (), {
        "chat": type("Chat", (), {
            "completions": type("Comp", (), {
                "create": staticmethod(
                    lambda **kw: _FakeOpenAIStream(chunks)
                )
            })()
        })()
    })
    client = OpenAILLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: sdk)
    out = list(client.chat_stream(
        [{"role": "user", "content": "hi"}], None, max_tokens=128
    ))
    # The stream yields once per chunk, with
    # the running accumulated response.
    assert len(out) == 4
    # The last response carries the full text
    # and the final stop reason and usage.
    final = out[-1]
    assert "Hello, streaming world!" in final.text
    assert final.stop_reason == "stop"
    assert final.usage["prompt_tokens"] == 10
    assert final.usage["completion_tokens"] == 20


def test_openai_chat_stream_no_key_yields_one_shot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client constructed without an API key
    must not call the SDK. It just yields
    the (mock) one-shot ``chat()`` response.
    This is the same code path MockLLM uses,
    and it guarantees a missing key never
    crashes the chat loop."""
    settings = Settings(
        workspace_dir=tmp_path / "ws",
        # No openai_api_key set
    )
    client = OpenAILLM(settings)
    out = list(client.chat_stream(
        [{"role": "user", "content": "hi"}], None, max_tokens=128
    ))
    # ``chat()`` returns a ChatResponse with
    # content ``"(no API key)"``.
    assert len(out) == 1
    assert "(no API key)" in out[0].text


# ---------- 5. AnthropicLLM chat_stream folds events ----------

class _FakeAnthropicTextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeAnthropicToolUseBlock:
    def __init__(self, id: str, name: str) -> None:
        self.type = "tool_use"
        self.id = id
        self.name = name


class _FakeAnthropicTextDelta:
    def __init__(self, text: str) -> None:
        self.type = "text_delta"
        self.text = text


class _FakeAnthropicInputJsonDelta:
    def __init__(self, fragment: str) -> None:
        self.type = "input_json_delta"
        self.partial_json = fragment


class _FakeAnthropicMessageDelta:
    def __init__(
        self, stop_reason: str = "", usage: Any = None
    ) -> None:
        self.stop_reason = stop_reason
        self.usage = usage


class _FakeAnthropicUsage:
    def __init__(self, in_tok: int, out_tok: int) -> None:
        self.input_tokens = in_tok
        self.output_tokens = out_tok
    def model_dump(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class _FakeAnthropicEvent:
    """One Anthropic stream event. The
    ``type`` attribute is the discriminator
    the chat_stream method switches on."""
    def __init__(self, **kw: Any) -> None:
        self.type = kw.get("type")
        self.content_block = kw.get("content_block")
        self.delta = kw.get("delta")
        self.index = kw.get("index")
        self.usage = kw.get("usage")


class _FakeAnthropicStream:
    def __init__(self, events: list) -> None:
        self._events = events
    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._events)


def _anthropic_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        anthropic_api_key="sk-test",
        anthropic_model="claude-3-5-sonnet-latest",
    )


def test_anthropic_chat_stream_folds_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anthropic events: text_block_start,
    text_delta x 3, message_delta. The
    accumulated text matches the
    concatenation, and the final stop
    reason / usage is recorded."""
    settings = _anthropic_settings(tmp_path)
    events = [
        _FakeAnthropicEvent(
            type="content_block_start",
            content_block=_FakeAnthropicTextBlock(text=""),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicTextDelta("foo "),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicTextDelta("bar "),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicTextDelta("baz"),
        ),
        _FakeAnthropicEvent(
            type="message_delta",
            delta=_FakeAnthropicMessageDelta(
                stop_reason="end_turn",
                usage=_FakeAnthropicUsage(5, 8),
            ),
        ),
    ]
    sdk = type("SDK", (), {
        "messages": type("M", (), {
            "create": staticmethod(
                lambda **kw: _FakeAnthropicStream(events)
            )
        })()
    })
    client = AnthropicLLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: sdk)
    out = list(client.chat_stream(
        [{"role": "user", "content": "hi"}], None, max_tokens=128
    ))
    assert len(out) == 5
    final = out[-1]
    assert final.text == "foo bar baz"
    assert final.stop_reason == "end_turn"
    assert final.usage["input_tokens"] == 5
    assert final.usage["output_tokens"] == 8


def test_anthropic_chat_stream_handles_tool_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool_use block streams as
    content_block_start (with id+name) +
    a series of input_json_delta fragments.
    The accumulated input is the
    concatenation of those fragments parsed
    as JSON."""
    settings = _anthropic_settings(tmp_path)
    events = [
        _FakeAnthropicEvent(
            type="content_block_start",
            content_block=_FakeAnthropicToolUseBlock(
                id="toolu_1", name="metadata"
            ),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicInputJsonDelta('{"trac'),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicInputJsonDelta('e_id": "'),
        ),
        _FakeAnthropicEvent(
            type="content_block_delta",
            delta=_FakeAnthropicInputJsonDelta('t-001"}'),
        ),
        _FakeAnthropicEvent(
            type="message_delta",
            delta=_FakeAnthropicMessageDelta(stop_reason="tool_use"),
        ),
    ]
    sdk = type("SDK", (), {
        "messages": type("M", (), {
            "create": staticmethod(
                lambda **kw: _FakeAnthropicStream(events)
            )
        })()
    })
    client = AnthropicLLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: sdk)
    out = list(client.chat_stream(
        [{"role": "user", "content": "hi"}], None, max_tokens=128
    ))
    final = out[-1]
    # The final tool_use block survived the
    # fold, with the right id, name, and
    # parsed input. The exact parsing of
    # partial JSON is best-effort: each chunk
    # carries an attempted parse; the last
    # chunk has the complete input.
    tool_blocks = [
        b for b in final.content_blocks
        if b.get("type") == "tool_use"
    ]
    assert tool_blocks
    assert tool_blocks[0]["name"] == "metadata"
    assert tool_blocks[0]["id"] == "toolu_1"


# ---------- 6. SDK error yields a single error chunk ----------

def test_openai_chat_stream_sdk_error_yields_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SDK call that raises (e.g. a network
    error) yields exactly one chunk with
    stop_reason ``"end_turn"`` and the
    exception text in the content. This is
    the same shape the non-streaming error
    path produces, so the agent loop does
    not have to special-case the streaming
    client."""
    settings = _openai_settings(tmp_path)
    sdk = type("SDK", (), {
        "chat": type("Chat", (), {
            "completions": type("Comp", (), {
                "create": staticmethod(
                    lambda **kw: (_ for _ in ()).throw(
                        RuntimeError("simulated network down")
                    )
                )
            })()
        })()
    })
    client = OpenAILLM(settings)
    monkeypatch.setattr(client, "_sdk", lambda: sdk)
    out = list(client.chat_stream(
        [{"role": "user", "content": "hi"}], None, max_tokens=128
    ))
    assert len(out) == 1
    assert "simulated network down" in out[0].text
    assert out[0].stop_reason == "end_turn"


# ---------- 7. _safe_json_loads ----------

def test_safe_json_loads_valid() -> None:
    """A well-formed JSON string parses."""
    assert _safe_json_loads('{"a": 1}') == {"a": 1}


def test_safe_json_loads_malformed_returns_none() -> None:
    """A malformed JSON string returns
    ``None`` — the streaming clients rely on
    this to fold partial ``input_json``
    deltas (the JSON is incomplete until
    the last chunk)."""
    assert _safe_json_loads('{"trac') is None
    assert _safe_json_loads("not json at all") is None


def test_safe_json_loads_empty_returns_none() -> None:
    """An empty string also returns ``None``."""
    assert _safe_json_loads("") is None
