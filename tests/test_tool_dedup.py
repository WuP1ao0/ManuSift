"""Tests for the tool-call dedup (R-audit, 2026-06-10).

Background: in the
integrity-report pilot
the LLM called
``render_report`` 99
times in a row, each time
with the exact same
arguments, until the
``max_steps`` cap finally
stopped the loop. The
audit adds two layers of
dedup:

  1. **Signature dedup**:
     if the LLM calls a
     tool with the exact
     same arguments it
     already used, the
     call is rejected
     with a JSON error.

  2. **Per-tool-name cap**:
     any single tool can
     be called at most
     ``_MAX_SAME_TOOL_CALLS``
     times in one
     conversation, even
     with different
     arguments. Tools in
     ``_TOOLS_EXEMPT_FROM_CAP``
     (currently just
     ``render_report``)
     are uncapped because
     writing the final
     report is the goal.

Both layers share the
``AgentLoop`` instance
state and reset per
``AgentLoop`` construction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


# A minimal fake tool
# used to drive the
# dedup tests. We bypass
# the real LLM entirely
# and call
# ``_execute_tool_calls``
# directly with a
# fabricated
# ``ChatResponse``.
class _FakeTool:
    """Stand-in for a real
    Tool; records every
    invocation so tests
    can count them."""

    def __init__(self, name: str = "fake_tool") -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []

    def description(self) -> str:
        return "fake tool"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def execute(
        self,
        input: dict[str, Any],
        ctx: Any,
    ) -> str:
        self.calls.append(input)
        return json.dumps({"ok": True, "input": input})


def _make_loop(tools):
    """Build an
    ``AgentLoop`` with a
    fake client. The real
    LLM never gets called
    because we drive
    ``_execute_tool_calls``
    directly."""
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext

    class _NoopClient:
        name = "noop"

        def chat(self, *args, **kwargs):
            raise AssertionError(
                "tests must not call the LLM"
            )

        def is_available(self) -> bool:
            return False

        def analyze_finding(self, finding):
            return None

        def chat_stream(self, *args, **kwargs):
            raise AssertionError(
                "tests must not call the LLM"
            )

    ctx = ToolContext(
        trace_id="t",
        current_pdf="t",
        metadata={},
    )
    return AgentLoop(
        client=_NoopClient(),
        tools=list(tools),
        ctx=ctx,
    )


def _make_response(tool_calls: list[dict[str, Any]]):
    """Build a minimal
    ChatResponse whose
    ``tool_calls`` property
    returns the given
    list. ``ChatResponse``
    derives ``tool_calls``
    from ``content_blocks``,
    so each entry must be
    a ``tool_use`` block.
    """
    from manusift.llm.chat import ChatResponse

    blocks = []
    for i, tc in enumerate(tool_calls):
        # Each
        # tool_use
        # block
        # needs
        # a
        # unique
        # id;
        # we
        # pass
        # one
        # through
        # from
        # the
        # caller.
        block = {
            "type": "tool_use",
            "id": tc.get("id", f"id{i}"),
            "name": tc["name"],
            "input": tc.get("input", {}),
        }
        blocks.append(block)
    return ChatResponse(
        content_blocks=blocks,
        stop_reason="tool_use",
        usage={},
        model="test",
    )


# ---------- 1. Signature dedup ----------


def test_same_tool_same_args_is_rejected() -> None:
    """First call runs;
    identical second call
    is rejected with a
    JSON error message
    that the LLM can read."""
    tool = _FakeTool(name="dup_tool")
    loop = _make_loop([tool])

    # First
    # call
    # --
    # should
    # run.
    loop._execute_tool_calls(
        _make_response(
            [{"name": "dup_tool", "input": {"x": 1}, "id": "t1"}]
        ),
        messages=[],
    )
    assert len(tool.calls) == 1

    # Second
    # call
    # with
    # the
    # SAME
    # arguments
    # --
    # rejected.
    msgs: list[dict[str, Any]] = []
    loop._execute_tool_calls(
        _make_response(
            [{"name": "dup_tool", "input": {"x": 1}, "id": "t2"}]
        ),
        messages=msgs,
    )
    assert len(tool.calls) == 1, (
        "identical re-call should be rejected"
    )
    # The
    # error
    # message
    # must
    # be
    # in
    # the
    # tool_result
    # the
    # LLM
    # sees.
    assert msgs
    result = msgs[0]["content"][0]
    assert "duplicate tool call" in result["content"]


def test_same_tool_different_args_runs_again() -> None:
    """Different arguments
    are NOT a duplicate --
    the LLM is allowed to
    re-call with new
    inputs."""
    tool = _FakeTool(name="dup_tool")
    loop = _make_loop([tool])

    loop._execute_tool_calls(
        _make_response(
            [{"name": "dup_tool", "input": {"x": 1}, "id": "t1"}]
        ),
        messages=[],
    )
    loop._execute_tool_calls(
        _make_response(
            [{"name": "dup_tool", "input": {"x": 2}, "id": "t2"}]
        ),
        messages=[],
    )
    assert len(tool.calls) == 2


def test_render_report_signature_dedup_still_applies() -> None:
    """``render_report`` is
    exempt from the
    per-tool-name cap but
    NOT from the signature
    dedup -- the 99-call
    loop we saw in the
    pilot must not come
    back."""
    tool = _FakeTool(name="render_report")
    loop = _make_loop([tool])

    for i in range(5):
        loop._execute_tool_calls(
            _make_response(
                [
                    {
                        "name": "render_report",
                        "input": {"markdown": "hello"},
                        "id": f"id{i}",
                    }
                ]
            ),
            messages=[],
        )
    # Only
    # the
    # first
    # call
    # actually
    # ran;
    # the
    # rest
    # were
    # deduped.
    assert len(tool.calls) == 1


# ---------- 2. Per-tool-name cap ----------


def test_per_tool_call_count_cap() -> None:
    """``cap_tool`` cannot be
    called more than
    ``_MAX_SAME_TOOL_CALLS``
    times even with
    different arguments
    (so an LLM cannot loop
    on ``metadata`` 99
    times either).

    R-audit (2026-06-14):
    the loop now reads
    ``_MAX_SAME_TOOL_CALLS``
    from Settings
    (``tool_calls_per_name_cap``,
    default 12). For this
    test we want a small
    cap so the 4th call
    triggers; we monkey-
    patch the attribute
    back to 3 after the
    loop is constructed.
    """
    tool = _FakeTool(name="cap_tool")
    loop = _make_loop([tool])
    loop._MAX_SAME_TOOL_CALLS = 3  # tight cap for this test

    # 3
    # distinct
    # calls
    # --
    # all
    # pass.
    for i in range(loop._MAX_SAME_TOOL_CALLS):
        loop._execute_tool_calls(
            _make_response(
                [
                    {
                        "name": "cap_tool",
                        "input": {"x": i},
                        "id": f"id{i}",
                    }
                ]
            ),
            messages=[],
        )
    assert len(tool.calls) == loop._MAX_SAME_TOOL_CALLS

    # 4th
    # call
    # --
    # rejected
    # even
    # with
    #
    # args.
    msgs: list[dict[str, Any]] = []
    loop._execute_tool_calls(
        _make_response(
            [
                {
                    "name": "cap_tool",
                    "input": {"x": 99},
                    "id": "id4",
                }
            ]
        ),
        messages=msgs,
    )
    assert len(tool.calls) == loop._MAX_SAME_TOOL_CALLS
    assert "budget exhausted" in msgs[0]["content"][0]["content"]


def test_render_report_exempt_from_per_tool_cap() -> None:
    """``render_report`` can
    be called more than 3
    times because the
    final report IS the
    loop's goal."""
    tool = _FakeTool(name="render_report")
    loop = _make_loop([tool])

    # 5
    # calls
    # with
    # DIFFERENT
    # markdown
    # --
    # all
    # should
    # pass
    # because
    # the
    # cap
    # exempts
    # ``render_report``.
    for i in range(5):
        loop._execute_tool_calls(
            _make_response(
                [
                    {
                        "name": "render_report",
                        "input": {"markdown": f"hello {i}"},
                        "id": f"id{i}",
                    }
                ]
            ),
            messages=[],
        )
    assert len(tool.calls) == 5


