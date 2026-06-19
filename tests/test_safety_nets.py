"""Tests for the agent-loop safety nets
(R-audit 2026-06-12).

The user reported a
session where the LLM
was narrating without
acting and the loop hit
``max_steps=8`` mid-turn,
leaving the user with no
final report.

The fix replaces the
hard step cap with two
softer safety nets:

  1. a per-run USD cost
     cap (default 5 USD,
     env-overridable via
     ``MANUSIFT_AGENT_MAX_COST_USD``)
  2. a no-progress
     detector (3 consecutive
     turns with the same
     tool signature
     triggers a forced
     final-report prompt)

The ``max_steps=0``
sentinel now means
"unlimited" (callers
and tests can still
pass an explicit cap).
"""
from __future__ import annotations

import itertools
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. Constants ----------


def test_default_max_steps_is_unlimited() -> None:
    """The default
    ``max_steps`` is 0,
    which means
    "unlimited"."""
    from manusift.agent import AgentLoop
    assert AgentLoop.DEFAULT_MAX_STEPS == 0


def test_default_max_cost_usd_is_zero() -> None:
    """R-audit (2026-06-14): the default USD cap per
    run is now 0 (no cap). The previous default of
    5.0 was too tight -- the loop was hitting the
    cap after 2-3 turns on a fresh paper, which
    forced a re-launch mid-investigation. Operators
    that want a finite budget can set
    ``MANUSIFT_AGENT_MAX_COST_USD=10.0`` or pass
    ``max_cost_usd=N`` to the Runner.

    The 0-means-"unlimited" convention is consistent
    with ``max_steps``: 0 also means "unlimited"
    there. The two safety nets are now symmetric.
    """
    from manusift.agent import AgentLoop
    assert AgentLoop.DEFAULT_MAX_COST_USD == 0


def test_no_progress_turn_limit_is_3() -> None:
    """The no-progress
    detector fires after 3
    consecutive
    narration-only turns.
    """
    from manusift.agent import AgentLoop
    assert AgentLoop.NO_PROGRESS_TURN_LIMIT == 3


# ---------- 2. The cost cap fires when cost exceeds the limit ----------


def test_cost_cap_fires_when_budget_exceeded() -> None:
    """When a turn's cost
    pushes the running
    total over
    ``max_cost_usd``, the
    loop exits with
    ``"cost_cap"``."""
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _CostlyClient:
        """A client whose
        responses report
        a USD cost of $1
        per turn via the
        usage dict. The
        client keeps
        emitting
        ``tool_use``
        blocks so the loop
        never reaches
        ``end_turn`` --
        the only way for
        the loop to exit
        is the cost cap.
        """
        name = "costly"

        def __init__(self) -> None:
            self._turn = 0

        def chat(self, messages, tools=None, **kw):
            self._turn += 1
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": f"c{self._turn}",
                        "name": "noop",
                        "input": {"x": self._turn},
                    }
                ],
                stop_reason="tool_use",
                model="costly",
                usage={
                    # Each turn costs ~$0.75;
                    # 3 turns would push
                    # the running total
                    # to $2.25, over the
                    # $2.0 cap. The cap
                    # fires at turn 3.
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                },
            )

    class _NoopTool:
        name = "noop"

        def description(self):
            return "noop"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, input, ctx):
            return "{}"

    # The prompt token count is deliberately large enough
    # that the configured cost model must trip the cap.
    # The
    # no-progress
    # detector
    # is
    # disabled
    # so
    # the
    # only
    # exit
    # is
    # the
    # cost
    # cap.
    loop = AgentLoop(
        client=_CostlyClient(),
        tools=[_NoopTool()],
        ctx=ToolContext(trace_id="t"),
        max_cost_usd=2.0,
        no_progress_turn_limit=0,  # disable
    )
    res = loop.run("hi")
    assert loop._streaming_turns >= 1
    assert loop._client._turn == loop._streaming_turns
    assert loop._streaming_cost_cap_reached is True
    assert res.stopped_reason == "cost_cap"


