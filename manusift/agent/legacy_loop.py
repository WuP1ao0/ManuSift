"""Legacy ReAct agent loop (Step J3) with streaming (P3).

Extracted from ``manusift.agent`` package init so the package
surface stays thin. Prefer
``manusift.agent.factory.create_agent_loop`` for production;
import ``AgentLoop`` from here (or via ``manusift.agent``)
when you need the hand-rolled driver explicitly
(``MANUSIFT_AGENT_RUNTIME=legacy``).

The loop drives an LLM through a sequence of
"thought, tool call, tool result, thought" turns
until the model stops on its own (an ``end_turn``
or ``stop`` finish reason) or we hit ``max_steps``.
``run_stream()`` yields accumulated ``ChatResponse``
chunks for TUI rendering.
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..contracts import Finding
from ..llm.chat import ChatResponse
from ..tools import ToolContext, ToolResult, get_tool
from ..trace import get_logger
from ..path_hooks import build_pre_canned_tool_calls

# R-audit (2026-06-11):
# re-exported
# under
# the
# legacy
# name
# so
# the
# ``run_stream``
# patch
# above
# can
# call
# the
# local
# symbol
# without
# a
# forward
# reference.
_build_pre_canned_tool_calls = build_pre_canned_tool_calls

log = get_logger(__name__)

_legacy_warned = False


def _warn_legacy_once() -> None:
    """Emit a one-shot DeprecationWarning for the legacy loop.

    Suppressed under pytest and when
    ``MANUSIFT_SUPPRESS_LEGACY_WARNING=1``.
    """
    global _legacy_warned
    if _legacy_warned:
        return
    import os
    import warnings

    if os.environ.get("MANUSIFT_SUPPRESS_LEGACY_WARNING") == "1":
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _legacy_warned = True
    warnings.warn(
        "manusift.agent.AgentLoop (legacy) is frozen maintenance mode. "
        "Prefer manusift.agent.create_agent_loop() which defaults to "
        "PydanticAI. Set MANUSIFT_AGENT_RUNTIME=legacy only if needed; "
        "MANUSIFT_SUPPRESS_LEGACY_WARNING=1 silences this notice.",
        DeprecationWarning,
        stacklevel=3,
    )


# Forward references are fine here; the
# typing-only Protocol lives in llm/client.py
# and is imported lazily to avoid a circular
# import at module load time.
class _LLMClientProto:  # pragma: no cover — type-only
    name: str
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 4096,
    ) -> ChatResponse: ...
    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int = 4096,
    ) -> "Iterator[ChatResponse]": ...


@dataclass
class AgentLoopResult:
    """The final state after the loop exits.

    Carries the last ``ChatResponse`` (so callers can
    inspect the assistant's final text), the full message
    transcript (so callers can save it to disk or show
    the user), and a count of LLM turns (for metrics /
    cost attribution).
    """
    final_response: ChatResponse
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    stopped_reason: str = "end_turn"  # or "max_steps"


class AgentLoop:
    """The ReAct-style agent loop.

    Construct with a client, a tool list, a context, and
    a starting user message. Call ``run()`` to drive the
    loop to completion. The loop:

      1. Builds a system prompt (constant; per the leaked
         Claude Code source, the real one is small and
         focuses on telling the model which tools exist).
      2. Sends ``system + user + (history)`` to the LLM
         along with the tool schemas.
      3. If the LLM responded with text only, return.
      4. If the LLM responded with tool_use, execute each
         tool, append the tool_result messages, and loop
         back to step 2.
      5. If ``max_steps`` is reached, stop and report
         ``stopped_reason="max_steps"`` so callers can
         surface that to the user.
    """

    # R-audit (2026-06-12):
    # the
    # step
    # cap
    # was
    # the
    # wrong
    # safety
    # net
    # for
    # a
    # screening
    # agent.
    # A
    # real
    # paper-integrity
    # review
    # needs
    # many
    # turns
    # (PDF
    # ingest
    # +
    # several
    # detector
    # runs
    # +
    # follow-up
    # reads
    # +
    # final
    # report).
    # Capping
    # at
    # 8
    # cuts
    # the
    # LLM
    # off
    # mid-thought.
    # The
    # right
    # safety
    # nets
    # are:
    #   1. a USD
    #      cost
    #      cap
    #      (``max_cost_usd``)
    #   2. a
    #      no-progress
    #      detector
    #      (3
    #      turns
    #      without
    #      a
    #      new
    #      tool
    #      result
    #      ->
    #      force
    #      a
    #      final
    #      report)
    #   3. a
    #      user
    #      abort
    #      key
    #      (already
    #      present).
    # ``max_steps = 0``
    # is
    # the
    # sentinel
    # for
    # "unlimited".
    # Callers
    # can
    # still
    # pass
    # an
    # explicit
    # ``max_steps``
    # for
    # tests
    # that
    # need
    # a
    # hard
    # cap.
    DEFAULT_MAX_STEPS = 0
    # USD
    # cap
    # per
    # run
    # (R-audit
    # 2026-06-12).
    # When
    # the
    # agent
    # loop
    # exceeds
    # this
    # cost,
    # it
    # stops
    # with
    # ``stopped_reason="cost_cap"``
    # so
    # the
    # TUI
    # can
    # surface
    # the
    # reason
    # to
    # the
    # user.
    # ``0``
    # means
    # "no
    # cost
    # cap".
    # R-audit (2026-06-14): the user reported that 5 USD
    # was too tight -- the loop hit the cap after 2-3
    # turns on a fresh paper and forced a re-launch
    # mid-investigation. The default is now 0 (no cap).
    # Operators that want a finite budget can still set
    # ``MANUSIFT_AGENT_MAX_COST_USD=10.0`` or pass
    # ``max_cost_usd=N`` to the Runner.
    DEFAULT_MAX_COST_USD = 0
    # Number
    # of
    # consecutive
    # turns
    # with
    # no
    # new
    # tool
    # call
    # before
    # we
    # force
    # a
    # final
    # report.
    # A
    # turn
    # with
    # no
    # tool
    # calls
    # and
    # no
    # progress
    # in
    # the
    # context
    # means
    # the
    # LLM
    # is
    # just
    # narrating.
    NO_PROGRESS_TURN_LIMIT = 3

    def __init__(
        self,
        client: Any,
        tools: list[Any],
        ctx: ToolContext,
        *,
        system_prompt: str | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        no_progress_turn_limit: int = NO_PROGRESS_TURN_LIMIT,
        on_step: Callable[[ChatResponse, list[dict[str, Any]]], None] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        on_tool_result: (
            Callable[[str, str, bool, str], None] | None
        ) = None,
        # NOTE: prefer ``create_agent_loop()`` (PydanticAI default).
        # R-2026-06-15 (Phase 3 + P3-1):
        # an optional
        # ``parent_interrupt_signal``
        # callable.  When
        # provided, the
        # agent loop
        # invokes it at the
        # *top of every turn*
        # (before any LLM
        # call) and, if it
        # returns ``True``,
        # sets
        # ``_interrupt_requested``.
        # This lets a parent
        # ``TaskTool`` propagate
        # the parent's
        # ``/stop`` interrupt
        # to the child loop:
        # when the user types
        # ``/stop`` in the
        # parent, the parent
        # loop's
        # ``_interrupt_requested``
        # flips to ``True``,
        # and the child loop
        # sees the same
        # signal on its next
        # turn.
        parent_interrupt_signal: (
            Callable[[], bool] | None
        ) = None,
    ) -> None:
        # Soft freeze: prefer create_agent_loop() / pydantic_ai.
        _warn_legacy_once()
        self._client = client
        self._tools = tools
        self._ctx = ctx
        self._max_steps = max_steps
        # R-2026-06-15 (Phase 3 + P3-1):
        # the parent-loop
        # interrupt signal
        # (callable, polled
        # each turn).  When
        # provided, the
        # child's
        # ``run`` /
        # ``run_stream``
        # invoke it at the
        # *top of every
        # turn* and set
        # ``_interrupt_requested``
        # if the parent has
        # been interrupted
        # (e.g. user typed
        # ``/stop``).
        self._parent_interrupt_signal = (
            parent_interrupt_signal
        )
        # R-audit (2026-06-12):
        # the
        # cost
        # cap
        # is
        # the
        # primary
        # safety
        # net
        # for
        # the
        # "no
        # step
        # cap"
        # run
        # policy.
        # ``0``
        # from
        # the
        # Runner
        # means
        # "use
        # the
        # AgentLoop
        # default
        # of
        # 5
        # USD
        # per
        # run".
        # This
        # avoids
        # the
        # trap
        # where
        # the
        # Runner
        # passes
        # ``max_cost_usd=0``
        # as
        # its
        # own
        # "use
        # default"
        # sentinel
        # and
        # the
        # AgentLoop
        # interprets
        # it
        # as
        # "unlimited
        # cost"
        # (the
        # ``0``
        # in
        # ``if
        # self._max_cost_usd
        # > 0``
        # check).
        if max_cost_usd == 0 or max_cost_usd == AgentLoop.DEFAULT_MAX_COST_USD:
            # Allow env override when caller
            # passed the default.
            import os as _os
            env_val = _os.environ.get(
                "MANUSIFT_AGENT_MAX_COST_USD"
            )
            if env_val is not None:
                try:
                    max_cost_usd = float(env_val)
                except (TypeError, ValueError):
                    pass
            # If
            # the
            # caller
            # still
            # wants
            # 0
            # (truly
            # unlimited
            # cost),
            # keep
            # it
            # 0
            # and
            # the
            # check
            # ``if
            # self._max_cost_usd
            # > 0``
            # will
            # skip
            # the
            # cap.
            # Otherwise
            # apply
            # the
            # default.
            # R-audit (2026-06-14): we no longer revert
            # ``max_cost_usd=0`` to the production default
            # of 5 USD. The 5 USD cap was too tight for
            # the user's real workload -- the loop was
            # hitting the cap after 2-3 turns on a fresh
            # paper. The new default IS zero ("no cap"),
            # and explicit ``0`` from the caller is
            # respected. Operators that want a finite
            # budget must set it explicitly via
            # ``MANUSIFT_AGENT_MAX_COST_USD`` or the
            # ``max_cost_usd`` Runner kwarg.
        self._max_cost_usd = max_cost_usd
        self._no_progress_turn_limit = (
            no_progress_turn_limit
        )
        self._on_step = on_step
        # R-audit (2026-06-10): optional
        # ``on_tool_result`` callback fired once
        # per tool execution with
        # ``(tool_name, output, is_error)``.
        # The Runner uses this to surface the
        # tool result to the TUI so the user
        # sees errors that the LLM might
        # silently ignore in its next turn.
        # None means "no callback" -- callers
        # that do not need the result are not
        # broken.
        self._on_tool_result = on_tool_result
        # L6 — optional audit sink. Called once per
        # successful tool execute with a dict
        # describing the call. None means "no audit";
        # chat_app.py passes a function that appends
        # a JSONL line. The sink must never raise;
        # a faulty audit must not break the agent.
        self._audit_sink = audit_sink
        # R-audit (2026-06-10): dedup tool calls so the
        # LLM cannot loop on the same tool 99 times
        # (we observed this with ``render_report`` in
        # the integrity-report pilot). Two layers:
        #
        #   * ``_called_signatures`` -- exact
        #     (tool_name, args) tuples already seen
        #     in this conversation. A re-call with the
        #     SAME arguments is rejected with a
        #     JSON error message so the LLM learns
        #     from the failure next turn.
        #   * ``_tool_call_counts`` -- per-tool-name
        #     counter, capped at
        #     ``_MAX_SAME_TOOL_CALLS``. A re-call of
        #     the same tool with DIFFERENT arguments
        #     is allowed up to the cap; beyond it,
        #     the tool is treated as exhausted and
        #     rejected.
        #
        # ``render_report`` is exempt from the
        # per-tool cap because writing the report
        # is the *goal* of the loop and the LLM
        # may legitimately re-issue the call to
        # update the report after seeing new
        # evidence. The signature dedup still
        # catches the 99-identical-calls loop we
        # saw in earlier runs.
        # R-2026-06-15 (Phase 1 + P1-16):
        # the per-(tool_name, args)
        # signature set used to be
        # an unbounded ``set``.  A
        # pathological agent loop
        # that calls many *unique*
        # tools (e.g. one per row
        # in a 50k-row data audit)
        # would grow the set
        # without bound, eventually
        # OOMing the chat session.
        # We now cap the set at
        # ``_CALLED_SIGNATURES_CAP``
        # entries (1000 by default)
        # and evict the
        # least-recently-added
        # entry on overflow.
        # ``OrderedDict`` is the
        # standard LRU primitive
        # in Python stdlib; using
        # ``move_to_end`` on a
        # hit and ``popitem(last=False)``
        # on overflow is
        # O(1).  The cap is large
        # enough that a normal
        # session (50-200 unique
        # calls) never evicts,
        # but small enough that a
        # pathological session
        # is bounded.
        self._called_signatures: "OrderedDict[str, None]" = (
            OrderedDict()
        )
        self._CALLED_SIGNATURES_CAP = 1000
        self._tool_call_counts: dict[str, int] = {}
        # R-audit (2026-06-14):
        # per-(tool_name,
        # args) signature
        # dedup. ``0``
        # disables the
        # cap (only for
        # tests). Default
        # is the
        # ``tool_calls_per_name_cap``
        # setting (12
        # under
        # trusted-local).
        from ..config import get_settings
        _settings = get_settings()
        self._MAX_SAME_TOOL_CALLS = int(
            getattr(
                _settings,
                "tool_calls_per_name_cap",
                12,
            )
        )
        # R-audit (2026-06-14):
        # per-turn total
        # cap (sum of all
        # tool names). ``0``
        # disables.
        self._TOOL_CALLS_PER_TURN_CAP = int(
            getattr(
                _settings,
                "tool_calls_per_turn_cap",
                50,
            )
        )
        # R-audit (2026-06-14):
        # bash-only per-
        # turn cap. ``0``
        # disables.
        self._BASH_MAX_PER_TURN = int(
            getattr(
                _settings,
                "bash_max_calls_per_turn",
                30,
            )
        )
        self._bash_call_count: int = 0
        self._TOOLS_EXEMPT_FROM_CAP = frozenset(
            {"render_report"}
        )
        # Default system prompt. Small, like the real
        # Claude Code one. We list the available tools by
        # name so the model knows what it can call; the
        # detailed schemas are passed via the tools= arg.
        from .system_prompt import build_system_prompt

        self._system_prompt = build_system_prompt(
            tools,
            ctx=ctx,
            system_prompt=system_prompt,
        )

    def _tool_dicts(self) -> list[dict[str, Any]]:
        """Translate each Tool into the provider-agnostic
        dict shape that ``client.chat`` understands."""
        out: list[dict[str, Any]] = []
        for t in self._tools:
            try:
                out.append(
                    {
                        "name": t.name,
                        "description": t.description(),
                        "input_schema": t.input_schema(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                # A broken tool should not stop the loop.
                log.warning(
                    "could not serialize tool",
                    extra={"tool_name": getattr(t, "name", "?"), "err": str(exc)},
                )
        return out

    def interrupt(self) -> None:
        """R-2026-06-15 (Phase 0.1):
        Set the interrupt flag so the
        streaming loop exits at the
        top of the next turn with
        ``stop_reason='cancelled'``.

        This is the public API the
        chat TUI's ``/stop`` slash
        command calls. The interrupt
        is best-effort: if the loop
        is already inside an LLM
        streaming ``for`` loop, the
        current turn completes
        naturally and the loop
        exits at the next iteration.

        The flag is reset at the
        start of each
        ``run_stream()`` call so a
        stale interrupt from a
        previous run does not leak.

        The method is safe to call
        before ``run_stream()``
        (no-op) and after
        ``run_stream()`` has
        returned (no-op).
        """
        self._interrupt_requested = True

    def run(
        self,
        user_message: str,
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> AgentLoopResult:
        """Drive the loop until the LLM stops or max_steps
        is reached. Returns an ``AgentLoopResult``.

        P3 also exposes ``run_stream()`` — a generator
        variant that yields running accumulated responses
        for token-level UI rendering. The two share the
        same loop body via a private helper; this method
        stays non-streaming so the 11 existing callers
        (pipeline, both TUIs, detector adapter, e2e)
        continue to work without changes.
        """
        # Reuse the streaming variant under the
        # hood so the two code paths cannot drift.
        # The trick: drive ``run_stream`` to
        # completion, keep the last yielded
        # response, and synthesize the
        # ``AgentLoopResult`` the old way.
        last_response: ChatResponse | None = None
        last_messages: list[dict[str, Any]] = []
        last_turns = 0
        max_steps_seen = False
        for resp in self.run_stream(user_message, prior_messages=prior_messages):
            last_response = resp
            # ``run_stream`` keeps ``messages`` on
            # ``self`` between yields via the
            # closure below.
            last_messages = self._streaming_messages
            last_turns = self._streaming_turns
        assert last_response is not None
        stopped_reason = last_response.stop_reason or "end_turn"
        if self._streaming_max_steps_reached:
            stopped_reason = "max_steps"

        return AgentLoopResult(
            final_response=last_response,
            messages=last_messages,
            turns=last_turns,
            stopped_reason=stopped_reason,
        )

    # P3 — streaming support. We keep the
    # running messages / turns / max-steps flag
    # on the instance so ``run()`` can read them
    # at the end of the iteration. The
    # alternative — refactoring both ``run``
    # and ``run_stream`` to share a private
    # helper that drives a state machine —
    # would touch every test; keeping two
    # methods that share the same loop body
    # via instance state is the smallest change
    # that gives streaming callers a real
    # chunk-by-chunk view.
    _streaming_messages: list[dict[str, Any]] = field(
        default_factory=list
    )
    _streaming_turns: int = 0
    _streaming_max_steps_reached: bool = False
    _streaming_cost_cap_reached: bool = False
    # R-2026-06-15 (Phase 0.1): the
    # ``interrupt_requested`` flag
    # is set by ``AgentLoop.interrupt()``
    # when the user types ``/stop`` in
    # the chat TUI. The streaming loop
    # checks this at the top of every
    # turn and exits early with
    # ``stop_reason='cancelled'`` so
    # the user can break out of a
    # long-running agent run. The
    # flag is reset at the start of
    # each ``run_stream()`` call so
    # a stale interrupt from a
    # previous run does not leak
    # into the next one.
    _interrupt_requested: bool = False
    # R-audit (2026-06-12):
    # the
    # per-run
    # cost
    # cap
    # (USD).
    # ``0``
    # means
    # "no
    # cap".
    # Default
    # is
    # ``DEFAULT_MAX_COST_USD``
    # which
    # is
    # overridable
    # by
    # the
    # ``max_cost_usd``
    # constructor
    # arg
    # or
    # the
    # ``MANUSIFT_AGENT_MAX_COST_USD``
    # env
    # var.
    _max_cost_usd: float = DEFAULT_MAX_COST_USD
    # How
    # many
    # consecutive
    # narration-only
    # turns
    # are
    # tolerated
    # before
    # we
    # force
    # a
    # final
    # report.
    # ``0``
    # disables
    # the
    # no-progress
    # detector.
    _no_progress_turn_limit: int = NO_PROGRESS_TURN_LIMIT
    # Running
    # total
    # cost
    # for
    # the
    # current
    # run,
    # used
    # by
    # the
    # cost-cap
    # safety
    # net.
    _run_cost_usd: float = 0.0
    # P3 — dedupe tool calls by id across the
    # streaming chunks of a turn (and across
    # turns, because the LLM may emit the same
    # tool call id again in a later turn if
    # the first attempt errored). ``run_stream``
    # clears this set at the start of each
    # run so a fresh loop is not affected by
    # the previous loop's tool-call id list.
    _streaming_tool_ids: set[str] = field(
        default_factory=set
    )

    def run_stream(
        self,
        user_message: str,
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatResponse]:
        """P3 — token-level streaming variant of
        ``run()``.

        Same semantics as ``run()`` — drive the
        loop until the LLM stops or ``max_steps``
        is reached, executing any ``tool_use``
        blocks the model emits. The difference
        is what the caller sees: ``run()``
        returns a single ``AgentLoopResult``
        after the loop is done; ``run_stream()``
        is a generator that yields one
        ``ChatResponse`` per chunk from
        ``client.chat_stream()``. The yielded
        responses are the *running accumulated*
        responses, not just the final one, so a
        caller can read ``resp.text`` on every
        yield and render a typing indicator.

        The ``on_step`` hook fires on every
        yielded response. The L1 cost log and
        the L6 audit log fire once per LLM turn
        (i.e. only after the final chunk of a
        given turn is consumed) so a single
        LLM call still produces exactly one
        cost record and zero duplicate audit
        rows.

        ``prior_messages`` (R-audit 2026-06-14)
        lets the caller replay earlier
        user/assistant turns into the loop's
        message list. The final messages are
        ``[system, *prior_messages, user_message]``.
        ``None`` and ``[]`` are equivalent. The
        caller is responsible for filtering /
        truncating the chat history (the
        AgentLoop does not know which
        ``ChatMessage``s are noise vs. signal);
        see ``manusift.tui.history_filter``.
        """
        prior_messages = prior_messages or []
        self._streaming_max_steps_reached = False
        self._interrupt_requested = False
        self._streaming_tool_ids = set()
        # R-audit (2026-06-14):
        # reset the per-
        # run tool-call
        # dedup + per-
        # turn bash cap
        # counters so a
        # new run starts
        # with a clean
        # slate. Without
        # this, a second
        # ``run_stream``
        # call inside
        # the same
        # ``AgentLoop``
        # instance would
        # carry the old
        # counts and
        # trip the cap
        # immediately.
        self._called_signatures = OrderedDict()
        self._tool_call_counts = {}
        self._bash_call_count = 0
        # R-audit (2026-06-14): build the message
        # list as ``[system, *prior_messages,
        # user_message]`` so short follow-ups
        # like "下一步" / "继续" / "render the
        # report" resolve against the previous
        # assistant turn instead of being treated
        # as a fresh task. ``prior_messages`` is
        # a list of ``{"role": ..., "content": ...}``
        # dicts (the format the LLM SDKs expect);
        # the ChatApp-level history filter is
        # responsible for stripping out tool JSON,
        # status rows, and detector trace blocks
        # before this list reaches the loop.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        for _pm in prior_messages:
            # Defensive copy: the caller may
            # hold a reference to the source
            # list, and the AgentLoop appends
            # to ``messages`` in place on
            # every turn. A shallow copy keeps
            # each prior item isolated from
            # future mutations.
            messages.append(dict(_pm))
        messages.append(
            {"role": "user", "content": user_message}
        )
        self._streaming_messages = messages
        self._streaming_turns = 0
        # R-audit (2026-06-12):
        # reset
        # the
        # per-run
        # cost
        # accumulator
        # and
        # the
        # no-progress
        # tracker
        # at
        # the
        # start
        # of
        # each
        # run.
        # These
        # are
        # the
        # two
        # safety
        # nets
        # that
        # replace
        # the
        # step
        # cap.
        self._run_cost_usd = 0.0
        self._streaming_no_progress_turns = 0
        self._streaming_last_tool_signature = None
        # R-audit (2026-06-11):
        # if
        # the
        # user
        # message
        # contains
        # a
        # Windows
        # /
        # Unix
        # path,
        # auto-inject
        # the
        # obvious
        # tool
        # calls
        # before
        # the
        # LLM
        # gets
        # a
        # turn.
        # The
        # LLM
        # is
        # unreliable
        # at
        # extracting
        # paths
        # from
        # Chinese-style
        # quoted
        # user
        # messages
        # and
        # at
        # filling
        # in
        # tool
        # parameters
        # --
        # it
        # would
        # narrate
        # "I
        # will
        # register
        # the
        # PDF"
        # but
        # call
        # ``ingest_from_path({})``
        # with
        # no
        # arguments.
        # The
        # deterministic
        # pre-processor
        # fixes
        # this
        # for
        # the
        # common
        # case
        # (user
        # pastes
        # a
        # path).
        # See
        # ``manusift.tui.path_hooks``
        # for
        # the
        # implementation.
        # R-audit (2026-06-11): the path hooks always
        # run; the ``allow_direct_fs`` setting gates
        # the *direct fs tools themselves* (``read_file``,
        # ``list_dir``, ``ingest_from_path``), not the
        # path detector. The path detector is a no-op if
        # the user message has no path-like string, so
        # there is no risk of an extra tool call slipping
        # through when direct-FS access is disabled.
        pre_canned = _build_pre_canned_tool_calls(
            user_message
        )
        for tc in pre_canned:
            self._execute_pre_canned_tool_call(
                messages, tc
            )
        turns = 0
        last_response: ChatResponse | None = None
        forced_final_report = False
        tool_dicts = self._tool_dicts()
        chat_stream_method = getattr(
            self._client, "chat_stream", None
        )
        # R-audit (2026-06-12): ``max_steps=0`` is the
        # sentinel for "unlimited". The cost cap
        # and no-progress detector are the new
        # safety nets.
        while self._max_steps == 0 or turns < self._max_steps:
            # R-2026-06-15 (Phase 0.1):
            # check the interrupt flag
            # at the top of every turn.
            # When the user types
            # ``/stop`` mid-run, this
            # branch exits the loop with
            # ``stop_reason='cancelled'``
            # so the chat TUI can show
            # a "cancelled" system
            # message. The check is
            # placed *before* the LLM
            # call so a stuck network
            # call cannot prevent
            # cancellation.
            # R-2026-06-15 (Phase 3 + P3-1):
            # also check the
            # parent's
            # interrupt signal
            # (a callable that
            # returns ``True``
            # if the parent
            # has been
            # interrupted).  This
            # propagates the
            # parent's ``/stop``
            # to the child
            # loop: the parent
            # calls
            # ``TaskTool.execute()``
            # which spawns a
            # child loop; if
            # the parent is
            # then interrupted,
            # the child loop
            # sees the same
            # signal on its
            # next turn and
            # exits with
            # ``stop_reason='cancelled'``.
            # Without this
            # propagation, a
            # user typing ``/stop``
            # mid-subagent
            # would still wait
            # the full
            # ``timeout_seconds``
            # for the child to
            # give up.
            if (
                self._parent_interrupt_signal
                is not None
                and self._parent_interrupt_signal()
            ):
                self._interrupt_requested = True
            if self._interrupt_requested:
                # R-2026-06-15 (Phase 1 + P1-9):
                # ``ChatResponse.__init__``
                # takes
                # ``content_blocks``
                # (a list of dicts),
                # NOT ``content`` (a
                # string).  The old
                # code passed
                # ``content=""``
                # which raised
                # ``TypeError`` and
                # crashed the
                # streaming loop
                # *after* the
                # interrupt -- the
                # user types ``/stop``,
                # the loop sees the
                # flag, then dies with
                # a TypeError instead
                # of returning the
                # ``cancelled``
                # response.  This is
                # the exact bug the
                # audit's P1-9 entry
                # was hinting at: a
                # ``/stop`` wired but
                # broken at the
                # cancel-exit path.
                last_response = ChatResponse(
                    content_blocks=[],
                    stop_reason="cancelled",
                )
                return
            turns += 1
            self._streaming_turns = turns
            # Reset the per-turn tool-id
            # dedupe set. A tool_use emitted in
            # turn N must not be skipped in
            # turn N+1 just because the same id
            # appeared earlier. (The streaming
            # path deduplicates *within* a
            # turn because the client may
            # re-emit the same tool_use block
            # across several chunks; that is
            # the only window where deduping
            # is needed.)
            self._streaming_tool_ids = set()
            # R-audit (2026-06-12): check the
            # safety nets *before* the LLM
            # call. If the previous turn hit
            # the no-progress limit we
            # inject a "give a final report"
            # instruction below; if it hit
            # the cost cap we exit the loop
            # immediately.
            if chat_stream_method is None:
                # No streaming support on the
                # client; we yield the non-
                # streaming response in a one-
                # shot wrapper so the caller
                # still sees a single response.
                # R-2026-06-15 (Phase 0 +
                # 3c): forward the
                # session id from
                # ``ctx.metadata`` so
                # prompt caching is
                # keyed on the
                # session. Older
                # LLM clients or
                # test mocks that
                # do not accept the
                # ``session_id``
                # kwarg fall back
                # to the legacy
                # two-argument call
                # (TypeError is
                # caught and the
                # call is retried
                # without the
                # kwarg).
                _session_id = (
                    (self._ctx.metadata or {})
                    .get("session_id")
                )
                try:
                    resp = self._client.chat(
                        messages,
                        tool_dicts,
                        session_id=_session_id,
                    )
                except TypeError:
                    resp = self._client.chat(
                        messages,
                        tool_dicts,
                    )
                last_response = resp
                yield from self._yield_with_hooks(resp, messages)
                self._record_cost(resp)
                # R-audit (2026-06-12): check
                # the safety nets. If a cap
                # is hit, exit the loop with
                # the appropriate stopped
                # reason.
                _safety = self._check_safety_nets(resp)
                if _safety == "no_progress":
                    if forced_final_report:
                        return
                    # Force a final report by
                    # injecting a "summarize
                    # now" message and
                    # continuing once.
                    self._inject_final_report_prompt(messages)
                    forced_final_report = True
                    self._streaming_no_progress_turns = 0
                    # The injected system
                    # message resets the
                    # no-progress tracker; we
                    # give the LLM one more
                    # turn to produce the
                    # report.
                    continue
                messages.append(
                    {
                        "role": "assistant",
                        "content": list(resp.content_blocks),
                    }
                )
                if resp.tool_calls:
                    self._execute_tool_calls(
                        resp, messages,
                        seen_ids=self._streaming_tool_ids,
                    )
                    continue
                if resp.stop_reason in (
                    "end_turn", "stop", "max_tokens", "stop_sequence",
                ):
                    return
            # Streaming branch: pull chunks from
            # the client, yielding the running
            # accumulated response on every
            # chunk so the caller's UI can
            # update progressively.
            #
            # R-audit (2026-06-10): the previous
            # version did ``accumulated =
            # partial`` which REPLACED the
            # accumulated text on every chunk.
            # That broke the TUI Runner's
            # ``resp.text`` check, which only
            # fires the assistant-text callback
            # on a turn-final chunk whose
            # ``resp.text`` is non-empty. With
            # replacement the final chunk's
            # ``resp.text`` was still 816 chars
            # (the text_delta was the last
            # chunk), so the bug was *not* a
            # dropped text -- it was a missing
            # ``merged()`` call. We now use
            # ``accumulated = accumulated.merged(partial)``
            # so the text grows monotonically
            # across chunks. The final chunk's
            # ``resp.text`` already carries the
            # full string, and the Runner
            # surfaces it correctly.
            accumulated = ChatResponse()
            # R-audit (2026-06-10):
            # we track the
            # *longest text
            # seen so far* in
            # the streaming
            # branch. The
            # SDKs in use
            # (Anthropic SDK,
            # OpenAI SDK,
            # MiniMax-M3) all
            # either send:
            #   (a) the *full*
            #       accumulated
            #       text on every
            #       chunk (so
            #       ``merged()``
            #       would
            #       double /
            #       triple the
            #       string), or
            #   (b) actual
            #       *delta* chunks
            #       that we want
            #       to concatenate.
            # We handle text
            # ourselves (the
            # longest-wins rule)
            # and only use
            # ``merged()`` for
            # the *non-text*
            # parts (stop_reason,
            # tool_use,
            # usage, model).
            longest_text: str = ""
            for partial in chat_stream_method(
                messages,
                tool_dicts,
                # R-2026-06-15
                # (Phase 0 +
                # 3c): forward
                # the session
                # id from
                # ``ctx.metadata``
                # so prompt
                # caching is
                # keyed on the
                # session.
                # Older LLM
                # clients or
                # test mocks
                # that do not
                # accept the
                # ``session_id``
                # kwarg fall
                # back to the
                # legacy
                # two-argument
                # call. The
                # fallback
                # wrapping is
                # left to the
                # helper layer
                # (the
                # OpenAI /
                # Anthropic
                # SDK retry
                # helpers) so
                # the loop
                # itself is
                # unchanged.
                session_id=(
                    (self._ctx.metadata or {})
                    .get("session_id")
                ),
            ):
                ptext = partial.text
                # Update
                # ``longest_text``
                # by
                # the
                # three
                # possible
                # rules
                # (no-concat
                # mode).
                if (
                    ptext
                    and len(ptext) >= len(longest_text)
                ):
                    if (
                        not longest_text
                        or longest_text in ptext
                    ):
                        # ptext
                        # is
                        # longer
                        # (or
                        # equal
                        # and
                        # not
                        # a
                        # substring)
                        # --
                        # take
                        # it
                        # whole.
                        # R-audit (2026-06-10):
                        # we cannot simply
                        # ``accumulated =
                        # accumulated.merged(partial)``
                        # because merged()
                        # CONCATENATES text
                        # blocks -- so two
                        # identical chunks
                        # would double the
                        # text. Instead we
                        # update the text +
                        # stop_reason fields
                        # by hand and only
                        # fall back to merged()
                        # for the tool_use
                        # blocks (which merged()
                        # handles correctly by
                        # id).
                        longest_text = ptext
                        new_blocks: list[dict[str, Any]] = []
                        # Carry
                        # over
                        # tool_use
                        # blocks
                        # from
                        # the
                        # previous
                        # accumulated.
                        seen_tool_ids: set[str] = set()
                        for b in accumulated.content_blocks:
                            if b.get("type") == "tool_use":
                                bid = b.get("id", "")
                                if bid:
                                    seen_tool_ids.add(bid)
                                    new_blocks.append(b)
                        # Add
                        # new
                        # tool_use
                        # /
                        # text
                        # blocks
                        # from
                        # partial.
                        for b in partial.content_blocks:
                            if b.get("type") == "tool_use":
                                bid = b.get("id", "")
                                if bid in seen_tool_ids:
                                    # Already
                                    # have
                                    # this
                                    # tool_use
                                    # --
                                    # replace
                                    # in
                                    # place.
                                    for i, existing in enumerate(
                                        new_blocks
                                    ):
                                        if (
                                            existing.get("type")
                                            == "tool_use"
                                            and existing.get("id")
                                            == bid
                                        ):
                                            new_blocks[i] = dict(b)
                                            break
                                else:
                                    new_blocks.append(dict(b))
                                    seen_tool_ids.add(bid)
                            elif b.get("type") == "text":
                                # Replace
                                # the
                                # text
                                # in
                                # place
                                # (we
                                # already
                                # know
                                # the
                                # text
                                # is
                                # the
                                # same
                                # or
                                # longer).
                                replaced = False
                                for i, existing in enumerate(
                                    new_blocks
                                ):
                                    if existing.get("type") == "text":
                                        new_blocks[i] = dict(b)
                                        replaced = True
                                        break
                                if not replaced:
                                    new_blocks.append(dict(b))
                            else:
                                new_blocks.append(dict(b))
                        accumulated = ChatResponse(
                            content_blocks=new_blocks,
                            stop_reason=partial.stop_reason
                            or accumulated.stop_reason,
                            usage=partial.usage
                            or accumulated.usage,
                            model=partial.model
                            or accumulated.model,
                        )
                    elif ptext in longest_text:
                        # ptext
                        # is
                        # a
                        # shorter
                        # substring
                        # of
                        # what
                        # we
                        # already
                        # have.
                        # Skip
                        # the
                        # text
                        # update
                        # but
                        # carry
                        # any
                        # new
                        # stop_reason
                        # /
                        # tool_use.
                        if (
                            partial.stop_reason
                            or partial.tool_calls
                        ):
                            accumulated = accumulated.merged(partial)
                    else:
                        # Genuine
                        # delta
                        # --
                        # the
                        # new
                        # text
                        # is
                        # not
                        # a
                        # substring.
                        # Append.
                        longest_text = longest_text + ptext
                        accumulated = accumulated.merged(partial)
                elif ptext and ptext not in longest_text:
                    # Shorter
                    # text
                    # not
                    # in
                    # longest
                    # --
                    # genuine
                    # delta.
                    longest_text = longest_text + ptext
                    accumulated = accumulated.merged(partial)
                else:

                    # No
                    # new
                    # text
                    # (or
                    # ptext
                    # is
                    # a
                    # substring
                    # of
                    # the
                    # longest).
                    # Still
                    # need
                    # to
                    # carry
                    # any
                    # new
                    # stop_reason
                    # or
                    # tool_use.
                    if (
                        partial.stop_reason
                        or partial.tool_calls
                    ):
    
                        accumulated = accumulated.merged(partial)
    
                yield from self._yield_with_hooks(
                    accumulated, messages
                )
            last_response = accumulated
            self._record_cost(accumulated)
            # R-audit (2026-06-12): check
            # the safety nets.
            _safety = self._check_safety_nets(accumulated)
            if _safety == "no_progress":
                if forced_final_report:
                    return
                # Force a final report.
                self._inject_final_report_prompt(messages)
                forced_final_report = True
                self._streaming_no_progress_turns = 0
                # Allow one more turn for
                # the LLM to produce the
                # report.
                continue
            # Append the assistant message and
            # decide whether to keep going.
            messages.append(
                {
                    "role": "assistant",
                    "content": list(accumulated.content_blocks),
                }
            )
            # Execute tool_use blocks FIRST, even
            # if the LLM has already set a
            # stop_reason. The streaming clients
            # sometimes fold a tool_use into the
            # same turn as the final stop
            # reason; we want the tool to run
            # before the loop decides to exit.

            if accumulated.tool_calls:
    
                self._execute_tool_calls(
                    accumulated, messages,
                    seen_ids=self._streaming_tool_ids,
                )
                continue
            if accumulated.stop_reason in (
                "end_turn", "stop", "max_tokens", "stop_sequence",
            ):
                # Fire one more ``on_step`` so
                # downstream hooks see a
                # "real" chat-completed event.
                yield from self._yield_with_hooks(accumulated, messages)
                return
        # Max steps exhausted.
        self._streaming_max_steps_reached = True
        if last_response is not None:
            yield from self._yield_with_hooks(last_response, messages)

    def _yield_with_hooks(
        self,
        chat_response: ChatResponse,
        messages: list[dict[str, Any]],
    ) -> Iterator[ChatResponse]:
        """Fire the ``on_step`` hook (if any) for
        this response and yield the response.
        The hook is best-effort: a buggy hook
        must not break the agent loop. The
        caller uses this in ``yield from`` so
        the cost log / audit / on_step side
        effect fires exactly once per yield.
        """
        if self._on_step is not None:
            try:
                self._on_step(chat_response, messages)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "on_step hook raised",
                    extra={"err": str(exc)},
                )
        yield chat_response

    def _cost_for_response(self, resp: ChatResponse) -> float:
        """Return the USD cost of ``resp`` (delegates to safety module)."""
        from .safety import cost_for_response

        return cost_for_response(resp)

    def _inject_final_report_prompt(
        self,
        messages: list[dict[str, Any]],
    ) -> None:
        """R-audit (2026-06-12):
        when the no-progress
        detector fires, the LLM
        has been narrating
        without producing new
        tool calls for
        ``_no_progress_turn_limit``
        consecutive turns. We
        inject a system message
        forcing the LLM to
        produce a final report
        in the next turn.

        The injected message is
        a ``user`` role (so the
        LLM treats it as a new
        instruction) and
        references the running
        cost so the user can see
        the budget was the
        reason.

        R-2026-06-15 (Phase 0+1 + P1-6):
        Anthropic's API requires
        strict alternation
        between ``user`` and
        ``assistant`` roles --
        two consecutive ``user``
        messages (or a ``user``
        message right after a
        ``tool`` message) is
        rejected with
        ``400 invalid_request_error``.
        This function is called
        AFTER a tool-use turn,
        so the last message is
        ``role="tool"``.  We
        insert an empty
        ``assistant`` placeholder
        before the ``user``
        reminder so the sequence
        becomes
        ``... tool, assistant, user``
        which is valid
        alternation.
        """
        # R-2026-06-15 (Phase 0+1 + P1-6):
        # preserve Anthropic's
        # role-alternation
        # invariant.  If the
        # last message is
        # ``tool`` (the common
        # case after
        # ``_execute_tool_calls``
        # appends a result)
        # we must insert an
        # ``assistant`` placeholder
        # before the ``user``
        # reminder.  We do NOT
        # insert a placeholder if
        # the last message is
        # already ``user`` (the
        # rare case where the
        # LLM responded with no
        # tool calls) -- the
        # Anthropic provider
        # allows multiple
        # ``user`` turns in a row
        # (the B8 backlog item
        # documents the *first*
        # alternation fix; this
        # one is the *second*
        # one specifically for
        # the no-progress path).
        if (
            messages
            and messages[-1].get("role") == "tool"
        ):
            messages.append({
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "[manusift] no-progress "
                            "reminder will follow."
                        ),
                    }
                ],
            })
        cost_str = f"${self._run_cost_usd:.4f}"
        messages.append(
            {
                "role": "user",
                "content": (
                    "[system reminder] You have "
                    f"used {self._streaming_turns} "
                    f"turns and {cost_str} of the "
                    f"{self._max_cost_usd:.2f} USD "
                    "budget without producing new "
                    "tool calls. STOP making tool "
                    "calls and give the user a "
                    "concise final report RIGHT "
                    "NOW. The report must include: "
                    "(1) one-line verdict; "
                    "(2) the 2-3 strongest "
                    "signals/findings you actually "
                    "verified; (3) any limitations "
                    "(e.g. detector that errored, "
                    "data you could not reach, "
                    "narrative you could not "
                    "verify). Do not call any more "
                    "tools -- your next response "
                    "must be plain text."
                ),
            }
        )

    def _check_safety_nets(
        self,
        resp: ChatResponse,
    ) -> str | None:
        """R-audit (2026-06-12):
        the two safety nets that
        replace the step cap.

        Returns ``"no_progress"`` if
        the LLM has been narrating
        without making new tool calls
        for ``_no_progress_turn_limit``
        consecutive turns. Returns
        ``None`` to continue the loop.

        Cost-cap protection was removed
        (2026-07): USD budget no longer
        stops the loop. Running cost is
        still accumulated for audit only.

        The "no progress" signature is
        the
        ``(tool_name, sorted(input.items()))``
        tuple of every tool_use block in
        ``resp`` (or ``"no_tool"`` if no
        tool calls). If the signature
        matches the previous turn's
        signature, the LLM is repeating
        itself; after
        ``_no_progress_turn_limit``
        such turns we force a final
        report.
        """
        # Track spend for audit only (never stop).
        try:
            turn_cost = self._cost_for_response(resp)
            self._run_cost_usd += turn_cost
        except Exception:  # noqa: BLE001
            pass
        # No-progress
        # detector.
        if self._no_progress_turn_limit <= 0:
            return None
        sig: str
        if not resp.tool_calls:
            sig = "no_tool"
        else:
            parts = []
            for tc in resp.tool_calls:
                name = tc.get("name", "")
                inp = tc.get("input", {}) or {}
                # Sort
                # keys
                # for
                # stable
                # signature.
                try:
                    items = sorted(inp.items())
                except Exception:  # noqa: BLE001
                    items = []
                parts.append(f"{name}({items})")
            sig = "|".join(parts)
        if sig == self._streaming_last_tool_signature:
            self._streaming_no_progress_turns += 1
        else:
            self._streaming_no_progress_turns = 0
            self._streaming_last_tool_signature = sig
        if (
            self._streaming_no_progress_turns
            >= self._no_progress_turn_limit
        ):
            return "no_progress"
        return None

    def _record_cost(self, resp: ChatResponse) -> None:
        """P1-E — log this LLM call's cost. The
        streaming path fires this exactly once
        per LLM turn, on the final accumulated
        response, so a single LLM call still
        produces a single cost row regardless of
        how many chunks streamed."""
        try:
            from ..cost import record_call
            record_call(resp)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "cost record_call raised",
                extra={"err": str(exc)},
            )

    def _execute_tool_calls(

        self,
        resp: ChatResponse,
        messages: list[dict[str, Any]],
        seen_ids: set[str] | None = None,
    ) -> None:
        """Execute every ``tool_use`` block on
        ``resp`` and append the ``tool_result``
        messages. Tool failures are returned to
        the LLM in a unified ToolResult envelope
        so the model can react next turn and the
        system can trace the failure. Audit log is fired
        per tool (one row per call, not per
        LLM turn).

        The streaming clients may emit the
        same ``tool_use`` id in multiple
        consecutive chunks (the first chunk
        carries the id, later chunks carry
        the streaming JSON arguments). The
        ``seen_ids`` set dedupes by id so we
        only execute each tool call once
        even if the client re-emits the same
        block in a later chunk of the same
        turn. ``seen_ids`` is mutated in
        place; the caller is expected to
        keep a reference between turns (we
        stash it on ``self._streaming_tool_ids``
        so the streaming variant survives the
        tool-execution → re-stream round
        trip)."""
        if seen_ids is None:
            # R-audit (2026-06-10): handle the case
            # where ``_streaming_tool_ids`` has not
            # been materialised yet (the test suite
            # and some direct callers drive
            # ``_execute_tool_calls`` without going
            # through ``run`` or ``run_stream``). In
            # that case the attribute is still a
            # ``dataclasses.Field`` descriptor --
            # not iterable. Fall back to a fresh
            # ``set`` per call so dedup still works
            # within the single call's tool batch.
            if not isinstance(
                self._streaming_tool_ids, set
            ):
                self._streaming_tool_ids = set()
            seen_ids = self._streaming_tool_ids
        for tc in resp.tool_calls:
            tc_id = tc.get("id", "")
            if tc_id and tc_id in seen_ids:
                continue
            if tc_id:
                seen_ids.add(tc_id)
            # R-audit (2026-06-10): signature dedup.
            # If the LLM has already called this
            # tool with the exact same arguments,
            # return a JSON error instead of running
            # it again. This stops the
            # "render_report 99 times" loop we
            # observed in earlier runs.
            #
            # ``args_hash`` is a stable string so
            # dict ordering and nested structures
            # do not affect the comparison. We use
            # ``json.dumps(sort_keys=True)`` rather
            # than Python's ``hash`` because the
            # latter is process-randomised.
            import json as _json_dedup
            try:
                args_str = _json_dedup.dumps(
                    tc.get("input", {}),
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
            except Exception:
                args_str = repr(tc.get("input", {}))
            sig = (tc["name"], args_str)
            if sig in self._called_signatures:
                err = (
                    "error: duplicate tool call -- "
                    f"tool={tc['name']!r} with the same "
                    "arguments has already been executed "
                    "in this conversation. Pick a "
                    "different tool, change the "
                    "arguments, or write a final "
                    "summary text instead of repeating "
                    "this call. If you are trying to "
                    "render a report and the previous "
                    "render succeeded, the report is "
                    "already on disk -- do not re-render."
                )
                result = ToolResult.fail(
                    trace_id=self._ctx.trace_id,
                    tool_name=tc["name"],
                    error=err,
                    metadata={
                        "tool_use_id": tc.get("id", ""),
                        "reason": "duplicate_call",
                    },
                )
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc.get("id", ""),
                        "content": result.to_json(),
                    }],
                })
                continue
            # Per-tool-name cap (skip tools that are
            # explicitly exempt from the cap).
            name = tc["name"]
            # R-audit (2026-06-14):
            # per-turn total
            # cap. Counts
            # every tool
            # call in this
            # run, regardless
            # of name. ``0``
            # disables.
            # R-audit (2026-06-14):
            # stash the per-
            # call wall-
            # clock start
            # time on a
            # dedicated dict
            # so the
            # ``tool.finished``
            # emit below can
            # read it. We
            # use a dict
            # rather than
            # ``setattr(tc,
            # ...)`` because
            # ``tc`` is
            # always a plain
            # dict in this
            # code path.
            if not hasattr(
                self, "_manusift_tc_starts"
            ):
                self._manusift_tc_starts = {}
            self._manusift_tc_starts[tc_id] = (
                time.monotonic()
            )
            if (
                self._TOOL_CALLS_PER_TURN_CAP
                and not self._TOOLS_EXEMPT_FROM_CAP
                or name not in self._TOOLS_EXEMPT_FROM_CAP
            ):
                total_count = sum(
                    self._tool_call_counts.values()
                )
                if (
                    total_count
                    >= self._TOOL_CALLS_PER_TURN_CAP
                ):
                    err = (
                        "error: per-turn tool-call "
                        "budget exhausted -- "
                        f"this run has already "
                        f"issued {total_count} tool "
                        "calls (the cap is "
                        f"{self._TOOL_CALLS_PER_TURN_CAP}). "
                        "Stop calling tools and "
                        "summarise your findings, or "
                        "ask the user to raise the "
                        "cap via "
                        "MANUSIFT_TOOL_MAX_CALLS_PER_TURN."
                    )
                    result = ToolResult.fail(
                        trace_id=self._ctx.trace_id,
                        tool_name=name,
                        error=err,
                    )
                    seen_ids.add(tc_id)
                    messages.append(
                        {
                            "role": "tool",
                            "name": name,
                            "content": result.to_json(),
                            "tool_call_id": tc_id,
                        }
                    )
                    continue
            # R-audit (2026-06-14):
            # bash-only per-
            # turn cap.
            # The LLM often
            # needs several
            # shells per turn
            # (pip install +
            # python transform
            # + ls + run a
            # detector). The
            # default cap is
            # 30; 0 disables.
            if (
                name == "bash"
                and self._BASH_MAX_PER_TURN
                and self._bash_call_count
                >= self._BASH_MAX_PER_TURN
            ):
                err = (
                    "error: per-turn bash budget "
                    f"exhausted -- already ran "
                    f"{self._bash_call_count} shell "
                    "commands in this turn. "
                    "Either run a tool other "
                    "than bash, or ask the user "
                    "to raise the cap via "
                    "MANUSIFT_BASH_MAX_CALLS_PER_TURN."
                )
                result = ToolResult.fail(
                    trace_id=self._ctx.trace_id,
                    tool_name=name,
                    error=err,
                )
                seen_ids.add(tc_id)
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": result.to_json(),
                        "tool_call_id": tc_id,
                    }
                )
                continue
            if name not in self._TOOLS_EXEMPT_FROM_CAP:
                count = self._tool_call_counts.get(name, 0)
                if count >= self._MAX_SAME_TOOL_CALLS:
                    err = (
                        "error: tool-call budget exhausted -- "
                        f"tool={name!r} has been called "
                        f"{count} times already in this "
                        "run. The Manusift system caps each "
                        "tool at that many calls to prevent "
                        "loops; either reason over the evidence "
                        "you already have, or pick a different "
                        "tool. The cap is configurable via "
                        "MANUSIFT_TOOL_MAX_CALLS_PER_NAME "
                        "(set to 0 to disable)."
                    )
                    result = ToolResult.fail(
                        trace_id=self._ctx.trace_id,
                        tool_name=name,
                        error=err,
                        metadata={
                            "tool_use_id": tc.get("id", ""),
                            "reason": "tool_call_budget",
                        },
                    )
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tc.get("id", ""),
                            "content": result.to_json(),
                        }],
                    })
                    continue
            # R-audit (2026-06-14):
            # emit a tool.started
            # event so the
            # TUI's event bus
            # can render a
            # per-turn Tool
            # Timeline (in
            # addition to the
            # existing
            # ``ToolTraceBlock``
            # which is
            # driven by the
            # callback path).
            # Failure emissions
            # (denied by
            # budget) happen
            # inside the
            # budget-error
            # blocks above;
            # this one is for
            # actual tool
            # execution.
            from ..events import (
                Event as _Event,
            )
            from ..events import (
                get_bus as _get_bus,
            )
            _tool_t0 = time.monotonic()
            try:
                _get_bus().emit(_Event(
                    "tool.started",
                    {
                        "trace_id": self._ctx.trace_id,
                        "tool": name,
                        "input": tc.get("input", {}),
                        "tool_id": tc_id,
                    },
                ))
            except Exception:  # noqa: BLE001
                pass
            self._called_signatures[sig] = None
            # R-2026-06-15 (Phase 1 + P1-16):
            # LRU eviction.  Move
            # to end on hit; on
            # overflow pop the
            # oldest entry
            # (``last=False``).
            self._called_signatures.move_to_end(sig)
            while (
                len(self._called_signatures)
                > self._CALLED_SIGNATURES_CAP
            ):
                self._called_signatures.popitem(
                    last=False
                )
            self._tool_call_counts[name] = (
                self._tool_call_counts.get(name, 0) + 1
            )
            if name == "bash":
                self._bash_call_count += 1
            # Prefer the local tool list (lets
            # a caller pass ad-hoc tools, e.g. a
            # CrashingTool in a test). Fall
            # back to the global registry so
            # plugins installed at runtime
            # still work.
            tool = next(
                (t for t in self._tools
                 if getattr(t, "name", None) == tc["name"]),
                None,
            )
            if tool is None:
                tool = get_tool(tc["name"])
            if tool is None:
                result = ToolResult.fail(
                    trace_id=self._ctx.trace_id,
                    tool_name=tc["name"],
                    error=(
                        f"error: tool {tc['name']!r} not registered"
                    ),
                    metadata={
                        "tool_use_id": tc.get("id", ""),
                        "reason": "not_registered",
                    },
                )
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc.get("id", ""),
                        "content": result.to_json(),
                    }],
                })
                continue

            t0 = time.perf_counter()
            try:
                # R-2026-06-15 (Phase 3 + P3-1):
                # inject a parent
                # interrupt check
                # into the ctx
                # passed to the
                # tool, so the
                # tool (e.g.
                # ``TaskTool``)
                # can forward the
                # parent's
                # interrupt signal
                # to a child agent
                # loop.  The check
                # is a no-op for
                # tools that do not
                # spawn child
                # loops; for those
                # that do
                # (TaskTool), the
                # callback is read
                # at the top of
                # every child turn
                # and ``True``
                # triggers the
                # ``cancelled``
                # exit path.
                ctx_with_interrupt = (
                    self._ctx.with_metadata(
                        _parent_interrupt_check=lambda: (
                            self._interrupt_requested
                        ),
                    )
                )
                raw_output = tool.execute(
                    tc.get("input", {}),
                    ctx_with_interrupt,
                )
            except Exception as exc:  # noqa: BLE001
                raw_output = (
                    f"error: {type(exc).__name__}: {exc}"
                )
            duration_ms = int(
                (time.perf_counter() - t0) * 1000
            )
            tool_result = ToolResult.from_legacy_output(
                trace_id=self._ctx.trace_id,
                tool_name=tc["name"],
                output=raw_output,
                latency_ms=duration_ms,
                metadata={"tool_use_id": tc_id},
            )
            output = tool_result.to_json()
            # R-2026-06-16 (Phase 4 +
            # ctx-metadata
            # propagation):
            # the
            # ``ingest_from_path``
            # tool returns
            # ``data_sources``
            # in its result
            # JSON, but
            # ``data_audit`` /
            # ``list_data_sources``
            # /
            # ``read_data_source``
            # read from
            # ``ctx.metadata['data_sources']``.
            # Without this
            # propagation,
            # a follow-up
            # ``data_audit``
            # call would
            # always see
            # ``data_source_missing``
            # even though
            # the agent
            # *just*
            # ingested the
            # data. We parse
            # the tool
            # result here
            # and write the
            # ``data_sources``
            # list back into
            # ``ctx.metadata``
            # so subsequent
            # tools see it.
            # The propagation
            # is idempotent
            # (replacing an
            # existing list
            # with a new
            # one) and only
            # fires for the
            # tools that
            # advertise
            # ``data_sources``
            # in their
            # result.
            try:
                _p = json.loads(output)
            except Exception:  # noqa: BLE001
                _p = None
            if isinstance(_p, dict):
                _ds = _p.get("data_sources")
                if (
                    isinstance(_ds, list)
                    and tc.get("name", "")
                    in (
                        "ingest_from_path",
                        "list_data_sources",
                    )
                ):
                    try:
                        # ``with_metadata``
                        # returns a new
                        # ``ToolContext``
                        # (frozen
                        # ``MappingProxyType``).
                        # The agent's
                        # ``self._ctx``
                        # is replaced
                        # with the
                        # updated one
                        # so all
                        # downstream
                        # tool calls
                        # (and the
                        # next turn's
                        # ``_build_messages``)
                        # see the
                        # fresh
                        # ``data_sources``.
                        self._ctx = (
                            self._ctx.with_metadata(
                                data_sources=_ds
                            )
                        )
                    except Exception:  # noqa: BLE001
                        pass
            # R-2026-06-15 (Phase 0+1 + P0-2):
            # a transient tool failure
            # (rate-limit, 500, network,
            # raised exception) used to
            # *burn* the per-tool cap
            # permanently for the rest
            # of the conversation, because
            # the counter was bumped
            # *before* the tool ran. We
            # now roll back the counter
            # when the result is not OK,
            # so a single blip on a
            # legitimate tool does not
            # deplete the budget.  The
            # rollback runs for every
            # tool -- including the
            # exempt ``render_report``
            # -- so a transient
            # ``render_report`` failure
            # does not leak into a
            # future per-turn total
            # count.  The
            # ``_called_signatures`` set
            # is also rolled back so a
            # retry with a slightly-
            # tweaked argument does not
            # collide with the previous
            # signature.
            if not tool_result.ok:
                self._tool_call_counts[name] = max(
                    0,
                    self._tool_call_counts.get(name, 0)
                    - 1,
                )
                if sig in self._called_signatures:
                    # R-2026-06-15 (Phase 1 + P1-16):
                    # ``OrderedDict`` uses
                    # ``del`` (or
                    # ``pop``) instead
                    # of ``discard``.
                    self._called_signatures.pop(sig, None)
                if name == "bash":
                    self._bash_call_count = max(
                        0, self._bash_call_count - 1
                    )
            # R-audit (2026-06-10): surface the
            # tool result to the TUI via the
            # ``on_tool_result`` callback.
            if self._on_tool_result is not None:
                try:
                    self._on_tool_result(
                        tc["name"],
                        output,
                        not tool_result.ok,
                        tc.get("id", ""),
                    )
                except Exception:  # noqa: BLE001
                    pass
            # R-audit (2026-06-14):
            # emit a
            # ``tool.finished``
            # event so the
            # TUI's event bus
            # can render a
            # per-turn Tool
            # Timeline entry
            # with the result
            # status, duration,
            # and the artifact
            # path(s) the
            # tool reported.
            try:
                from ..events import (
                    Event as _EventF,
                )
                from ..events import (
                    get_bus as _get_bus_f,
                )
                _artifacts: list[str] = []
                try:
                    _p = json.loads(output)
                    # ``output`` is the
                    # ``ToolResult.to_json()``
                    # envelope: it has
                    # ``{trace_id, tool_name,
                    #  ok, result, error,
                    #  latency_ms, metadata}``.
                    # Real artifact
                    # paths live in
                    # ``result`` (a
                    # nested dict) and
                    # occasionally in
                    # the envelope root
                    # (e.g. ``trace_id``).
                    # Walk both layers.
                    def _collect_artifacts(d: Any) -> None:
                        if not isinstance(d, dict):
                            return
                        for k in (
                            "report_path",
                            "report_html",
                            "html",
                            "output_path",
                            "path",
                            "trace_id",
                        ):
                            v = d.get(k)
                            if (
                                isinstance(v, str)
                                and v
                                and v not in _artifacts
                            ):
                                _artifacts.append(v)
                        arr = d.get("artifacts")
                        if isinstance(arr, list):
                            for a in arr:
                                if (
                                    isinstance(a, str)
                                    and a not in _artifacts
                                ):
                                    _artifacts.append(a)
                    _collect_artifacts(_p)
                    _collect_artifacts(_p.get("result"))
                except Exception:  # noqa: BLE001
                    pass
                _get_bus_f().emit(_EventF(
                    "tool.finished",
                    {
                        "trace_id": self._ctx.trace_id,
                        "tool": tc["name"],
                        "tool_id": tc_id,
                        "ok": bool(tool_result.ok),
                        "duration_ms": int(duration_ms),
                        "artifacts": _artifacts,
                    },
                ))
            except Exception:  # noqa: BLE001
                pass

            self._emit_audit(
                tool_name=tc["name"],
                tool_input=tc.get("input", {}),
                output=output,
                error=None if tool_result.ok else tool_result.error,
                duration_ms=duration_ms,
            )
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tc.get("id", ""),
                    "content": output,
                }],
            })

    def _execute_pre_canned_tool_call(
        self,
        messages: list[dict[str, Any]],
        tc: dict[str, Any],
    ) -> None:
        """R-audit (2026-06-11):
        execute a pre-canned
        tool call (built by
        ``manusift.tui.path_hooks.build_pre_canned_tool_calls``)
        and append the
        assistant tool_use +
        user tool_result
        blocks to ``messages``.

        This is the
        deterministic
        pre-processor that
        runs *before* the
        LLM gets a turn. The
        user reported
        "manusift cannot
        find the file"
        because the LLM was
        narrating instead of
        calling the tool with
        the right path. The
        pre-canned calls
        guarantee that the
        LLM sees a working
        trace_id (and a
        populated
        ``_ctx.current_pdf``)
        on its first turn.

        The method is
        ``_execute_tool_calls``-
        shaped so the
        conversation state
        after the pre-canned
        calls is exactly the
        same as if the LLM
        had emitted the
        tool_use itself.
        """
        # Generate
        # a
        # stable
        # tool_use_id.
        # Pre-canned
        # tool
        # calls
        # are
        # identified
        # with
        # a
        # ``pre_<name>_<idx>``
        # id
        # so
        # the
        # LLM
        # can
        # see
        # them
        # as
        # distinct
        # from
        # its
        # own
        # tool_use
        # ids.
        tc_id = tc.get("id", f"pre_{tc['name']}_{len(messages)}")
        # Do NOT inject a synthetic assistant tool_use into
        # the LLM transcript. DeepSeek thinking mode (and
        # similar) require thinking/signature on model
        # assistant turns; a fake tool_use without those
        # blocks causes 400 on the next request. We still
        # execute the tool and surface the result as a
        # plain user note below.
        # Look
        # up
        # the
        # tool
        # and
        # execute. Keep this
        # in sync with
        # ``_execute_tool_calls``:
        # prefer the local
        # ``self._tools`` list
        # that was exposed to
        # the LLM, then fall
        # back to the global
        # registry for runtime
        # plugins.
        t0 = time.perf_counter()
        duration_ms = 0
        try:
            tool = next(
                (
                    t for t in self._tools
                    if getattr(t, "name", None) == tc["name"]
                ),
                None,
            )
            if tool is None:
                tool = get_tool(tc["name"])
        except Exception as exc:  # noqa: BLE001
            tool_result = ToolResult.fail(
                trace_id=self._ctx.trace_id,
                tool_name=tc["name"],
                error=f"tool not found: {tc['name']!r}: {exc}",
                metadata={
                    "tool_use_id": tc_id,
                    "reason": "not_found",
                },
            )
        else:
            if tool is None:
                tool_result = ToolResult.fail(
                    trace_id=self._ctx.trace_id,
                    tool_name=tc["name"],
                    error=f"tool not found: {tc['name']!r}",
                    metadata={
                        "tool_use_id": tc_id,
                        "reason": "not_found",
                    },
                )
            else:
                try:
                    # R-2026-06-15 (Phase 3 + P3-1):
                    # same
                    # parent-interrupt
                    # propagation as
                    # the streaming
                    # path (see
                    # _execute_tool_calls).
                    ctx_with_interrupt = (
                        self._ctx.with_metadata(
                            _parent_interrupt_check=lambda: (
                                self._interrupt_requested
                            ),
                        )
                    )
                    raw_output = tool.execute(
                        tc["input"], ctx_with_interrupt
                    )
                except Exception as exc:  # noqa: BLE001
                    raw_output = json.dumps({
                        "ok": False,
                        "error": f"tool crashed: {exc}",
                    })
                duration_ms = int((time.perf_counter() - t0) * 1000)
                tool_result = ToolResult.from_legacy_output(
                    trace_id=self._ctx.trace_id,
                    tool_name=tc["name"],
                    output=raw_output,
                    latency_ms=duration_ms,
                    metadata={"tool_use_id": tc_id},
                )
        output = tool_result.to_json()
        # If
        # the
        # tool
        # returned
        # a
        # trace_id,
        # bind
        # it
        # to
        # the
        # run
        # context
        # so
        # subsequent
        # tool
        # calls
        # can
        # find
        # the
        # parsed
        # document.
        try:
            parsed = json.loads(output)
            payload = parsed
            if (
                isinstance(parsed, dict)
                and isinstance(parsed.get("result"), dict)
            ):
                payload = parsed["result"]
            if isinstance(payload, dict):
                new_tid = payload.get("trace_id") or payload.get("id")
                if new_tid and isinstance(new_tid, str):
                    # R-audit (2026-06-11):
                    # bind
                    # the
                    # trace_id
                    # to
                    # the
                    # ``_ctx``
                    # so
                    # subsequent
                    # tool
                    # calls
                    # can
                    # use
                    # it.
                    # ``ToolContext``
                    # is
                    # frozen,
                    # so
                    # we
                    # use
                    # ``object.__setattr__``.
                    try:
                        object.__setattr__(
                            self._ctx, "trace_id", new_tid
                        )
                        pdf_path_str = (
                            payload.get("path")
                            or tc["input"].get("path", "")
                        )
                        # Keep the context fields semantically distinct:
                        # trace_id is the workspace key; current_pdf is the
                        # original user-facing PDF path.
                        if pdf_path_str and isinstance(pdf_path_str, str):
                            try:
                                object.__setattr__(
                                    self._ctx,
                                    "current_pdf",
                                    pdf_path_str,
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        # R-2026-06-15 (Phase 1 + P1-1):
                        # ``ctx.metadata`` is now
                        # a ``MappingProxyType``
                        # (read-only view); use
                        # ``with_metadata`` to
                        # build a new
                        # ``ToolContext`` with the
                        # extra ``pdf_path`` key
                        # instead of mutating the
                        # dict in place.  The old
                        # code did
                        # ``self._ctx.metadata["pdf_path"] = ...``
                        # which is exactly the
                        # Hyrum's-Law trap P1-1
                        # is closing.
                        if pdf_path_str and isinstance(
                            pdf_path_str, str
                        ):
                            try:
                                self._ctx = (
                                    self._ctx.with_metadata(
                                        pdf_path=pdf_path_str
                                    )
                                )
                            except Exception:  # noqa: BLE001
                                pass
                        # Also
                        # update
                        # the
                        # bound
                        # trace
                        # id
                        # for
                        # logging.
                        try:
                            from ..trace import bind_trace_id
                            bind_trace_id(new_tid)
                        except Exception:  # noqa: BLE001
                            pass
                        if tool_result.trace_id != new_tid:
                            tool_result = ToolResult(
                                trace_id=new_tid,
                                tool_name=tool_result.tool_name,
                                ok=tool_result.ok,
                                result=tool_result.result,
                                error=tool_result.error,
                                latency_ms=tool_result.latency_ms,
                                metadata=tool_result.metadata,
                            )
                            output = tool_result.to_json()
                    except Exception:  # noqa: BLE001
                        pass
        except (ValueError, TypeError):
            # Output
            # was
            # not
            # JSON.
            pass
        # R-audit (2026-06-14):
        # emit a
        # ``tool.finished``
        # event so the
        # TUI's event
        # bus can render
        # a per-turn Tool
        # Timeline entry
        # with the result
        # status, duration,
        # and the artifact
        # path(s) the
        # tool reported.
        # The event MUST
        # NOT be allowed
        # to abort the
        # tool call, so
        # we wrap the
        # emit in a
        # try/except.
        try:
            from ..events import (
                Event as _EventF,
            )
            from ..events import (
                get_bus as _get_bus_f,
            )
            _t0 = (
                self._manusift_tc_starts.get(tc_id)
                if hasattr(self, "_manusift_tc_starts")
                else None
            )
            _dur_ms = int(duration_ms)
            _artifacts: list[str] = []
            try:
                _p = json.loads(output)
                def _collect_artifacts(d):
                    if not isinstance(d, dict):
                        return
                    for k in (
                        "report_path",
                        "report_html",
                        "html",
                        "output_path",
                        "path",
                        "trace_id",
                    ):
                        v = d.get(k)
                        if (
                            isinstance(v, str)
                            and v
                            and v not in _artifacts
                        ):
                            _artifacts.append(v)
                    arr = d.get("artifacts")
                    if isinstance(arr, list):
                        for a in arr:
                            if (
                                isinstance(a, str)
                                and a not in _artifacts
                            ):
                                _artifacts.append(a)
                _collect_artifacts(_p)
                _collect_artifacts(_p.get("result"))
            except Exception:  # noqa: BLE001
                pass
            _get_bus_f().emit(_EventF(
                "tool.finished",
                {
                    "trace_id": self._ctx.trace_id,
                    "tool": tc["name"],
                    "tool_id": tc_id,
                    "ok": bool(tool_result.ok),
                    "duration_ms": _dur_ms,
                    "artifacts": _artifacts,
                },
            ))
        except Exception:  # noqa: BLE001
            pass
        self._emit_audit(
            tool_name=tc["name"],
            tool_input=tc.get("input", {}),
            output=output,
            error=None if tool_result.ok else tool_result.error,
            duration_ms=duration_ms,
        )
        # User note only (not Anthropic tool_result pairing).
        try:
            args_preview = json.dumps(
                tc.get("input", {}), ensure_ascii=False, default=str
            )[:200]
        except Exception:  # noqa: BLE001
            args_preview = str(tc.get("input", ""))[:200]
        messages.append({
            "role": "user",
            "content": (
                f"[system] Deterministic pre-tool already ran: "
                f"{tc['name']}({args_preview}) → "
                f"{str(output)[:800]}. "
                "Do not re-ingest the same path unless needed."
            ),
        })
        # Fire
        # the
        # on_tool_result
        # callback
        # (TUI
        # uses
        # this
        # to
        # populate
        # the
        # ToolTraceBlock
        # and
        # the
        # DebugDrawer).
        if self._on_tool_result is not None:
            try:
                self._on_tool_result(
                    tc["name"], output, not tool_result.ok, tc_id
                )
            except Exception:  # noqa: BLE001
                pass

    def _emit_audit(
        self,
        *,
        tool_name: str,
        tool_input: Any,
        output: Any,
        error: str | None,
        duration_ms: int = 0,
    ) -> None:
        """L6 — forward one tool-call record (see ``legacy_audit``)."""
        from .legacy_audit import emit_tool_audit

        emit_tool_audit(
            self._audit_sink,
            tool_name=tool_name,
            tool_input=tool_input,
            output=output,
            error=error,
            duration_ms=duration_ms,
        )
