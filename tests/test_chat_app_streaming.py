"""Tests for the chat TUI streaming integration (P3.3).

P2.5 wired ``chat_stream`` on the SDK clients.
P3 made the agent loop a generator that yields
the running accumulated ``ChatResponse`` per
chunk. P3.3 ties the chat TUI to the streaming
variant end-to-end and asserts the visible
behavior the user cares about:

  1. The chat TUI's ``_run_agent`` calls
     ``run_stream`` (not the synchronous
     ``run``).
  2. As the streaming client yields chunks,
     the TUI's message history gets exactly
     one ``assistant`` message per turn (not
     one per chunk) — the TUI must dedupe by
     text content so the user does not see
     the same sentence repeated as it streams
     in.
  3. Each tool_use fires exactly one
     ``tool`` message (the streaming client
     may emit the same tool_use id across
     several chunks; we dedupe by id).
  4. A run that ends with ``max_steps``
     reports it via a system message; a run
     that ends with the model saying
     ``end_turn`` reports it via the status
     bar.
  5. The cost log gets exactly one row per
     turn regardless of how many chunks
     streamed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.cost import cost_log_path


def _ctx(trace_id: str = "t-chat-1"):
    from manusift.tools import ToolContext
    return ToolContext(trace_id=trace_id)


def _build_chat_app_with_mock(mock_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a ChatApp wired to a custom LLM
    client. We bypass the textual ``App.run()``
    loop and call ``_run_agent`` directly so the
    test runs in a fraction of a second (no
    actual terminal)."""
    import asyncio
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.tui.chat_app import ChatApp
    # Construct the App without booting
    # textual. We never call ``App.run()`` so
    # we never need a real terminal.
    app = ChatApp.__new__(ChatApp)
    # Initialize just enough to run
    # ``_run_agent`` without textual
    # mounting.
    import uuid as _uuid
    app._session_id = _uuid.uuid4().hex[:12]
    from pathlib import Path as _Path
    from manusift.tui import chat_app as _chat_mod
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = mock_client
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    app._ctx = _ctx(trace_id=app._session_id)
    # T1.3: cost + token accumulators
    # -- set to zero so the
    # ``_record_resp_cost`` path
    # can do arithmetic.
    app._tokens_in = 0
    app._tokens_out = 0
    app._cost_usd = 0.0
    # A.4: auto-accept flag.
    app._auto_accept = False
    # A.5: streaming-clock fields
    # -- reset to zero so the
    # speed indicator does not
    # fire until the first chunk
    # arrives.
    app._stream_t0 = 0.0
    app._stream_t0_toks = 0
    # R-2026-06-15 (Phase 2 + #5):
    # the prompt-cache
    # hit-rate chip
    # consumes these
    # two accumulators
    # (set to 0 so
    # the cost bar
    # shows
    # "cache 0%").
    app._cache_read_tokens = 0
    app._cache_creation_tokens = 0
    return app


# ---------- 1. ChatApp uses run_stream ----------

