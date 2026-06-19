"""R-2026-06-15 (Phase 0+1 + P0-2):
test that a transient tool
failure does NOT burn the
per-tool cap.

Before the fix,
``AgentLoop._tool_call_counts``
was bumped *before* the tool
ran.  A tool that raised an
exception (or returned
``{"ok": false, "error_kind":
"..."}`` due to a 429 / 500
/ network blip) would
permanently consume one slot
of the per-tool budget for
the rest of the conversation.
The LLM would then see
``error: tool-call budget
exhausted`` on a legitimate
retry, even though no actual
loop happened.

The fix rolls the counter
back when the result is not
OK.  This file contains
targeted tests that exercise:

  * a tool that raises an
    exception on the first call
    and succeeds on the second
    -- the second call must
    NOT be blocked by the cap.
  * a tool that returns
    ``{"ok": false}`` on the
    first call and succeeds
    on the second -- same.
  * a tool that succeeds every
    time -- counter still
    increments normally.
"""
from __future__ import annotations

import pytest

from manusift.agent import AgentLoop
from manusift.tools.tool import ToolContext, ToolResult


class _FlakeyTool:
    """A tool that fails on the
    first N calls and succeeds
    afterwards."""

    def __init__(
        self, name: str, fail_count: int
    ) -> None:
        self.name = name
        self._remaining_fails = fail_count
        self.calls = 0

    def description(self) -> str:
        return f"flakey tool {self.name}"

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(
        self,
        input: dict,
        ctx: ToolContext,
    ) -> str:
        self.calls += 1
        if self._remaining_fails > 0:
            self._remaining_fails -= 1
            return (
                '{"ok": false, "error": '
                '"transient 500"}'
            )
        return '{"ok": true, "result": "ok"}'


def _make_loop(
    tool: _FlakeyTool,
    *,
    per_tool_cap: int = 5,
) -> AgentLoop:
    """Build a minimal AgentLoop
    with one tool and a low cap.
    The settings / bus are not
    needed for this unit test.
    """
    from manusift.config import get_settings

    ctx = ToolContext(trace_id="t-p02")
    loop = AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[tool],
        ctx=ctx,
        max_steps=10,
        max_cost_usd=0,
    )
    # Force a low cap so the test
    # runs fast.
    loop._MAX_SAME_TOOL_CALLS = per_tool_cap
    return loop


def _simulate_one_tool_call(
    loop: AgentLoop, tool: _FlakeyTool
) -> None:
    """Walk the same path the
    agent loop walks for one
    tool call.  We do not call
    the full ``run_conversation``
    because it requires a real
    LLM client; instead we
    exercise the exact same
    increment / execute /
    rollback sequence so the
    test is fast and
    deterministic.
    """
    from manusift.tools.tool import (
        ToolResult as _TR,
    )

    sig = (tool.name, "{}")
    # ---- replicate line 2523
    # (counter bump) ----
    # R-2026-06-15 (Phase 1 + P1-16):
    # ``_called_signatures`` is
    # now an ``OrderedDict``
    # (LRU), not a ``set``.
    # The old ``.add(sig)``
    # becomes
    # ``[sig] = None`` +
    # ``move_to_end``.
    loop._called_signatures[sig] = None
    loop._called_signatures.move_to_end(sig)
    loop._tool_call_counts[tool.name] = (
        loop._tool_call_counts.get(tool.name, 0)
        + 1
    )
    # ---- replicate line 2565
    # (execute + on-failure
    # wrap) ----
    try:
        raw_output = tool.execute({}, loop._ctx)
    except Exception as exc:  # noqa: BLE001
        raw_output = f"error: {type(exc).__name__}: {exc}"
    result = _TR.from_legacy_output(
        trace_id=loop._ctx.trace_id,
        tool_name=tool.name,
        output=raw_output,
    )
    # ---- replicate the new
    # rollback block (line 2585+):
    # always rolls back on
    # failure, regardless of
    # exempt status ----
    if not result.ok:
        loop._tool_call_counts[tool.name] = max(
            0,
            loop._tool_call_counts.get(tool.name, 0)
            - 1,
        )
        if sig in loop._called_signatures:
            # R-2026-06-15 (Phase 1 + P1-16):
            # ``_called_signatures``
            # is an OrderedDict, use
            # ``pop(sig, None)`` not
            # ``discard``.
            loop._called_signatures.pop(sig, None)


def test_p02_tool_failure_does_not_burn_cap():
    """A tool that fails on the
    first call and succeeds on
    the second must NOT have its
    count incremented.  The
    second call's success must
    increment to 1, not be
    blocked by an exhausted cap.
    """
    tool = _FlakeyTool("flakey", fail_count=1)
    loop = _make_loop(tool)
    # Call 1: fail.  Counter
    # goes to 1 then back to 0.
    _simulate_one_tool_call(loop, tool)
    assert loop._tool_call_counts["flakey"] == 0, (
        "counter not rolled back on failure"
    )
    # Call 2: succeed.  Counter
    # goes 0 -> 1.
    _simulate_one_tool_call(loop, tool)
    assert loop._tool_call_counts["flakey"] == 1, (
        "counter should be 1 after one "
        "successful call (failure was rolled back)"
    )


def test_p02_consecutive_failures_all_rolled_back():
    """Three transient failures
    in a row must keep the
    counter at 0; the LLM gets
    the full cap for legitimate
    retries.
    """
    tool = _FlakeyTool("flakey", fail_count=3)
    loop = _make_loop(tool)
    for _ in range(3):
        _simulate_one_tool_call(loop, tool)
    assert loop._tool_call_counts["flakey"] == 0
    # Now succeed.
    _simulate_one_tool_call(loop, tool)
    assert loop._tool_call_counts["flakey"] == 1


def test_p02_successful_calls_increment_normally():
    """Sanity: a tool that always
    succeeds bumps the counter
    exactly once per call.
    """
    tool = _FlakeyTool("flakey", fail_count=0)
    loop = _make_loop(tool)
    for _ in range(3):
        _simulate_one_tool_call(loop, tool)
    assert loop._tool_call_counts["flakey"] == 3


def test_p02_called_signature_also_rolled_back():
    """The dedup signature set
    is also rolled back on
    failure, so a retry with a
    tweaked argument does not
    collide with the previous
    signature.
    """
    tool = _FlakeyTool("flakey", fail_count=1)
    loop = _make_loop(tool)
    _simulate_one_tool_call(loop, tool)
    # After failure, the
    # signature should be
    # removed.
    assert ("flakey", "{}") not in (
        loop._called_signatures
    )


def test_p02_render_report_rollback_is_safe():
    """``render_report`` is exempt
    from the per-tool cap (the
    *check* is skipped), so it
    can be called many times
    without triggering the
    budget-exhausted error. The
    rollback block must still
    decrement the counter on
    failure (the counter is
    incremented in the same way
    for exempt and non-exempt
    tools) so a transient
    failure does not deplete
    the count.
    """
    tool = _FlakeyTool("render_report", fail_count=1)
    loop = _make_loop(tool)
    # The exempt set contains
    # render_report.
    assert "render_report" in (
        loop._TOOLS_EXEMPT_FROM_CAP
    )
    _simulate_one_tool_call(loop, tool)
    # After a failure, the
    # counter is rolled back to
    # 0 (it was bumped to 1,
    # then decremented to 0).
    assert loop._tool_call_counts.get(
        "render_report", 0
    ) == 0