# ---------- 3. Independence ----------


def test_per_tool_counter_resets_per_loop() -> None:
    """Each AgentLoop gets
    its own dedup state --
    two consecutive
    conversations don't
    share counters."""
    tool1 = _FakeTool(name="x")
    tool2 = _FakeTool(name="x")
    loop1 = _make_loop([tool1])
    loop2 = _make_loop([tool2])

    # Loop
    # 1
    # burns
    # through
    # its
    # cap
    # on
    # tool
    # ``x``.
    for i in range(loop1._MAX_SAME_TOOL_CALLS):
        loop1._execute_tool_calls(
            _make_response(
                [{"name": "x", "input": {"a": i}, "id": f"a{i}"}]
            ),
            messages=[],
        )
    # Loop
    # 2
    # should
    # still
    # have
    # a
    # fresh
    # budget.
    loop2._execute_tool_calls(
        _make_response(
            [{"name": "x", "input": {"a": 1}, "id": "b1"}]
        ),
        messages=[],
    )
    assert len(tool1.calls) == loop1._MAX_SAME_TOOL_CALLS
    assert len(tool2.calls) == 1


def test_different_tools_have_independent_counters() -> None:
    """Calling ``metadata``
    3 times must not
    consume the budget
    for ``image_dup``."""
    a = _FakeTool(name="a")
    b = _FakeTool(name="b")
    loop = _make_loop([a, b])

    for i in range(loop._MAX_SAME_TOOL_CALLS):
        loop._execute_tool_calls(
            _make_response(
                [{"name": "a", "input": {"x": i}, "id": f"a{i}"}]
            ),
            messages=[],
        )
    # ``a``
    # is
    # at
    # the
    # cap;
    # ``b``
    # is
    # untouched.
    msgs: list[dict[str, Any]] = []
    loop._execute_tool_calls(
        _make_response(
            [{"name": "b", "input": {}, "id": "b0"}]
        ),
        messages=msgs,
    )
    assert len(a.calls) == loop._MAX_SAME_TOOL_CALLS
    assert len(b.calls) == 1