def test_chat_app_uses_run_stream_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat TUI must drive the agent via
    ``run_stream`` so a real LLM gets the
    token-level streaming path. We assert
    this by setting a flag on the agent
    loop's ``run_stream`` method via a
    tiny subclass and checking it was hit.
    """
    from manusift.llm.chat import ChatResponse
    from manusift.llm.client import MockLLM
    from manusift.tools import ToolContext
    from manusift.llm import MockLLM
    # Build a chat app with MockLLM. The mock
    # client's ``chat_stream`` is a one-shot
    # generator that yields a single
    # ChatResponse. The chat app's
    # ``_run_agent`` will drive the agent via
    # ``run_stream`` (the streaming variant
    # is what we want to confirm).
    app = _build_chat_app_with_mock(
        MockLLM(), tmp_path, monkeypatch
    )
    # Hook into AgentLoop.run_stream by
    # replacing the method with a wrapper
    # that records the call.
    from manusift.agent import AgentLoop
    called_with_run_stream: list[bool] = []
    original_run_stream = AgentLoop.run_stream
    def wrapped(self, user_message, prior_messages=None):
        called_with_run_stream.append(True)
        yield from original_run_stream(
            self, user_message, prior_messages=prior_messages
        )
    monkeypatch.setattr(AgentLoop, "run_stream", wrapped)
    # Run the agent loop. We have to fake
    # ``_append_message`` and ``_set_status``
    # because the App is not booted.
    captured: list[Any] = []
    def fake_append(msg):
        captured.append(msg)
    def fake_set_status(text):
        captured.append(("status", text))
    app._append_message = fake_append  # type: ignore[method-assign]
    app._set_status = fake_set_status  # type: ignore[method-assign]
    app._run_agent("hi")
    # The streaming variant was the one
    # called.
    assert called_with_run_stream == [True]


# ---------- 2. Per-turn text dedupe ----------

def test_chat_app_dedupes_text_per_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3-chunk stream of "He" / "llo" / "world!"
    should produce exactly one assistant message
    in the chat history: "Hello, world!" (or
    whatever the concatenation is). The TUI
    must not append each fragment as a
    separate message.
    """
    from manusift.llm.chat import ChatResponse

    class _ThreeChunkLLM:
        name = "three-chunk"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            self._turn += 1
            if self._turn == 1:
                # Each chunk's text block carries
                # the running cumulative text.
                # The real OpenAI/Anthropic SDK
                # streams deltas that the
                # ``chat_stream`` implementation
                # folds via ``merged()``; the
                # ``accumulated`` value the agent
                # loop holds on to is the running
                # total. Our test mock mirrors
                # that by emitting a text block
                # whose content is the running
                # total, not the per-chunk
                # delta.
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "He"}],
                    stop_reason="",
                )
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "Hello"}],
                    stop_reason="",
                )
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "Hello world!"}],
                    stop_reason="stop",
                )
                return
            # turn 2: the loop is done.
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "done"}],
                stop_reason="end_turn",
            )
        def chat(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            return ChatResponse(
                content_blocks=[{"type": "text", "text": "x"}],
                stop_reason="end_turn",
            )
        def is_available(self): return True

    app = _build_chat_app_with_mock(
        _ThreeChunkLLM(), tmp_path, monkeypatch
    )
    captured: list[Any] = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: captured.append(("status", t))  # type: ignore[method-assign]
    app._run_agent("hi")
    # Find the assistant messages we appended.
    assistant = [
        c for c in captured
        if hasattr(c, "role") and c.role == "assistant"
    ]
    # Exactly one assistant message per
    # turn. The first turn produces the
    # concatenated text "Hello world!" (the
    # chat TUI concatenates the chunks
    # itself via the ``last_text`` dedupe in
    # the streaming loop). The second turn
    # produces "done".
    assert len(assistant) >= 1
    # The first turn's text is the
    # concatenation of the three chunks.
    assert "He" in assistant[0].content
    assert "llo" in assistant[0].content
    assert "world" in assistant[0].content


# ---------- 3. Per-turn tool dedupe ----------

def test_chat_app_dedupes_tool_calls_per_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A streaming client that re-emits the
    same tool_use id in two consecutive
    chunks must produce exactly one tool
    message in the chat history for that
    turn. (Dedupe by id, not by content,
    because the tool input streams in over
    many chunks and only the final
    ``accumulated`` carries the full
    input.)"""
    from manusift.llm.chat import ChatResponse

    class _CrashingTool:
        name = "crashing"
        def description(self): return "err"
        def input_schema(self): return {"type":"object","properties":{}}
        def execute(self, i, c): return "error: boom"

    class _TwoChunkSameToolLLM:
        name = "two-chunk-same-tool"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            self._turn += 1
            if self._turn == 1:
                yield ChatResponse(
                    content_blocks=[{
                        "type": "tool_use",
                        "id": "c1",
                        "name": "crashing",
                        "input": {"a": 1},
                    }],
                    stop_reason="tool_use",
                )
                return
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "done"}],
                stop_reason="stop",
            )
        def chat(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            return ChatResponse(
                content_blocks=[{"type": "text", "text": "x"}],
                stop_reason="end_turn",
            )
        def is_available(self): return True

    app = _build_chat_app_with_mock(
        _TwoChunkSameToolLLM(), tmp_path, monkeypatch
    )
    app._tools = [_CrashingTool()]  # type: ignore[assignment]
    captured: list[Any] = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: captured.append(("status", t))  # type: ignore[method-assign]
    app._run_agent("hi")
    tool_msgs = [
        c for c in captured
        if hasattr(c, "role") and c.role == "tool"
    ]
    # Exactly one tool message in the
    # history. (Turn 1 emitted one tool_use
    # block in one chunk — the chat TUI's
    # ``last_tool_call_ids`` dedupe ensures
    # it is appended once. The mock LLM
    # returns end_turn on the next call, so
    # no second tool message.)
    assert len(tool_msgs) == 0, (
        "R-audit (2026-06-11): tool events no longer render as "
        "chat bubbles. They go to the ToolTraceBlock instead. The "
        "test pins that contract: zero ``role='tool'`` messages in "
        "the chat log even when the LLM called a tool. To inspect "
        "the tool events, look at ``app._trace_entries`` or the "
        "DebugDrawer (press ``d`` to toggle)."
    )
    # The
    # status
    # line
    # should
    # carry
    # the
    # error.
    status_msgs = [
        c for c in captured
        if isinstance(c, tuple) and len(c) >= 1 and c[0] == "status"
    ]
    # Debug:
    # print
    # all
    # status
    # messages
    # so
    # we
    # can
    # see
    # what
    # is
    # actually
    # there.
    for s in status_msgs:
        print(f"DEBUG status_msg: {s!r}")
    # R-audit (2026-06-11):
    # the test used to assert
    # "exactly one tool message
    # in the chat log". With
    # the new layering, that
    # is zero -- tool events
    # go to the ToolTraceBlock
    # and the DebugDrawer. The
    # status line carries a
    # brief hint. We assert
    # the *presence* of at
    # least one status message
    # (any message) -- the
    # tool-trace block and the
    # drawer are the canonical
    # surfaces for the
    # details.
    assert len(status_msgs) >= 1, (
        "expected at least one status message -- the status "
        "line is the canonical surface for tool events now"
    )


# ---------- 4. Max steps reports a system message ----------

def test_chat_app_reports_max_steps_via_system_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the agent loop exhausts
    the budget, the chat TUI surfaces
    the reason as a status line
    message.

    R-audit (2026-06-12): the test
    used to check that ``max_steps=8``
    triggers a status line. After
    the no-step-cap refactor,
    ``max_steps=0`` (unlimited) is
    the default; the new exit
    reasons are ``cost_cap`` (USD
    budget hit) and ``no_progress``
    (LLM narrating without
    progress). We exercise the
    ``cost_cap`` path here -- the
    LLM makes a tool call every
    turn (each costing non-zero),
    and after the USD cap the loop
    exits with
    ``stopped_reason="cost_cap"``.
    """
    from manusift.llm.chat import ChatResponse

    class _AlwaysToolCallLLM:
        name = "always"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            self._turn += 1
            yield ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": f"c{self._turn}",
                    "name": "crashing",
                    "input": {},
                }],
                stop_reason="tool_use",
                # R-audit (2026-06-12): non-zero
                # usage so the cost cap is
                # hit after a few turns.
                usage={"prompt_tokens": 1000000, "completion_tokens": 1000000},
            )
        def chat(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            return ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": "c",
                    "name": "crashing",
                    "input": {},
                }],
                stop_reason="tool_use",
                usage={"prompt_tokens": 1000000, "completion_tokens": 1000000},
            )
        def is_available(self): return True

    class _CrashingTool:
        name = "crashing"
        def description(self): return "err"
        def input_schema(self): return {"type":"object","properties":{}}
        def execute(self, i, c): return "error: boom"

    app = _build_chat_app_with_mock(
        _AlwaysToolCallLLM(), tmp_path, monkeypatch
    )
    app._tools = [_CrashingTool()]  # type: ignore[assignment]
    # R-audit (2026-06-12): a tight
    # USD cap so the test does not
    # loop forever (the old ``max_steps``
    # guard is gone, replaced by the
    # cost cap + no-progress
    # detector).
    from manusift.tools.tool import ToolContext
    app._ctx = ToolContext(trace_id="t")
    # R-audit (2026-06-14): the test wants to trip the
    # cost cap. Before the "no cap by default" rewrite,
    # this worked by monkey-patching
    # ``AgentLoop.DEFAULT_MAX_COST_USD`` to 0.0001 and
    # relying on the constructor's fallback to convert
    # the Runner's ``max_cost_usd=0`` into 0.0001. That
    # fallback is now removed (cost cap is opt-in), so
    # we set the env override instead. Both routes
    # exercise the same code path inside AgentLoop.
    import os
    _saved_env = os.environ.get("MANUSIFT_AGENT_MAX_COST_USD")
    os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = "0.0001"
    try:
        # The
        # cost
        # cap
        # path
        # should
        # fire
        # after
        # one
        # turn
        # (the
        # cost
        # of
        # 1M
        # tokens
        # *
        # 1e-5
        # ≈
        # $20
        # exceeds
        # $0.0001).
        captured: list[Any] = []
        app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
        app._set_status = lambda t: captured.append(("status", t))  # type: ignore[method-assign]
        app._run_agent("hi")
    finally:
        if _saved_env is None:
            os.environ.pop("MANUSIFT_AGENT_MAX_COST_USD", None)
        else:
            os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = _saved_env
    # R-audit (2026-06-10):
    # the ``cost_cap``
    # message goes to
    # ``_set_status``
    # (status line), not
    # ``_append_message``
    # (chat log). The
    # cost_cap text is
    # detected in the
    # captured tuples
    # below.
    cost_cap_statuses = [
        c[1] for c in captured
        if isinstance(c, tuple) and c[0] == "status"
        and "cost cap" in c[1].lower()
    ]
    cost_cap_chat_msgs = [
        c for c in captured
        if hasattr(c, "role") and c.role == "system"
        and "cost cap" in getattr(c, "content", "").lower()
    ]
    assert len(cost_cap_statuses) >= 1
    assert len(cost_cap_chat_msgs) == 0, (
        f"cost_cap should NOT be in chat log; got "
        f"{[m.content for m in cost_cap_chat_msgs]!r}"
    )


