"""Tests for the per-tool-call audit log (L6, B5).

When the chat TUI launches an agent loop, every
tool.execute should leave a JSONL line under
``data/chats/<sid>/tool_calls.jsonl`` describing the
call. This is the audit trail that lets a user
review what the agent did and replay it for
debugging.

Guarantees:

  1. When ``audit_sink=None`` the loop runs exactly
     as before — the audit hook is a no-op.
  2. When ``audit_sink`` is set, it is called once
     per ``tool.execute`` with a dict that has at
     least ``ts``, ``tool``, ``input``, and
     ``output_preview`` fields.
  3. If the tool itself raises, the audit record
     still fires and includes an ``error`` field.
  4. If the audit sink itself raises, the agent
     loop continues — a buggy sink never breaks
     the agent.
  5. A JSONL sink (the format the TUI uses) can be
     reloaded round-trip into the same list of
     dicts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.agent import AgentLoop
from manusift.llm import MockLLM
from manusift.tools import get_tool, tool_names
from manusift.tools.tool import ToolContext


# ---------- helpers ----------

def _ctx() -> ToolContext:
    return ToolContext(trace_id="t-audit", current_pdf=None)


# ---------- 1. No-op when audit_sink is None ----------

def test_audit_sink_none_is_noop() -> None:
    """Passing ``audit_sink=None`` (the default) must
    not break anything. We just check the agent
    runs and returns."""
    llm = MockLLM()
    tool = get_tool("metadata")
    # We have no real PDF, but metadata tool returns
    # an error-string when current_pdf is None,
    # which is fine for this test.
    loop = AgentLoop(
        client=llm,
        tools=[tool],
        ctx=_ctx(),
    )
    result = loop.run("hi")
    assert result.turns >= 1
    # No exception. No assertion on audit (it's off).


# ---------- 2. Sink is called once per tool call ----------

def test_audit_sink_called_for_tool_execute() -> None:
    """With a custom sink attached, the sink is
    called exactly once per ``tool.execute``."""
    llm = ScriptedLLMForAudit([
        # First turn: call the metadata tool.
        _text_response_with_tool_call(
            "metadata", {"trace_id": "t-audit"}
        ),
        # Second turn: stop.
        _text_response_only("done"),
    ])
    captured: list[dict[str, Any]] = []
    loop = AgentLoop(
        client=llm,
        tools=[get_tool("metadata")],
        ctx=_ctx(),
        audit_sink=captured.append,
    )
    loop.run("go")
    # Exactly one tool call -> one audit record.
    assert len(captured) == 1
    rec = captured[0]
    assert rec["tool"] == "metadata"
    assert rec["input"] == {"trace_id": "t-audit"}
    assert "output_preview" in rec
    assert "ts" in rec


def test_audit_sink_called_for_pre_canned_path_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deterministic path pre-processor executes a real
    tool before the first LLM turn, so it must produce the
    same audit record as an LLM-emitted tool call.
    """

    class LocalIngestTool:
        name = "ingest_from_path"

        def description(self) -> str:
            return "local ingest"

        def input_schema(self) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }

        def execute(
            self, input: dict[str, Any], ctx: Any
        ) -> str:
            return json.dumps(
                {
                    "ok": True,
                    "trace_id": "audit-trace",
                    "path": input["path"],
                },
                ensure_ascii=False,
            )

    monkeypatch.setattr(
        "manusift.agent.legacy_loop.get_tool",
        lambda name: None,
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    captured: list[dict[str, Any]] = []
    llm = ScriptedLLMForAudit([_text_response_only("done")])

    loop = AgentLoop(
        client=llm,
        tools=[LocalIngestTool()],
        ctx=_ctx(),
        audit_sink=captured.append,
    )
    loop.run(f"review {pdf}")

    assert len(captured) == 1
    rec = captured[0]
    assert rec["tool"] == "ingest_from_path"
    # P1.5 (R-2026-06-14): the audit
    # sink now runs the input through
    # ``redact_input``. A user-home
    # path (``C:/Users/<u>/...``) is
    # replaced with
    # ``<redacted:user_home>/...`` so
    # the audit JSONL does not leak
    # the user's local username. The
    # test asserts the redacted form
    # to pin the contract.
    assert rec["input"]["path"].startswith(
        "<redacted:user_home>"
    )
    assert rec["input"]["path"].endswith(
        "paper.pdf"
    )
    assert rec["ok"] is True
    assert rec["error"] is None
    assert "audit-trace" in rec["output_preview"]


# ---------- 3. Tool crash is still audited ----------

def test_audit_record_includes_error_on_tool_crash() -> None:
    """A tool that raises an exception is still
    audited. The record's ``error`` field carries
    the exception class + message so a post-hoc
    review can see what went wrong."""
    from manusift.tools.tool import Tool

    class CrashingTool:
        name = "crash"

        def description(self) -> str:
            return "always crashes"

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(self, input: dict, ctx: Any) -> str:
            raise RuntimeError("boom")

    captured: list[dict[str, Any]] = []
    llm = ScriptedLLMForAudit([
        _text_response_with_tool_call("crash", {}),
        _text_response_only("done"),
    ])
    loop = AgentLoop(
        client=llm,
        tools=[CrashingTool()],  # type: ignore[arg-type]
        ctx=_ctx(),
        audit_sink=captured.append,
    )
    loop.run("go")
    assert len(captured) == 1
    rec = captured[0]
    assert rec["tool"] == "crash"
    assert rec["error"] is not None
    assert "boom" in rec["error"]


# ---------- 4. Sink raising does not break the agent ----------

def test_audit_sink_raising_does_not_break_agent() -> None:
    """A buggy sink that raises on every call must
    not propagate the exception. The agent loop
    still completes the turn and moves on."""
    def bad_sink(record: dict) -> None:
        raise ValueError("disk full")

    llm = ScriptedLLMForAudit([
        _text_response_with_tool_call("metadata", {"trace_id": "t-audit"}),
        _text_response_only("done"),
    ])
    loop = AgentLoop(
        client=llm,
        tools=[get_tool("metadata")],
        ctx=_ctx(),
        audit_sink=bad_sink,
    )
    # No exception is the assertion. (A real prod
    # deployment would also want a log line; we
    # check that below.)
    result = loop.run("go")
    assert result.turns >= 2


# ---------- 5. JSONL round-trip (the TUI format) ----------

def test_jsonl_sink_round_trip(tmp_path: Path) -> None:
    """The TUI persists audit records as one JSONL
    line per tool call under
    ``<session_dir>/tool_calls.jsonl``. We round-
    trip: write 2 records (each with a distinct
    tool-call signature so the dedup in
    ``AgentLoop._execute_tool_calls`` lets them
    through), read them back, check they match.
    """
    from manusift.tools.tool import Tool

    class CountingTool:
        name = "count"
        n = 0

        def description(self) -> str:
            return "counter"

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(self, input: dict, ctx: Any) -> str:
            self.n += 1
            return f"call {self.n}"

    captured: list[dict[str, Any]] = []
    # Two tool calls with DIFFERENT arguments so
    # the R-audit-2026-06-10 signature dedup does
    # not collapse them into one. The first call's
    # argument is ``{"n": 1}``; the second is
    # ``{"n": 2}``. The audit log must record both.
    llm = ScriptedLLMForAudit([
        _text_response_with_tool_call("count", {"n": 1}),
        _text_response_with_tool_call("count", {"n": 2}),
        _text_response_only("done"),
    ])
    tool = CountingTool()
    loop = AgentLoop(
        client=llm,
        tools=[tool],  # type: ignore[arg-type]
        ctx=_ctx(),
        audit_sink=captured.append,
    )
    loop.run("go")
    assert len(captured) == 2, (
        f"expected 2 audit records (one per distinct "
        f"tool call), got {len(captured)}"
    )

    # Persist to JSONL.
    target = tmp_path / "tool_calls.jsonl"
    with target.open("w", encoding="utf-8") as f:
        for r in captured:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Reload and check.
    reloaded = [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert reloaded == captured


# ---------- helpers for the scripted LLM ----------

class ScriptedLLMForAudit:
    """A tiny LLM stand-in that returns a fixed
    sequence of responses. Each ``chat`` call pops
    the next response. Keeps the audit tests
    independent of the MockLLM's behaviour."""
    name = "scripted-audit"

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat(  # type: ignore[no-untyped-def]
        self, messages, tools, **kw
    ) -> Any:
        self.calls += 1
        return self._responses.pop(0)

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding: Any) -> None:  # type: ignore[no-untyped-def]
        return None


def _text_response_with_tool_call(name: str, input: dict) -> Any:
    from manusift.llm.chat import ChatResponse
    return ChatResponse(
        content_blocks=[
            {"type": "text", "text": f"calling {name}"},
            {"type": "tool_use", "id": f"call_{name}", "name": name, "input": input},
        ],
        stop_reason="tool_use",
    )


def _text_response_only(text: str) -> Any:
    from manusift.llm.chat import ChatResponse
    return ChatResponse(
        content_blocks=[{"type": "text", "text": text}],
        stop_reason="end_turn",
    )