# ---------- 4. System prompt routing rules ----------


def test_default_system_prompt_documents_dedup_intent() -> None:
    """R-2026-06-14: the system prompt must document
    the dedup policy so the LLM does not loop on the
    same tool 99 times. The specific numerical cap
    (3 same-tool calls, signature dedup) is enforced
    in ``AgentLoop`` code (``_MAX_SAME_TOOL_CALLS``
    and ``_called_signatures``), so the prompt only
    needs to state the *intent*: do not retry with
    the same arguments, surface the error after a
    couple of retries, then stop.
    """
    from manusift.config import get_settings
    from manusift.llm.client import _reset_for_tests
    from manusift.agent import AgentLoop
    from manusift.tools import iter_registered_tools
    from manusift.tools.tool import ToolContext

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    _reset_for_tests()

    class _StubClient:
        name = "stub"

        def chat(self, *a, **k):
            raise AssertionError

        def is_available(self):
            return False

        def analyze_finding(self, f):
            return None

        def chat_stream(self, *a, **k):
            raise AssertionError

    ctx = ToolContext(
        trace_id="t", current_pdf="t", metadata={}
    )
    loop = AgentLoop(
        client=_StubClient(),
        tools=list(iter_registered_tools()),
        ctx=ctx,
    )
    sp = loop._system_prompt
    # Identity.
    assert "ManuSift" in sp
    # The path -> trace_id contract.
    assert "trace_id" in sp
    # The render_report workflow tool is named.
    assert "render_report" in sp
    # The dedup intent: the prompt tells the LLM not
    # to retry the same call when a tool returns an
    # error. We accept any of these phrasings.
    lower = sp.lower()
    assert (
        "do not retry with the same" in lower
        or "do not re-call" in lower
        or "do not re-call a tool with identical" in lower
    )
    # The prompt also says: after a couple of retries,
    # surface the error. We accept any number >= 1.
    import re
    m = re.search(
        r"after (\d+|a couple of|a few) retr",
        lower,
    )
    assert m is not None, (
        "prompt should mention a retry count or a couple of retries"
    )


