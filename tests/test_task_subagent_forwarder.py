"""Tests for the R-2026-06-14 TaskTool + subagent forwarder.

Covers issue 1 (``task`` causes TUI hang) and issue 2
(subagent tool calls are invisible to the parent).

The previous TaskTool ran the sub-agent synchronously
with no timeout and discarded every intermediate
``tool.*`` / ``detector.*`` event. These tests pin the
new contract:

  * the sub-agent runs in a worker thread with a hard
    deadline, so a hang does NOT freeze the parent;
  * the parent EventBus receives a
    ``subagent.started`` / ``subagent.finished`` pair
    bracketing the sub-agent;
  * every tool/detector event the sub-agent emits is
    forwarded to the parent bus with a ``subagent_id``
    payload field;
  * the result envelope contains the new
    ``subagent_id`` and ``timeout_seconds`` fields;
  * the error envelope uses the new
    ``error_kind: "budget_exhausted"`` taxonomy.

Pattern follows claw-code's
``SubagentToolExecutor`` tests
(``external_repos/claw-code/rust/crates/tools/src/lib.rs``).
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from manusift.events import Event, get_bus
from manusift.tools.agent_tools import TaskTool
from manusift.tools.subagent_forwarder import (
    new_subagent_id,
    run_subagent_with_timeout,
    short_subagent_prefix,
)
from manusift.tools.tool import ToolContext
from manusift.tools import subagent_forwarder as forwarder_module


# --------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------


class _FakeLLM:
    """Minimal LLM client the subagent loop can drive.

    Yields a single ``ChatResponse`` with the text we
    configured, then ``end_turn``. Used to drive
    ``AgentLoop.run_stream`` without a real API.
    """

    name = "fake"

    def __init__(self, text: str = "ok") -> None:
        self._text = text
        self.calls = 0

    def chat_stream(self, messages, tools=None, **kw):
        from manusift.llm.chat import ChatResponse

        self.calls += 1
        yield ChatResponse(
            content_blocks=[{"type": "text", "text": self._text}],
            stop_reason="end_turn",
        )


class _HangingLLM:
    """Mimics a sub-agent that never returns.

    Yields nothing, then blocks the thread forever.
    Used to exercise the timeout path.
    """

    name = "hanging"

    def __init__(self) -> None:
        self.calls = 0
        self._stop = threading.Event()

    def chat_stream(self, messages, tools=None, **kw):
        from manusift.llm.chat import ChatResponse

        self.calls += 1
        # Yield once so the loop registers the
        # streaming start, then block.
        yield ChatResponse(
            content_blocks=[{"type": "text", "text": ""}],
            stop_reason="",
        )
        self._stop.wait(timeout=10.0)
        yield ChatResponse(
            content_blocks=[],
            stop_reason="end_turn",
        )


# --------------------------------------------------------------------
# new_subagent_id / short_subagent_prefix
# --------------------------------------------------------------------


def test_new_subagent_id_shape():
    """``sub:`` prefix + 6 chars from a no-confusable
    alphabet (``0-9`` + ``a-z`` minus
    ``i, l, o, u``).
    """
    sid = new_subagent_id()
    assert sid.startswith("sub:")
    assert len(sid) == 10
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    assert all(c in alphabet for c in sid[4:])


def test_short_subagent_prefix():
    """The 7-char prefix is exactly ``sub:`` + 3 chars.
    """
    sid = "sub:abc123"
    assert short_subagent_prefix(sid) == "sub:abc"
    # Falls back to the first 7 chars for non-prefixed.
    assert short_subagent_prefix("abcdefg") == "abcdefg"


# --------------------------------------------------------------------
# run_subagent_with_timeout (pure)
# --------------------------------------------------------------------


def test_run_subagent_with_timeout_completes():
    """A non-hanging loop finishes within the timeout and
    the result text is returned.
    """
    from manusift.agent import AgentLoop

    loop = AgentLoop(
        client=_FakeLLM(text="all done"),
        tools=[],
        ctx=ToolContext(trace_id="t"),
    )
    fwd = forwarder_module._SubagentEventForwarder(
        new_subagent_id(), "pure"
    )
    result = run_subagent_with_timeout(
        loop, "hi", timeout_seconds=2.0, forwarder=fwd
    )
    assert result.ok is True
    assert result.error_kind is None
    assert result.output == "all done"


def test_run_subagent_with_timeout_times_out():
    """A hanging loop returns a timeout error tuple
    after the deadline, even though the worker thread
    is still running.
    """
    from manusift.agent import AgentLoop

    loop = AgentLoop(
        client=_HangingLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
    )
    fwd = forwarder_module._SubagentEventForwarder(
        new_subagent_id(), "hanging"
    )
    t0 = time.monotonic()
    result = run_subagent_with_timeout(
        loop, "hi", timeout_seconds=0.3, forwarder=fwd
    )
    dt = time.monotonic() - t0
    assert result.ok is False
    assert "timeout" in (result.error_kind or "")
    assert 0.2 < dt < 1.5, f"timeout took {dt:.2f}s, expected < 1.5s"


# --------------------------------------------------------------------
# TaskTool.execute: end-to-end
# --------------------------------------------------------------------


@pytest.fixture
def collected_events():
    """Subscribe a listener to the global bus, return
    the collected list, unsubscribe on teardown.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _Listener:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _Listener()
    bus.subscribe(listener)
    yield captured
    bus.unsubscribe(listener)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace ``get_llm_client`` with a callable that
    returns a ``_FakeLLM``.
    """
    llm = _FakeLLM(text="subagent finished OK")

    def _get_llm():
        return llm

    monkeypatch.setattr(
        "manusift.llm.get_llm_client", _get_llm, raising=False
    )
    # ``TaskTool.execute`` imports ``get_llm_client``
    # from ``..llm``. Re-bind the module attribute so
    # the import inside the function picks up the
    # fake.
    import manusift.llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm_client", _get_llm)
    return llm


def test_task_tool_emits_subagent_started_finished(
    collected_events, fake_llm
):
    """A normal sub-agent run produces a
    ``subagent.started`` and ``subagent.finished`` event
    pair on the parent bus.
    """
    tool = TaskTool()
    ctx = ToolContext(trace_id="parent-trace")
    out = tool.execute(
        {"subagent_prompt": "do something"},
        ctx,
    )
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "subagent_id" in payload

    types = [e.type for e in collected_events]
    assert "subagent.started" in types
    assert "subagent.finished" in types

    started = next(
        e for e in collected_events
        if e.type == "subagent.started"
    )
    finished = next(
        e for e in collected_events
        if e.type == "subagent.finished"
    )
    assert started.payload["subagent_id"] == (
        payload["subagent_id"]
    )
    assert finished.payload["ok"] is True
    assert finished.payload["elapsed_seconds"] >= 0
    assert finished.payload["tool_started"] >= 0


def test_task_tool_result_envelope_has_subagent_id(
    collected_events, fake_llm
):
    """The result envelope carries ``subagent_id`` and
    ``timeout_seconds`` so the parent TUI can
    correlate the row.
    """
    tool = TaskTool()
    ctx = ToolContext(trace_id="parent")
    out = tool.execute(
        {
            "subagent_prompt": "ping",
            "timeout_seconds": 5,
        },
        ctx,
    )
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["timeout_seconds"] == 5
    assert payload["subagent_id"].startswith("sub:")
    assert payload["result"] == "subagent finished OK"


def test_task_tool_timeout_returns_typed_error(
    collected_events, monkeypatch
):
    """A hanging sub-agent returns a
    ``error_kind: "budget_exhausted"`` envelope with
    the actual deadline, instead of freezing the
    parent.
    """
    import manusift.llm as llm_mod
    monkeypatch.setattr(
        llm_mod, "get_llm_client", _HangingLLM
    )
    tool = TaskTool()
    ctx = ToolContext(trace_id="parent")
    t0 = time.monotonic()
    out = tool.execute(
        {
            "subagent_prompt": "hang me",
            "timeout_seconds": 0.3,
        },
        ctx,
    )
    dt = time.monotonic() - t0
    payload = json.loads(out)
    assert dt < 2.0, f"task tool took {dt:.2f}s, expected < 2s"
    assert payload["ok"] is False
    assert payload["error_kind"] == "budget_exhausted"
    assert "timeout" in payload["error"]
    assert payload["timeout_seconds"] == 0.3
    # The sub-agent still got a unique id even though
    # it never returned.
    assert payload["subagent_id"].startswith("sub:")

    # The bus must show the subagent.finished event
    # with ok=False and a non-None error.
    finished = next(
        e for e in collected_events
        if e.type == "subagent.finished"
    )
    assert finished.payload["ok"] is False
    assert finished.payload["error"] is not None


def test_task_tool_forwards_tool_started(
    collected_events, monkeypatch, fake_llm
):
    """When the sub-agent emits a ``tool.started`` event
    directly, the parent bus sees it with
    ``subagent_id`` in the payload.

    The fake LLM in this test does NOT return a
    ``tool_use`` block, so the sub-agent does not call
    any tool. We therefore exercise the forwarder
    by emitting a ``tool.started`` event from a stub
    tool that the sub-agent invokes, and check the
    parent bus sees the tagged copy.
    """
    from manusift.events import get_bus, Event
    from manusift.tools.tool import ToolResult
    from manusift.llm.chat import ChatResponse
    import manusift.llm as llm_mod

    # A LLM that returns a tool_use block which the
    # sub-agent will dispatch.
    class _ToolUseLLM:
        name = "tool-use"

        def __init__(self) -> None:
            self._yielded = False

        def chat_stream(self, messages, tools=None, **kw):
            if not self._yielded:
                self._yielded = True
                yield ChatResponse(
                    content_blocks=[{
                        "type": "tool_use",
                        "name": "hello",
                        "input": {},
                        "id": "tid-1",
                    }],
                    stop_reason="tool_use",
                )
            else:
                # Second turn: stop calling
                # tools.
                yield ChatResponse(
                    content_blocks=[{
                        "type": "text",
                        "text": "done",
                    }],
                    stop_reason="end_turn",
                )

    llm = _ToolUseLLM()
    monkeypatch.setattr(llm_mod, "get_llm_client", lambda: llm)

    # A tool that emits a ``tool.started`` event
    # itself (in addition to the one the loop
    # emits).
    class _Hello:
        name = "hello"

        def description(self):
            return ""

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, input, ctx):
            get_bus().emit(Event(
                "tool.started",
                {
                    "trace_id": ctx.trace_id,
                    "tool": "hello",
                    "input": {},
                    "tool_id": "tid-extra",
                },
            ))
            return "ok"

    import manusift.tools as tools_mod
    monkeypatch.setattr(
        tools_mod, "iter_registered_tools",
        lambda: [_Hello()],
    )
    tool = TaskTool()
    out = tool.execute(
        {"subagent_prompt": "call hello"},
        ToolContext(trace_id="t"),
    )
    payload = json.loads(out)
    assert payload["ok"] is True
    # At least one ``tool.started`` event with the
    # subagent_id tag in the payload.
    tagged = [
        e for e in collected_events
        if e.type == "tool.started"
        and e.payload.get("subagent_id") == payload["subagent_id"]
    ]
    assert tagged, (
        f"no tool.started with subagent_id={payload['subagent_id']!r} "
        f"in {[e.type for e in collected_events]}"
    )


def test_task_tool_missing_prompt_returns_permission_denied(
    collected_events, fake_llm
):
    """An empty ``subagent_prompt`` returns a typed
    ``error_kind: "permission_denied"`` envelope.
    """
    tool = TaskTool()
    out = tool.execute({"subagent_prompt": ""}, ToolContext(trace_id="t"))
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "permission_denied"


def test_task_tool_missing_llm_returns_dependency_missing(
    collected_events, monkeypatch
):
    """When the LLM client cannot be built (e.g. no
    key), the tool returns a typed
    ``error_kind: "dependency_missing"`` envelope.
    """
    def _explode():
        raise RuntimeError("no LLM key")

    import manusift.llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm_client", _explode)
    tool = TaskTool()
    out = tool.execute({"subagent_prompt": "x"}, ToolContext(trace_id="t"))
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "dependency_missing"
    assert "no LLM key" in payload["error"]