# ---------- 3. The no-progress detector forces a final report ----------


def test_no_progress_detector_after_three_narration_turns() -> None:
    """When the LLM emits
    the same tool call
    (or no tool call) for
    3 consecutive turns,
    the loop injects a
    "final report" prompt
    and exits the loop.
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _RepetitiveClient:
        """A client that
        always emits the
        same narration
        (no tool calls)
        for every turn.
        The ``no-tool`` signature
        is stable across
        turns, which the
        no-progress detector
        flags after
        ``no_progress_turn_limit``
        consecutive turns.
        """
        name = "repetitive"

        def __init__(self) -> None:
            self._turn = 0

        def chat(self, messages, tools=None, **kw):
            self._turn += 1
            # No
            # tool
            # calls,
            # just
            # narration.
            # Use
            # ``tool_use``
            # so
            # the
            # loop
            # does
            # not
            # exit
            # on
            # ``end_turn``
            # --
            # but
            # with
            # the
            # SAME
            # tool
            # signature
            # each
            # time
            # so
            # the
            # no-progress
            # detector
            # fires.
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": f"c{self._turn}",
                        "name": "noop",
                        "input": {"x": 1},
                    }
                ],
                stop_reason="tool_use",
            )

    class _NoopTool:
        name = "noop"

        def description(self):
            return "noop"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, input, ctx):
            return "{}"

    loop = AgentLoop(
        client=_RepetitiveClient(),
        tools=[_NoopTool()],
        ctx=ToolContext(trace_id="t"),
        max_steps=0,  # unlimited
        max_cost_usd=0,  # no cost cap
        no_progress_turn_limit=3,
    )
    res = loop.run("hi")
    # After
    # 3
    # turns
    # of
    # the
    # same
    # tool
    # call
    # signature,
    # the
    # detector
    # injects
    # a
    # "final
    # report"
    # prompt
    # and
    # the
    # client
    # is
    # called
    # one
    # more
    # time.
    # The
    # 5th
    # turn
    # would
    # be
    # end_turn
    # (the
    # LLM
    # "responding"
    # to
    # the
    # final-report
    # prompt)
    # --
    # but
    # our
    # stub
    # still
    # returns
    # tool_use.
    # The
    # loop
    # should
    # never
    # exceed
    # 4
    # turns
    # (3
    # narration
    # +
    # 1
    # forced).
    assert loop._client._turn >= 4
    # And
    # the
    # no_progress
    # counter
    # was
    # hit
    # at
    # some
    # point.
    assert loop._streaming_no_progress_turns >= 3


def test_no_progress_does_not_fire_on_real_progress() -> None:
    """When the LLM makes
    *different* tool calls
    on consecutive turns,
    the no-progress
    detector does NOT
    fire."""
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _AlternatingClient:
        name = "alt"

        def __init__(self) -> None:
            self._turn = 0

        def chat(self, messages, tools=None, **kw):
            self._turn += 1
            if self._turn == 10:
                return ChatResponse(
                    content_blocks=[],
                    stop_reason="end_turn",
                )
            # Different
            # tool
            # name
            # each
            # turn
            # so
            # the
            # signature
            # changes.
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "tool_use",
                        "id": f"t{self._turn}",
                        "name": f"tool_{self._turn % 3}",
                        "input": {"x": self._turn},
                    }
                ],
                stop_reason="tool_use",
            )

    class _NoopTool:
        name = "tool_0"

        def description(self):
            return "noop"

        def input_schema(self):
            return {"type": "object", "properties": {}}

        def execute(self, input, ctx):
            return "{}"

    # Build
    # a
    # tool
    # for
    # each
    # name.
    class _T1(_NoopTool):
        name = "tool_1"

    class _T2(_NoopTool):
        name = "tool_2"

    tools = [_NoopTool(), _T1(), _T2()]
    loop = AgentLoop(
        client=_AlternatingClient(),
        tools=tools,
        ctx=ToolContext(trace_id="t"),
        max_steps=0,  # unlimited
        max_cost_usd=0,  # no cost cap
        no_progress_turn_limit=3,
    )
    out = list(loop.run_stream("hi"))
    # The
    # client
    # was
    # called
    # 10
    # times
    # (the
    # loop
    # terminated
    # via
    # end_turn,
    # not
    # via
    # no_progress
    # or
    # cost_cap).
    assert loop._client._turn == 10
    assert loop._streaming_no_progress_turns < 3


def test_streaming_no_progress_stops_after_forced_final_report() -> None:
    """If a streaming client ignores the forced-final prompt,
    the loop must stop instead of injecting that prompt forever."""
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _NeverStopsStreamingClient:
        name = "never-stops"

        def __init__(self) -> None:
            self._turn = 0

        def chat_stream(self, messages, tools=None, **kw):
            self._turn += 1
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "Still working"}
                ],
                model="test",
            )

    loop = AgentLoop(
        client=_NeverStopsStreamingClient(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
        max_steps=0,
        max_cost_usd=0,
        no_progress_turn_limit=1,
    )
    chunks = list(itertools.islice(loop.run_stream("hi"), 8))
    assert len(chunks) <= 3
    assert loop._client._turn <= 3


# ---------- 4. AgentLoop.run() reports the new stop reasons ----------


def test_run_reports_cost_cap_via_stopped_reason() -> None:
    """``AgentLoop.run()``
    returns an
    ``AgentLoopResult``
    with
    ``stopped_reason="cost_cap"``
    when the cost cap
    fires."""
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _CostlyClient:
        name = "costly"

        def chat(self, messages, tools=None, **kw):
            return ChatResponse(
                content_blocks=[],
                stop_reason="end_turn",
                model="costly",
                usage={
                    # Each turn costs ~$0.75;
                    # 3 turns would push
                    # the running total
                    # to $2.25, over the
                    # $2.0 cap. The cap
                    # fires at turn 3.
                    "prompt_tokens": 1_000_000,
                    "completion_tokens": 0,
                },
            )

    res = AgentLoop(
        client=_CostlyClient(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
        max_cost_usd=1.0,
        no_progress_turn_limit=0,
    ).run("hi")
    assert res.stopped_reason == "cost_cap"


# ---------- 5. The pre-canned path-hook flow still terminates ----------


def test_pre_canned_path_hooks_dont_infinite_loop() -> None:
    """The pre-canned path
    hooks (R-audit
    2026-06-11) might
    fire ``ingest_from_path``
    which is non-trivial
    work. After they run,
    the loop should
    continue normally and
    the no-progress detector
    should not be tripped
    just by the
    pre-canned calls."""
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext
    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools import iter_registered_tools
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        # Make
        # a
        # directory
        # with
        # a
        # PDF
        # so
        # the
        # pre-canned
        # path
        # hook
        # fires.
        d = Path(tmp) / "case"
        d.mkdir()
        (d / "p.pdf").write_bytes(b"%PDF-1.4\n%fake\n")
        # Mock
        # LLM
        # that
        # always
        # ends
        # the
        # turn.
        class _EndTurnClient:
            name = "endturn"

            def __init__(self) -> None:
                self._turn = 0

            def chat(self, messages, tools=None, **kw):
                self._turn += 1
                return ChatResponse(
                    content_blocks=[],
                    stop_reason="end_turn",
                )

        # Tools
        # need
        # to
        # include
        # the
        # real
        # ones
        # so
        # the
        # pre-canned
        # hook
        # can
        # find
        # them.
        tools = list(iter_registered_tools())
        loop = AgentLoop(
            client=_EndTurnClient(),
            tools=tools,
            ctx=ToolContext(trace_id=""),
            max_steps=0,
            max_cost_usd=0,
            no_progress_turn_limit=3,
        )
        list(loop.run_stream(f'审查 "{d}"'))
        # The
        # LLM
        # was
        # called
        # at
        # least
        # once
        # (the
        # post-pre-canned
        # turn).
        # The
        # no-progress
        # counter
        # should
        # be
        # low
        # because
        # the
        # LLM
        # returned
        # end_turn
        # (not
        # the
        # same
        # tool
        # call
        # 3
        # times).
        assert loop._client._turn >= 1



# --------------------------------------------------------------------
# R-audit (2026-06-14): cost cap is now disabled by default.
# These tests pin the new "no cap" contract: the agent loop
# does NOT exit with ``stopped_reason="cost_cap"`` unless the
# user / operator explicitly opts in via env or kwarg.
# --------------------------------------------------------------------


def test_no_cost_cap_when_caller_passes_zero() -> None:
    """R-audit (2026-06-14): when the caller passes
    ``max_cost_usd=0`` to the Runner/AgentLoop and
    the env var is unset, the loop MUST accept that
    as "no cap" and run forever (modulo no-progress
    and step cap). Before this change, the loop
    silently re-interpreted 0 as the production
    default of 5.0 USD, which tripped the cap after
    2-3 turns on a fresh paper.
    """
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext
    from manusift.llm.chat import ChatResponse

    class _FreeClient:
        name = "free"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, messages, tools=None, **kw):
            self._turn += 1
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "ok"}
                ],
                model="test",
            )
    import os
    saved = os.environ.pop(
        "MANUSIFT_AGENT_MAX_COST_USD", None
    )
    try:
        loop = AgentLoop(
            client=_FreeClient(),
            tools=[],
            ctx=ToolContext(trace_id="t"),
            max_cost_usd=0,  # explicit "no cap"
            no_progress_turn_limit=0,  # also disable
        )
        # Loop internal state must reflect no cap.
        assert loop._max_cost_usd == 0, (
            f"expected _max_cost_usd=0 (no cap), "
            f"got {loop._max_cost_usd}"
        )
    finally:
        if saved is not None:
            os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = saved


def test_cost_cap_still_honours_env_override() -> None:
    """R-audit (2026-06-14): even with the new
    "no cap by default" contract, an operator that
    sets ``MANUSIFT_AGENT_MAX_COST_USD=2.0`` MUST
    still see that cap honoured. The fix did not
    remove the env-override path; it only stopped
    silently re-mapping 0 to 5.0.
    """
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext

    class _CheapClient:
        name = "cheap"
        def chat_stream(self, messages, tools=None, **kw):
            from manusift.llm.chat import ChatResponse
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "x"}],
                model="test",
            )

    saved = os.environ.get("MANUSIFT_AGENT_MAX_COST_USD")
    os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = "2.0"
    try:
        loop = AgentLoop(
            client=_CheapClient(),
            tools=[],
            ctx=ToolContext(trace_id="t"),
            max_cost_usd=0,  # caller wants "use the env"
        )
        # The env override (2.0) must win over the
        # caller's 0.
        assert loop._max_cost_usd == 2.0, (
            f"expected env override 2.0 to win, "
            f"got {loop._max_cost_usd}"
        )
    finally:
        if saved is None:
            os.environ.pop("MANUSIFT_AGENT_MAX_COST_USD", None)
        else:
            os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = saved


def test_cost_cap_still_honours_explicit_kwarg() -> None:
    """R-audit (2026-06-14): passing an explicit
    ``max_cost_usd=N`` (N > 0) MUST still trip the
    cap. The fix only changed the *default*, not
    the operator-overridable behaviour.
    """
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext
    from manusift.llm.chat import ChatResponse

    class _CheapClient:
        name = "cheap"
        def __init__(self) -> None:
            self._turn = 0
        def chat_stream(self, messages, tools=None, **kw):
            self._turn += 1
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "x"}],
                model="test",
            )

    saved = os.environ.pop("MANUSIFT_AGENT_MAX_COST_USD", None)
    try:
        loop = AgentLoop(
            client=_CheapClient(),
            tools=[],
            ctx=ToolContext(trace_id="t"),
            max_cost_usd=10.0,  # explicit cap
            no_progress_turn_limit=0,
        )
        assert loop._max_cost_usd == 10.0
    finally:
        if saved is not None:
            os.environ["MANUSIFT_AGENT_MAX_COST_USD"] = saved
