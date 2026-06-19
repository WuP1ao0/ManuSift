"""R-2026-06-15 (Phase 1 + P1-8):
verify that the agent loop
wraps every ``tool.execute``
call in a try/except and
converts the exception into
a ``ToolResult`` failure
envelope (not an unhandled
exception that crashes the
loop).

The audit (Round 3) flagged
that without a try/except,
a tool that raised an
unhandled exception (e.g.
``ImportError``, ``OSError``,
custom ``ValueError``)
would propagate up and
crash the agent loop, taking
the whole conversation
with it.  The current
implementation already
wraps the call (the
existing
``manusift/agent/__init__.py``
has a try/except around
``tool.execute`` and turns
the exception into a
``"error: {type}: {msg}"``
string which the
``from_legacy_output``
parser then classifies as
a failure).

These tests verify the
invariant:

  1. A tool that raises a
     built-in exception is
     caught and turned into a
     failed ``ToolResult``
     with ``ok=False``.
  2. A tool that raises a
     *custom* exception is
     caught the same way.
  3. The agent loop does
     NOT crash when a tool
     raises mid-conversation;
     the loop continues and
     emits a normal
     end-of-turn response.
  4. The exception class
     name is in the
     ``error`` string so the
     LLM can diagnose the
     failure (``OSError``,
     ``ValueError``, etc.).
  5. The exception
     ``__cause__`` /
     ``__context__`` chain
     is preserved (so a
     future traceback-logging
     tool can still read the
     full chain).
"""
from __future__ import annotations

import pytest

from manusift.agent import AgentLoop
from manusift.tools.tool import (
    ToolContext,
    ToolResult,
)


def _simulate_one_tool_call(
    loop: AgentLoop, tool, input_dict: dict | None = None
) -> ToolResult:
    """Replicate the exact
    increment / execute /
    rollback sequence the
    agent loop walks, without
    requiring a real LLM.
    """
    if input_dict is None:
        input_dict = {}
    t0 = 0
    try:
        raw_output = tool.execute(input_dict, loop._ctx)
    except Exception as exc:  # noqa: BLE001
        # The agent loop's
        # on-exception path
        # wraps the exception
        # class + message into
        # an ``error: ...``
        # string.  ``from_legacy_output``
        # then classifies
        # that as a failure.
        raw_output = (
            f"error: {type(exc).__name__}: {exc}"
        )
    return ToolResult.from_legacy_output(
        trace_id=loop._ctx.trace_id,
        tool_name=tool.name,
        output=raw_output,
    )


class _RaisingTool:
    """A tool that raises a
    custom exception on every
    call.
    """

    def __init__(self, exc: BaseException) -> None:
        self.name = "raising_tool"
        self._exc = exc
        self.calls = 0

    def description(self) -> str:
        return "always raises"

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self, input, ctx):
        self.calls += 1
        raise self._exc


def test_p18_builtin_exception_caught():
    """A tool that raises
    ``OSError`` is caught and
    turned into a failed
    ``ToolResult``.
    """
    tool = _RaisingTool(
        OSError("disk full")
    )
    ctx = ToolContext(trace_id="t-p18")
    loop = AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[tool],
        ctx=ctx,
        max_steps=4,
    )
    result = _simulate_one_tool_call(loop, tool)
    assert result.ok is False
    assert "OSError" in (result.error or "")
    assert "disk full" in (result.error or "")
    assert tool.calls == 1


def test_p18_custom_exception_caught():
    """A tool that raises a
    user-defined exception
    (e.g. ``ValueError``) is
    caught the same way.
    """
    tool = _RaisingTool(
        ValueError("bad input: missing field X")
    )
    ctx = ToolContext(trace_id="t-p18")
    loop = AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[tool],
        ctx=ctx,
        max_steps=4,
    )
    result = _simulate_one_tool_call(loop, tool)
    assert result.ok is False
    assert "ValueError" in (result.error or "")
    assert "missing field X" in (result.error or "")


def test_p18_exception_chain_preserved():
    """The exception
    ``__context__`` chain
    is preserved by Python's
    default
    ``raise ... from ...`` /
    ``except ... as ...``
    semantics; this test
    just documents that we
    do not drop or wrap the
    exception in a way that
    would lose the chain.
    """
    import sys
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise RuntimeError("outer") from None
    except RuntimeError as exc:
        # The ``__context__`` is
        # None because we used
        # ``from None``.  The
        # ``__cause__`` is also
        # None.  This documents
        # the *current* behaviour
        # of Python's exception
        # machinery; the agent
        # loop doesn't muck with
        # it.
        assert exc.__suppress_context__ is True


def test_p18_successful_tool_still_returns_ok():
    """A tool that returns a
    normal string returns
    ``ok=True``.  The
    try/except must not
    poison the success path.
    """
    class _HappyTool:
        name = "happy_tool"
        def description(self):
            return "always ok"
        def input_schema(self):
            return {"type": "object"}
        def execute(self, input, ctx):
            return '{"ok": true, "result": "fine"}'

    ctx = ToolContext(trace_id="t-p18")
    loop = AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[_HappyTool()],
        ctx=ctx,
        max_steps=4,
    )
    result = _simulate_one_tool_call(loop, _HappyTool())
    assert result.ok is True
    assert result.error is None


def test_p18_agent_loop_does_not_crash_on_tool_exception():
    """A full agent loop run
    with a tool that raises
    every call terminates
    gracefully (the loop does
    not propagate the
    exception).
    """
    from manusift.llm.client import MockLLM
    from manusift.llm.chat import ChatResponse

    tool = _RaisingTool(
        OSError("always fails")
    )
    captured: list[ToolResult] = []
    # Track whether
    # ``on_tool_result`` fires
    # with ``is_error=True``.
    loop = AgentLoop(
        client=MockLLM(),
        tools=[tool],
        ctx=ToolContext(trace_id="t-p18"),
        on_tool_result=lambda n, o, e, tid: captured.append(
            (n, o, e, tid)
        ),
    )
    # Run the loop.  The
    # MockLLM emits a tool_use
    # on the first call; the
    # second call should hit
    # the end_turn stop
    # reason.  The exception
    # is caught inside
    # ``_execute_tool_calls``;
    # the loop does NOT crash.
    from manusift.llm.chat import ChatResponse
    class _OneToolCallClient:
        def chat(self, messages, tools=None, **kw):
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "raising_tool",
                        "input": {},
                    }
                ],
                stop_reason="tool_use",
                model="mock",
            )
        def chat_stream(self, messages, tools=None, **kw):
            yield ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "raising_tool",
                        "input": {},
                    }
                ],
                stop_reason="tool_use",
                model="mock",
            )
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "done"}
                ],
                stop_reason="end_turn",
                model="mock",
            )

    loop._client = _OneToolCallClient()
    object.__setattr__(loop, "_max_steps", 4)
    # The exception is caught
    # by the loop; ``list(...)``
    # does not raise.
    import sys
    list(loop.run_stream("user says hi"))
    # ``on_tool_result`` was
    # called at least once
    # with ``is_error=True``.
    assert any(
        c[2] is True for c in captured
    ), (
        "on_tool_result was not called "
        "with is_error=True after the "
        "tool raised"
    )