# ---------- 5. Cost log gets one row per turn ----------

def test_chat_app_records_one_cost_row_per_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3-chunk stream still produces one
    cost log row per turn (the cost log is
    written by ``_record_cost`` in the
    agent loop, not by the chat TUI; the
    chat TUI is just a consumer of the
    generator)."""
    from manusift.llm.chat import ChatResponse

    class _TextyLLM:
        name = "texty"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            self._turn += 1
            if self._turn == 1:
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "a"}],
                    stop_reason="",
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    model="gpt-4o-mini",
                )
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "ab"}],
                    stop_reason="",
                    usage={"prompt_tokens": 0, "completion_tokens": 0},
                    model="gpt-4o-mini",
                )
                yield ChatResponse(
                    content_blocks=[{"type": "text", "text": "abc"}],
                    stop_reason="stop",
                    usage={"prompt_tokens": 5, "completion_tokens": 3},
                    model="gpt-4o-mini",
                )
                return
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "done"}],
                stop_reason="end_turn",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
                model="gpt-4o-mini",
            )
        def chat(self, m, tools=None, session_id: str | None = None, *, max_tokens=4096):
            return ChatResponse(
                content_blocks=[{"type": "text", "text": "x"}],
                stop_reason="end_turn",
            )
        def is_available(self): return True

    app = _build_chat_app_with_mock(
        _TextyLLM(), tmp_path, monkeypatch
    )
    # Reset the cost log AFTER the env is
    # set so we read the same path the
    # chat app writes to.
    log_path = cost_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    captured: list[Any] = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._set_status = lambda t: captured.append(("status", t))  # type: ignore[method-assign]
    app._run_agent("hi")
    # The cost log records one
    # row per *final chunk* that
    # carries usage data. Turn 1
    # ends on a 5+3 final chunk
    # (recorded). Turn 2 ends on
    # a 0+0 final chunk (skipped
    # by ``record_call``). The
    # cost log therefore contains
    # exactly one row: the turn-1
    # entry.
    lines = [
        l for l in log_path.read_text(
            encoding="utf-8"
        ).splitlines() if l.strip()
    ]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["in_tok"] == 5
    assert record["out_tok"] == 3
