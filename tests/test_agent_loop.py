"""Tests for the AgentLoop (Step J3).

Borrowed design from the leaked Claude Code v2.1.88 source.
We exercise the loop with a controllable mock LLM (the
``MockLLM`` from J2) and confirm:

  * A short user message with no tool calls finishes in
    one turn and reports ``end_turn``.
  * A scripted LLM that wants a tool gets the tool called
    and the result fed back in.
  * The loop stops at ``max_steps`` to prevent runaway
    tool-calling (cost guard).
  * Tool execution errors are returned to the LLM as a
    string, not raised.
  * The full message transcript is preserved on the
    AgentLoopResult for the caller to save or display.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from manusift.agent import AgentLoop, AgentLoopResult
from manusift.llm import MockLLM
from manusift.llm.chat import ChatResponse
from manusift.tools import ToolContext, get_tool, tool_names


# ---------- helpers ----------

class ScriptedLLM:
    """A controllable LLM that returns a fixed sequence of
    ChatResponse objects. Each call to ``chat`` pops the
    next scripted response; when the script is empty,
    returns end_turn with the accumulated text."""

    def __init__(self, script: list[ChatResponse]) -> None:
        self._script = list(script)
        self._call_count = 0
        self.captured_messages: list[list[dict[str, Any]]] = []
        self.captured_tools: list[list[dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "scripted"

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding: Any) -> Any:
        return None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None, session_id: str | None = None,
        *,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        self._call_count += 1
        self.captured_messages.append(list(messages))
        self.captured_tools.append(list(tools or []))
        if self._script:
            return self._script.pop(0)
        return ChatResponse(
            content_blocks=[{"type": "text", "text": "[end of script]"}],
            stop_reason="end_turn",
        )


def _ctx() -> ToolContext:
    return ToolContext(trace_id="t-agent")


# ---------- 1. Single-turn finish ----------

def test_loop_finishes_after_one_text_response() -> None:
    """A simple user message that the LLM answers with
    text only (no tool calls) finishes in one turn with
    stop_reason end_turn. The transcript contains the
    system + user + assistant messages."""
    script = [
        ChatResponse(
            content_blocks=[{"type": "text", "text": "Hello, paper."}],
            stop_reason="end_turn",
        )
    ]
    llm = ScriptedLLM(script)
    loop = AgentLoop(llm, tools=[], ctx=_ctx())
    result = loop.run("analyze this paper")

    assert isinstance(result, AgentLoopResult)
    assert result.turns == 1
    assert result.stopped_reason == "end_turn"
    assert result.final_response.text == "Hello, paper."
    # The transcript is the system + user + assistant.
    assert len(result.messages) == 3
    assert result.messages[0]["role"] == "system"
    assert result.messages[1]["role"] == "user"
    assert result.messages[2]["role"] == "assistant"


# ---------- 2. The system prompt lists the available tools ----------

def test_system_prompt_includes_tool_names() -> None:
    """Per the leaked Claude Code source: the system
    prompt tells the model which tools exist. We assert
    that the LLMClient received a system message that
    contains every registered tool name."""
    script = [
        ChatResponse(
            content_blocks=[{"type": "text", "text": "ok"}],
            stop_reason="end_turn",
        )
    ]
    llm = ScriptedLLM(script)
    tools = [get_tool("metadata"), get_tool("image_dup")]
    AgentLoop(llm, tools=tools, ctx=_ctx()).run("hi")
    sys_msg = llm.captured_messages[0][0]
    assert sys_msg["role"] == "system"
    assert "metadata" in sys_msg["content"]
    assert "image_dup" in sys_msg["content"]


def test_system_prompt_direct_path_review_requires_ingest_detectors_and_html_report() -> None:
    """The default agent contract for a pasted PDF path should
    match the R-2026-06-14 rewrite: the prompt instructs
    the LLM to call ``ingest_from_path`` first, use the
    returned ``trace_id`` for every subsequent call (not
    derive one from the basename), attach companion data
    via ``data_paths``, query the data sources, and end
    a deep review with exactly one ``render_report`` call
    that writes ``report.html``.
    """
    script = [
        ChatResponse(
            content_blocks=[{"type": "text", "text": "ok"}],
            stop_reason="end_turn",
        )
    ]
    llm = ScriptedLLM(script)
    tools = [
        get_tool("ingest_from_path"),
        get_tool("metadata"),
        get_tool("render_report"),
    ]
    AgentLoop(llm, tools=tools, ctx=_ctx()).run("hi")

    sys_prompt = llm.captured_messages[0][0]["content"]
    # Hard contract: path -> ingest -> trace_id.
    assert "ingest_from_path" in sys_prompt
    assert "trace_id" in sys_prompt
    # No basename-derived trace_id.
    assert (
        "basename, hash, or guess" in sys_prompt
        or "do not derive a trace_id from the pdf" in sys_prompt.lower()
    )
    # Companion data must be passed via data_paths.
    assert "data_paths" in sys_prompt
    # Source data must be queried.
    assert "list_data_sources" in sys_prompt
    assert "read_data_source" in sys_prompt
    # Deep review ends with exactly one render_report.
    assert "render_report" in sys_prompt
    # HTML report is the canonical artefact.
    assert "report.html" in sys_prompt
    # The legacy "basename (without .pdf) as trace_id"
    # phrase is gone -- it was the old anti-pattern
    # disclaimer.
    assert "basename (without .pdf) as trace_id" not in sys_prompt


# ---------- 3. Tool call then finish ----------

def test_loop_executes_tool_and_returns_result_to_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The LLM first asks to call the metadata tool, then
    on the second turn sees the tool result and answers.
    The loop should call the tool exactly once, with the
    trace_id from the LLM's input, and the final answer
    should be the second scripted response."""
    # Lay down a workspace with the PDF the tool expects.
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    import fitz  # type: ignore[import-not-found]
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello")
    pdf_path = tmp_path / "orig.pdf"
    pdf.save(str(pdf_path))
    pdf.close()
    tid = "t-agent"
    job_dir = tmp_path / tid
    job_dir.mkdir()
    (job_dir / "original.pdf").write_bytes(pdf_path.read_bytes())

    script = [
        ChatResponse(
            content_blocks=[
                {"type": "text", "text": "running metadata"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "metadata",
                    "input": {"trace_id": "t-agent"},
                },
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "done!"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    tools = [get_tool("metadata")]
    result = AgentLoop(llm, tools=tools, ctx=_ctx()).run("analyze")

    assert result.turns == 2
    assert result.stopped_reason == "end_turn"
    assert result.final_response.text == "done!"
    # The tool result was fed back to the LLM on turn 2.
    # The captured_messages[1] is the message list as
    # sent to the LLM on turn 2: system + user + assistant
    # (with tool_use) + user (with tool_result).
    msgs_turn2 = llm.captured_messages[1]
    assert msgs_turn2[0]["role"] == "system"
    assert msgs_turn2[1]["role"] == "user"
    assert msgs_turn2[2]["role"] == "assistant"
    assert msgs_turn2[3]["role"] == "user"
    tool_result_block = msgs_turn2[3]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "call_1"
    # The tool result is a JSON string in the unified
    # ToolResult envelope; the detector payload lives
    # under ``result``.
    parsed = json.loads(tool_result_block["content"])
    assert parsed["trace_id"] == "t-agent"
    assert parsed["tool_name"] == "metadata"
    assert parsed["ok"] is True
    assert "findings" in parsed["result"]


def test_pre_canned_path_calls_prefer_loop_tool_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deterministic path pre-processing should execute the
    same local tool list that is exposed to the LLM, not a
    separate global registry lookup.
    """

    class LocalIngestTool:
        name = "ingest_from_path"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def description(self) -> str:
            return "local ingest"

        def input_schema(self) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }

        def execute(
            self, input: dict[str, Any], ctx: ToolContext
        ) -> str:
            self.calls.append(dict(input))
            return json.dumps(
                {
                    "ok": True,
                    "trace_id": "local-trace",
                    "path": input["path"],
                },
                ensure_ascii=False,
            )

    def _global_lookup_should_not_run(name: str):
        raise AssertionError(f"global lookup used for {name}")

    monkeypatch.setattr(
        "manusift.agent.get_tool",
        _global_lookup_should_not_run,
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    tool = LocalIngestTool()
    llm = ScriptedLLM(
        [
            ChatResponse(
                content_blocks=[{"type": "text", "text": "done"}],
                stop_reason="end_turn",
            )
        ]
    )

    ctx = ToolContext(trace_id="")
    # R-2026-06-15 (Phase 1 + P1-1):
    # bind the loop to a local
    # variable so the test can
    # inspect ``loop._ctx`` (the
    # agent loop's *internal*
    # ToolContext, which is a
    # new object after the
    # path-pre-processing).  The
    # original ``ctx`` is no
    # longer mutated for the
    # ``metadata`` field.
    loop = AgentLoop(
        llm,
        tools=[tool],
        ctx=ctx,
        max_steps=1,
    )
    result = loop.run(f"review {pdf}")

    assert result.stopped_reason == "end_turn"
    assert tool.calls == [{"path": str(pdf)}]
    assert ctx.trace_id == "local-trace"
    assert ctx.current_pdf == str(pdf)
    # R-2026-06-15 (Phase 1 + P1-1):
    # ``ctx.metadata`` is now a
    # ``MappingProxyType`` (read-only).
    # The agent loop cannot mutate the
    # caller's context; it builds a new
    # ``ToolContext`` via
    # ``with_metadata`` for its own
    # use.  The original ``ctx`` is
    # unchanged; the metadata is set
    # on the *internal* loop context.
    assert "pdf_path" not in ctx.metadata
    # The internal ctx (loop._ctx)
    # carries the metadata.
    assert (
        loop._ctx.metadata["pdf_path"]
        == str(pdf)
    )
    assert result.messages[2]["content"][0]["name"] == "ingest_from_path"
    payload = json.loads(result.messages[3]["content"][0]["content"])
    assert payload["trace_id"] == "local-trace"
    assert payload["ok"] is True
    assert payload["result"]["trace_id"] == "local-trace"


# ---------- 4. max_steps guard ----------

def test_loop_stops_at_max_steps() -> None:
    """A misbehaving LLM that always asks for another tool
    must be cut off by max_steps. The final AgentLoopResult
    has stopped_reason='max_steps' so the caller can
    surface that to the user."""
    infinite_script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": f"c{i}",
                    "name": "metadata",
                    "input": {"trace_id": "t-agent"},
                }
            ],
            stop_reason="tool_use",
        )
        for i in range(100)
    ]
    llm = ScriptedLLM(infinite_script)
    tools = [get_tool("metadata")]
    result = AgentLoop(llm, tools=tools, ctx=_ctx(), max_steps=3).run("go")

    assert result.turns == 3
    assert result.stopped_reason == "max_steps"


# ---------- 5. Unknown tool name ----------

def test_unknown_tool_name_returned_as_error_to_llm() -> None:
    """The LLM hallucinated a tool name that does not
    exist. The loop must not crash; it feeds back an
    error envelope so the LLM can recover next turn."""
    script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "this_tool_does_not_exist",
                    "input": {},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "ok"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    tools = [get_tool("metadata")]
    result = AgentLoop(llm, tools=tools, ctx=_ctx()).run("x")

    assert result.stopped_reason == "end_turn"
    # The error was passed back. Inspect the tool_result.
    msgs = llm.captured_messages[1]
    tool_result = msgs[3]["content"][0]
    payload = json.loads(tool_result["content"])
    assert payload["trace_id"] == "t-agent"
    assert payload["tool_name"] == "this_tool_does_not_exist"
    assert payload["ok"] is False
    assert "not registered" in payload["error"].lower()


# ---------- 6. Tool execution error ----------

def test_tool_execution_error_returned_as_envelope() -> None:
    """A tool whose execute() raises must not kill the
    loop. The error becomes a ToolResult envelope in
    the tool_result so the LLM can react on the next
    turn."""
    from manusift.tools import ToolContext

    class CrashingTool:
        name = "crashy"

        def description(self) -> str:
            return "Always crashes."

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}, "additionalProperties": False}

        def execute(self, input: dict[str, Any], ctx: ToolContext) -> str:
            raise RuntimeError("intentional")

    script = [
        ChatResponse(
            content_blocks=[
                {"type": "tool_use", "id": "c1", "name": "crashy", "input": {}}
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "recovered"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    # Build a tool list whose CrashingTool lives outside
    # the registry: pass it explicitly to the loop. The
    # loop calls get_tool() to dispatch, so we monkeypatch
    # that single function call.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        "manusift.agent.get_tool",
        lambda n: CrashingTool() if n == "crashy" else None,
    )
    try:
        # Build the loop with a fake tool list (the actual
        # tool reference is not strictly used by the loop,
        # only the schema — and CrashingTool is also
        # available via our monkeypatched get_tool).
        tools = [CrashingTool()]
        result = AgentLoop(llm, tools=tools, ctx=_ctx()).run("go")
        # The error must have been fed back to the LLM as
        # a ToolResult envelope (not raised).
        msgs = llm.captured_messages[1]
        tool_result = msgs[3]["content"][0]
        payload = json.loads(tool_result["content"])
        assert payload["trace_id"] == "t-agent"
        assert payload["tool_name"] == "crashy"
        assert payload["ok"] is False
        assert "intentional" in payload["error"]
        assert result.stopped_reason == "end_turn"
    finally:
        monkey.undo()


def test_tool_result_content_uses_unified_envelope() -> None:
    """Successful tool outputs are
    wrapped before they cross the
    LLM message boundary, so every
    tool result carries trace_id,
    tool_name, ok, result, error,
    and latency_ms."""

    class EchoTool:
        name = "echo"

        def description(self) -> str:
            return "echo"

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(
            self, input: dict[str, Any], ctx: ToolContext
        ) -> str:
            return json.dumps(
                {"ok": True, "value": input["value"]},
                ensure_ascii=False,
            )

    script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "echo-1",
                    "name": "echo",
                    "input": {"value": "paper"},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "done"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    result = AgentLoop(
        llm, tools=[EchoTool()], ctx=_ctx()
    ).run("go")

    tool_result = llm.captured_messages[1][3]["content"][0]
    payload = json.loads(tool_result["content"])
    assert payload["trace_id"] == "t-agent"
    assert payload["tool_name"] == "echo"
    assert payload["ok"] is True
    assert payload["result"] == {"ok": True, "value": "paper"}
    assert payload["error"] is None
    assert isinstance(payload["latency_ms"], int)
    assert payload["metadata"]["tool_use_id"] == "echo-1"
    assert result.stopped_reason == "end_turn"


def test_tool_exception_result_uses_unified_envelope() -> None:
    """Tool crashes should use the
    same result envelope as normal
    tool returns, not a separate
    ad-hoc error string."""

    class CrashingEnvelopeTool:
        name = "crash_envelope"

        def description(self) -> str:
            return "crash"

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(
            self, input: dict[str, Any], ctx: ToolContext
        ) -> str:
            raise RuntimeError("boom")

    script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "crash-1",
                    "name": "crash_envelope",
                    "input": {},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "recovered"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    result = AgentLoop(
        llm, tools=[CrashingEnvelopeTool()], ctx=_ctx()
    ).run("go")

    tool_result = llm.captured_messages[1][3]["content"][0]
    payload = json.loads(tool_result["content"])
    assert payload["trace_id"] == "t-agent"
    assert payload["tool_name"] == "crash_envelope"
    assert payload["ok"] is False
    assert "RuntimeError" in payload["error"]
    assert "boom" in payload["error"]
    assert payload["result"] is None
    assert isinstance(payload["latency_ms"], int)
    assert payload["metadata"]["tool_use_id"] == "crash-1"
    assert result.stopped_reason == "end_turn"


# ---------- 7. on_step hook fires per turn ----------

def test_on_step_hook_fires_per_turn() -> None:
    """A caller (e.g. the TUI) can register a hook to
    receive every ChatResponse and the message-so-far
    transcript. The hook is informational; raising in
    the hook must not break the loop."""
    seen: list[ChatResponse] = []
    script = [
        ChatResponse(
            content_blocks=[{"type": "text", "text": "step 1"}],
            stop_reason="end_turn",
        )
    ]
    llm = ScriptedLLM(script)

    def hook(resp: ChatResponse, msgs: list[dict[str, Any]]) -> None:
        seen.append(resp)

    AgentLoop(llm, tools=[], ctx=_ctx(), on_step=hook).run("x")
    assert len(seen) == 1
    assert seen[0].text == "step 1"


# ---------- 8. The agent + a real PDF end-to-end ----------

def test_agent_loop_runs_real_metadata_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: drop a tiny PDF in the workspace, point
    the agent at it, watch the metadata detector run via
    the agent loop. No real LLM is needed — the script
    only asks for the metadata tool."""
    import fitz  # type: ignore[import-not-found]
    pdf_path = tmp_path / "tiny.pdf"
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello")
    pdf.save(str(pdf_path))
    pdf.close()

    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    # Place the PDF where the tool expects: a job dir.
    tid = "t-agent-e2e"
    job_dir = tmp_path / tid
    job_dir.mkdir()
    (job_dir / "original.pdf").write_bytes(pdf_path.read_bytes())

    script = [
        ChatResponse(
            content_blocks=[
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "metadata",
                    "input": {"trace_id": tid},
                }
            ],
            stop_reason="tool_use",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "done"}],
            stop_reason="end_turn",
        ),
    ]
    llm = ScriptedLLM(script)
    ctx = ToolContext(trace_id=tid, current_pdf=str(pdf_path))
    tools = [get_tool("metadata")]
    result = AgentLoop(llm, tools=tools, ctx=ctx).run("analyze")

    # The tool was actually run; the LLM saw a real
    # DetectorResult JSON under the unified ToolResult
    # envelope. The end-of-loop "done" is returned.
    assert result.stopped_reason == "end_turn"
    msgs = llm.captured_messages[1]
    tool_result = msgs[3]["content"][0]
    parsed = json.loads(tool_result["content"])
    assert parsed["trace_id"] == tid
    assert parsed["tool_name"] == "metadata"
    assert parsed["ok"] is True
    assert parsed["result"]["detector"] == "metadata"
    assert "findings" in parsed["result"]
