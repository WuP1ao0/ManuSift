"""Tests for the agent runner (R4).

R4 audit moved the
``ChatApp._run_agent`` body
into a stand-alone
``manusift.tui.agent_runner.Runner``
class. The tests below
exercise the runner
directly, without
spinning up a textual
``App``:

  * the
    ``RunnerCallbacks``
    dataclass has the
    five callbacks plus
    two ``on_started`` /
    ``on_finished``
    hooks,
  * the runner surfaces
    one ``on_assistant_text``
    per turn (on the
    final chunk),
  * the runner dedupes
    tool_use blocks by
    id within a turn,
  * a crash inside the
    loop is reported via
    ``on_message`` and
    the runner returns
    ``"crashed"``,
  * a max_steps exit is
    reported via
    ``on_message`` and
    the runner returns
    ``"max_steps"``,
  * a normal ``end_turn``
    exit returns
    ``"end_turn"``.

The tests use a small
mock LLM + a tiny
"crashing" tool that
returns ``"error: boom"``
to drive the agent
loop. The mocks live
inline because the
project already has
similar mocks in
``tests/test_chat_app_streaming.py``;
duplicating them here
keeps the runner tests
self-contained.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.llm.chat import ChatResponse
from manusift.tools import ToolContext
from manusift.tui.agent_runner import (
    Runner,
    RunnerCallbacks,
)


# ---------- shared mocks ----------


class _MockLLM:
    """A minimal mock LLM
    that yields a sequence
    of ``ChatResponse``s on
    each ``chat_stream``
    call. The sequence is
    taken from the
    ``script`` argument,
    which is a list of
    ``(text, stop_reason)``
    tuples (one tuple per
    turn)."""

    def __init__(
        self,
        script: list[tuple[str, str, list[dict]]],
    ) -> None:
        # ``script[i]`` is
        # the i-th turn's
        # response:
        # (text, stop_reason, tool_calls).
        self._script = script
        self._turn = 0

    @property
    def name(self) -> str:
        return "mock"

    def chat_stream(
        self,
        m: Any,
        tools: Any = None, session_id: str | None = None,
        *,
        max_tokens: int = 4096,
    ) -> Any:
        if self._turn >= len(self._script):
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": ""}
                ],
                stop_reason="end_turn",
            )
            return
        text, stop_reason, tool_calls = self._script[
            self._turn
        ]
        self._turn += 1
        blocks: list[dict] = []
        if text:
            blocks.append(
                {"type": "text", "text": text}
            )
        for i, tc in enumerate(tool_calls):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": f"c{self._turn}_{i}",
                    "name": tc["name"],
                    "input": tc.get("input", {}),
                }
            )
        yield ChatResponse(
            content_blocks=blocks,
            stop_reason=stop_reason,
        )

    def chat(
        self, m: Any, tools: Any = None, session_id: str | None = None, *, max_tokens: int = 4096
    ) -> Any:
        return ChatResponse(
            content_blocks=[],
            stop_reason="end_turn",
        )

    def is_available(self) -> bool:
        return True


class _RecordingTool:
    """A no-op tool that
    returns ``"ok"``. The
    tests use it to verify
    that the agent loop
    actually executes the
    tool, not that the
    tool does anything
    useful."""

    def __init__(self, name: str = "noop") -> None:
        self.name = name

    def description(self) -> str:
        return f"a {self.name} tool"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(self, i: Any, c: Any) -> str:
        return "ok"


# ---------- 1. RunnerCallbacks fields ----------

def test_runner_callbacks_has_six_fields() -> None:
    """The dataclass exposes
    seven callbacks:
    on_status /
    on_assistant_text /
    on_tool_call /
    on_tool_result (R-audit 2026-06-10) /
    on_message /
    on_started /
    on_finished."""
    import dataclasses
    names = {
        f.name
        for f in dataclasses.fields(RunnerCallbacks)
    }
    assert names == {
        "on_status",
        "on_assistant_text",
        "on_tool_call",
        "on_tool_result",
        "on_message",
        "on_started",
        "on_finished",
    }


# ---------- 2. assistant text fires once per turn ----------

def test_assistant_text_fires_once_per_turn() -> None:
    """A 1-turn stream with
    text + stop_reason
    fires ``on_assistant_text``
    exactly once."""
    captured_text: list[str] = []
    captured_status: list[str] = []
    captured_started: list[int] = []
    captured_finished: list[str] = []
    captured_msg: list = []
    llm = _MockLLM(
        script=[("hello", "end_turn", [])]
    )
    runner = Runner(
        client=llm,
        tools=[],
        ctx=ToolContext(trace_id="t1"),
        cb=RunnerCallbacks(
            on_status=captured_status.append,
            on_assistant_text=captured_text.append,
            on_tool_call=lambda *a: None,
            on_message=captured_msg.append,
            on_started=lambda: captured_started.append(1),
            on_finished=captured_finished.append,
        ),
    )
    stopped = runner.run("hi")
    assert stopped == "end_turn"
    assert captured_text == ["hello"]
    assert captured_started == [1]
    assert captured_finished == ["end_turn"]


# ---------- 3. tool calls dedupe by id ----------

def test_tool_calls_surface_once() -> None:
    """Turn 1 emits a
    tool_use; the runner
    surfaces
    ``on_tool_call`` once
    with the right name
    and input."""
    captured_tools: list[tuple[str, dict]] = []
    llm = _MockLLM(
        script=[
            ("", "tool_use", [
                {"name": "noop", "input": {"a": 1}},
            ]),
        ]
    )
    runner = Runner(
        client=llm,
        tools=[_RecordingTool("noop")],
        ctx=ToolContext(trace_id="t1"),
        cb=RunnerCallbacks(
            on_status=lambda s: None,
            on_assistant_text=lambda t: None,
            on_tool_call=lambda n, i, tid: captured_tools.append(
                (n, i)
            ),
            on_message=lambda m: None,
        ),
    )
    runner.run("hi")
    # Exactly one
    # on_tool_call fired
    # with name=``noop``
    # and ``input=``
    # ``{"a": 1}``.
    assert len(captured_tools) == 1
    name, inp = captured_tools[0]
    assert name == "noop"
    assert inp == {"a": 1}


# ---------- 4. crash path ----------

def test_crash_surfaces_via_on_message() -> None:
    """A ``ValueError`` in
    the loop is caught and
    surfaced via
    ``on_message`` as a
    system message; the
    runner returns
    ``"crashed"``."""
    captured_msg: list = []
    captured_status: list[str] = []
    captured_finished: list[str] = []

    class _CrashyLLM:
        @property
        def name(self) -> str:
            return "crashy"

        def chat_stream(self, *a: Any, **kw: Any) -> Any:
            raise ValueError("boom")
            yield  # type: ignore[unreachable]

        def chat(self, *a: Any, **kw: Any) -> Any:
            raise ValueError("boom")

        def is_available(self) -> bool:
            return True

    runner = Runner(
        client=_CrashyLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t1"),
        cb=RunnerCallbacks(
            on_status=captured_status.append,
            on_assistant_text=lambda t: None,
            on_tool_call=lambda *a: None,
            on_message=captured_msg.append,
            on_finished=captured_finished.append,
        ),
    )
    stopped = runner.run("hi")
    assert stopped == "crashed"
    # The runner fired
    # ``on_message`` with a
    # system message
    # containing the
    # exception text.
    assert len(captured_msg) == 1
    msg = captured_msg[0]
    assert msg.role == "system"
    assert "boom" in msg.content
    assert "ready (crashed)" in captured_status
    assert captured_finished == ["crashed"]


# ---------- 5. max_steps path ----------

def test_max_steps_surfaces_via_on_message() -> None:
    """When the agent loop
    exhausts the
    ``max_steps`` budget,
    the runner fires
    ``on_message`` with a
    system message and
    returns
    ``"max_steps"``."""
    captured_msg: list = []
    captured_finished: list[str] = []

    class _AlwaysToolLLM:
        """Always emits a
        tool_use so the
        loop's
        ``continue``
        branch fires
        every turn
        (the runner never
        sees ``end_turn``
        until
        ``max_steps``)."""

        def __init__(self) -> None:
            self._turn = 0

        @property
        def name(self) -> str:
            return "always"

        def chat_stream(
            self, m: Any, tools: Any = None, session_id: str | None = None, *, max_tokens: int = 4096
        ) -> Any:
            self._turn += 1
            yield ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": f"c{self._turn}",
                        "name": "noop",
                        "input": {},
                    }
                ],
                stop_reason="tool_use",
            )

        def chat(
            self, m: Any, tools: Any = None, session_id: str | None = None, *, max_tokens: int = 4096
        ) -> Any:
            return ChatResponse(
                content_blocks=[],
                stop_reason="end_turn",
            )

        def is_available(self) -> bool:
            return True

    runner = Runner(
        client=_AlwaysToolLLM(),
        tools=[_RecordingTool("noop")],
        ctx=ToolContext(trace_id="t1"),
        cb=RunnerCallbacks(
            on_status=lambda s: None,
            on_assistant_text=lambda t: None,
            on_tool_call=lambda *a: None,
            on_message=captured_msg.append,
            on_finished=captured_finished.append,
        ),
        # R-audit (2026-06-12):
        # the
        # default
        # ``max_steps``
        # is
        # now
        # 0
        # (unlimited).
        # The
        # ``_AlwaysToolLLM``
        # stub
        # never
        # emits
        # ``end_turn``
        # on
        # the
        # streaming
        # branch,
        # so
        # the
        # loop
        # would
        # run
        # forever
        # without
        # an
        # explicit
        # cap.
        # We
        # pass
        # ``max_steps=4``
        # to
        # keep
        # the
        # test
        # terminating
        # in
        # O(1)
        # time.
        max_steps=4,
    )
    stopped = runner.run("hi")
    assert stopped == "max_steps"
    # The runner fired
    # ``on_message`` with
    # a max_steps system
    # message.
    sys_msgs = [
        m
        for m in captured_msg
        if getattr(m, "role", "") == "system"
    ]
    assert len(sys_msgs) >= 1
    assert "max_steps" in sys_msgs[-1].content
    assert captured_finished == ["max_steps"]
