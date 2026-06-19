"""Agent-loop driver for the TUI (R4).

R4 audit: ``chat_app.py``
contained a 200-line
``_run_agent`` method that
mixed three unrelated
concerns:

  1. textual UI side
     effects (status
     bar, message
     append, agent-
     running flag),
  2. LLM stream
     consumption
     (the
     ``for resp in
     loop.run_stream(...)``
     loop), and
  3. per-chunk
     business logic
     (turn / tool-use
     dedupe, cost
     recording).

This module owns the
second of those three
sub-concerns: pulling
chunks from the agent
loop and turning them
into a stream of "UI
events". The TUI handles
the first concern (UI
side effects) and the
ChatApp's existing
``_record_resp_cost``
method handles the third
(per-chunk business
logic).

The split is done with a
``Runner`` dataclass that
holds a small set of
*callbacks*. The TUI
constructs a ``Runner``
with five ``callable``
attributes (the only
hooks the runner needs)
and calls
``runner.run(user_text)``.
The runner never imports
textual or knows about
widgets; it only knows
about ``Callable``s. This
keeps the agent loop
testable in isolation
and means the runner can
be reused by a future
``manusift-eval`` runner
that needs the same
streaming-dedupe logic
without spinning up a
TUI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..agent import AgentLoop
from ..trace import bind_trace_id
from .i18n import t as _t


class _ChatMessageLike(Protocol):
    """Minimal shape the
    ``Runner`` needs from a
    chat message: positional
    ``role``, ``content``,
    ``tool_name``. The
    actual type is
    ``manusift.contracts.ChatMessage``;
    the protocol keeps the
    runner importable from
    tests without pulling
    in the rest of the
    TUI."""

    role: str
    content: str
    tool_name: str | None


@dataclass(frozen=True)
class RunnerCallbacks:
    """The five callbacks the
    ``Runner`` invokes as
    the agent loop streams.

    Every callback is a
    plain ``Callable`` so a
    test can pass a
    ``Mock()`` and a
    production TUI can pass
    a bound method. The
    signatures are pinned
    here so a future caller
    can grep for them.

    The callbacks are:

    * ``on_status`` --
      update the status
      bar text (e.g.
      ``"calling foo…"``
      or ``"ready"``).
    * ``on_assistant_text`` --
      surface one assistant
      message. Called once
      per turn with the
      final text. The TUI
      appends a chat history
      row and the LLM cost
      is recorded.
    * ``on_tool_call`` --
      surface one tool
      invocation. Called
      once per *new* tool
      id; the runner
      dedupes by id within
      a turn.
    * ``on_message`` --
      append any
      ``ChatMessage`` to
      the on-screen /
      persisted history.
      Used for the
      ``"agent crashed"``
      and ``"hit max_steps"``
      system messages.
    * ``on_started`` --
      fires once at the
      start of the run.
      The TUI sets
      ``_agent_running=True``
      and resets the
      streaming speed
      accumulator.
    * ``on_finished`` --
      fires once at the
      end (success, crash,
      or max_steps). The
      TUI clears
      ``_agent_running`` and
      re-focuses the input.
    """

    on_status: Callable[[str], None]
    on_assistant_text: Callable[[str], None]
    on_tool_call: Callable[[str, dict[str, Any], str], None]
    on_message: Callable[[_ChatMessageLike], None]
    # R-audit (2026-06-10): the runner now surfaces
    # tool results to the TUI so the user can see
    # errors that the LLM might silently ignore
    # in its next turn. Signature:
    # ``(tool_name, output, is_error)``. Default is
    # a no-op so callers that do not need the result
    # are not broken. NOTE: this MUST come after
    # all non-default fields because Python
    # dataclasses forbid non-default fields after
    # default fields.
    on_tool_result: Callable[[str, str, bool, str], None] = (
        lambda _tool_id, _result, _is_error, _tool_call_id: None
    )
    on_started: Callable[[], None] = lambda: None
    on_finished: Callable[[str], None] = lambda _stopped: None


@dataclass
class Runner:
    """Drive a single
    ``AgentLoop`` run and
    surface chunks to the
    caller's callbacks.

    The runner is a
    *plain dataclass*, not
    a ``textual App``
    widget. It is a thin
    object: it owns the
    per-turn dedupe state
    and the streaming clock
    but delegates every UI
    decision to the
    callbacks. A typical
    caller::

        runner = Runner(
            client=llm,
            tools=tool_list,
            ctx=ctx,
            cb=RunnerCallbacks(
                on_status=app._set_status,
                on_assistant_text=app._append_assistant,
                on_tool_call=app._append_tool,
                on_message=app._append_message,
                on_started=lambda: setattr(
                    app, "_agent_running", True
                ),
                on_finished=lambda stopped: setattr(
                    app, "_agent_running", False
                ),
            ),
        )
        runner.run(user_text)

    """

    client: Any
    tools: list[Any]
    ctx: Any
    cb: RunnerCallbacks
    # R-audit (2026-06-12):
    # ``max_steps=0`` means
    # "unlimited" (the
    # safety nets are the
    # per-run USD cap and the
    # no-progress detector
    # in ``AgentLoop``). Tests
    # that need a hard cap
    # pass an explicit
    # ``max_steps`` here.
    max_steps: int = 0
    # R-audit (2026-06-12):
    # the
    # per-run
    # USD
    # cap.
    # ``0``
    # means
    # "no
    # cap"
    # (use
    # the
    # ``AgentLoop``
    # default
    # of
    # 5
    # USD).
    max_cost_usd: float = 0
    # R-2026-06-15 (Phase 0.1):
    # ``active_loop`` is set
    # to the ``AgentLoop``
    # instance after
    # ``run()`` constructs it,
    # and reset to ``None``
    # when the run finishes.
    # The chat TUI's
    # ``/stop`` slash
    # command reads this
    # attribute to call
    # ``AgentLoop.interrupt()``
    # on the in-flight loop.
    # The attribute is
    # ``None`` when no
    # run is active.
    active_loop: Any = field(
        default=None,
        repr=False,
        compare=False,
    )
    # The first chunk of
    # every turn records
    # ``time.monotonic()``
    # so the speed indicator
    # can render ``42 t/s``.
    # The runner owns this
    # state; the TUI reads
    # ``_stream_t0`` /
    # ``_stream_t0_toks``
    # in ``_render_cost_bar``.
    _stream_t0: float = 0.0
    _stream_t0_toks: int = 0

    def _new_message(
        self,
        role: str,
        content: str,
        tool_name: str | None = None,
    ) -> _ChatMessageLike:
        """Build a chat message
        using the actual
        ``ChatMessage`` type
        from the contracts
        module. The
        ``ChatMessage`` import
        is deferred to runtime
        to keep the runner
        testable without the
        TUI module."""
        from ..contracts import ChatMessage
        return ChatMessage(
            role=role,
            content=content,
            tool_name=tool_name,
        )

    def _new_loop(self) -> AgentLoop:
        """Build a fresh
        ``AgentLoop`` for this
        run. The loop is
        constructed per run
        (not cached) because
        the streaming state
        (``_streaming_tool_ids``,
        ``_streaming_messages``,
        etc.) is owned by the
        loop and we want a
        clean slate every
        time."""
        # R-audit (2026-06-12):
        # the
        # ``max_steps``
        # /
        # ``max_cost_usd``
        # kwargs
        # are
        # forwarded
        # so
        # tests
        # can
        # hard-cap
        # the
        # loop
        # without
        # monkey-patching
        # the
        # class.
        return AgentLoop(
            client=self.client,
            tools=self.tools,
            ctx=self.ctx,
            max_steps=self.max_steps,
            max_cost_usd=self.max_cost_usd,
            # R-audit (2026-06-10): wire
            # the on_tool_result callback
            # so the TUI sees the
            # result of every tool call,
            # not just the request. The
            # callback forwards to the
            # RunnerCallbacks.on_tool_result
            # which the ChatApp uses to
            # append a folded
            # "↳ result: ..." row right
            # under the
            # "calling foo(...)" row.
            on_tool_result=lambda name, output, is_error, tool_id="": (
                self.cb.on_tool_result(
                    name, output, is_error, tool_id
                )
            ),
        )

    def _short_repr(self, d: Any) -> str:
        """Compact one-line
        stringification of
        the tool-call input
        dict. We deliberately
        avoid ``repr`` for
        long inputs to keep
        the chat history
        readable."""
        try:
            s = str(d)
        except Exception:  # noqa: BLE001
            s = "<unrepr>"
        if len(s) > 80:
            s = s[:77] + "..."
        return s

    def run(
        self,
        user_text: str,
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> str:
        """Drive the agent loop
        to completion and
        return the final
        ``stopped`` reason
        (``"end_turn"`` or
        ``"max_steps"``).

        The runner NEVER
        raises. A crash inside
        the agent loop is
        surfaced via
        ``on_message`` with a
        ``"agent crashed: …"``
        system row and the
        return value is
        ``"crashed"``.

        ``prior_messages``
        (R-audit 2026-06-14)
        is a pre-filtered
        list of earlier
        user/assistant turns
        to replay into the
        loop's message list.
        ``None`` means "no
        history" (single-turn
        mode); the TUI passes
        the result of
        ``history_filter.filter_history_for_llm``
        on every turn after
        the first.
        """
        self.cb.on_started()
        self.cb.on_status(_t("thinking"))
        loop = self._new_loop()
        # R-2026-06-15 (Phase 0.1):
        # expose the AgentLoop on
        # the Runner so the chat
        # TUI's ``/stop`` slash
        # command can call
        # ``.interrupt()`` on it.
        # The field is reset to
        # ``None`` in the
        # ``finally`` block below
        # so a stale reference
        # does not survive past
        # the end of the run.
        self.active_loop = loop
        last_text: str = ""
        last_turn: int = 0
        last_tool_call_ids: set[str] = set()
        try:
            bind_trace_id(self.ctx.trace_id)
            self._stream_t0 = 0.0
            self._stream_t0_toks = 0
            # R-audit (2026-06-10): track the
            # (turn, stop_reason) pair we
            # already fired an ``on_assistant_text``
            # for, so the agent loop's
            # post-loop "fire one more
            # on_step" re-emit of the final
            # accumulated response does not
            # cause a duplicate assistant
            # message in the chat history.
            # Without this, MiniMax-M3 (and
            # the Anthropic SDK) both yield
            # two consecutive end_turn
            # chunks -- one from the
            # streaming ``message_delta``
            # event and one from a
            # subsequent re-fold -- and
            # each had a different
            # accumulated text length,
            # so the existing
            # ``resp.text != last_text``
            # check was not enough to
            # suppress the duplicate.
            last_fired_turn_sr: tuple[int, str] | None = None
            for resp in loop.run_stream(
                user_text,
                prior_messages=prior_messages,
            ):
                # First chunk of a
                # turn: stamp the
                # wall clock so the
                # speed indicator
                # can render
                # ``<N> t/s``.
                if self._stream_t0 == 0.0:
                    self._stream_t0 = time.monotonic()
                    # ``self._stream_t0_toks``
                    # is set by the
                    # caller (TUI
                    # _render_cost_bar)
                    # -- the runner
                    # owns the
                    # monotonic clock,
                    # the TUI owns the
                    # token counter.
                current_turn = loop._streaming_turns
                if current_turn != last_turn:
                    # New turn: reset
                    # per-turn
                    # accumulators so
                    # we do not
                    # double-print the
                    # text the
                    # previous turn
                    # already
                    # produced.
                    last_text = ""
                    last_tool_call_ids = set()
                    last_turn = current_turn
                    # Force a re-fire on the
                    # new turn even if the
                    # (turn, sr) pair is
                    # identical to the last
                    # turn's (which only
                    # happens if two turns in
                    # a row both end with
                    # ``end_turn`` -- common).
                    last_fired_turn_sr = None
                # Surface the
                # assistant text
                # once per turn, on
                # the final chunk
                # of that turn.
                sr = resp.stop_reason
                is_turn_final = (
                    sr in (
                        "end_turn",
                        "stop",
                        "max_tokens",
                        "stop_sequence",
                    )
                    or bool(resp.tool_calls)
                )
                if (
                    is_turn_final
                    and resp.text
                    and resp.text != last_text
                ):
                    # Suppress the duplicate
                    # re-emit: only fire if
                    # this (turn, stop_reason)
                    # pair is new.
                    key = (current_turn, sr)
                    if key != last_fired_turn_sr:
                        self.cb.on_assistant_text(resp.text)
                        last_text = resp.text
                        last_fired_turn_sr = key
                # Surface each new
                # tool_use (dedupe
                # by id within the
                # turn).
                for tc in resp.tool_calls:
                    if (
                        tc.get("id", "")
                        in last_tool_call_ids
                    ):
                        continue
                    last_tool_call_ids.add(
                        tc.get("id", "")
                    )
                    self.cb.on_tool_call(
                        tc.get("name", ""),
                        tc.get("input", {}),
                        tc.get("id", ""),
                    )
                # Status bar mirror.
                if sr in ("end_turn", "stop"):
                    self.cb.on_status(_t("ready"))
                elif resp.tool_calls:
                    names = ", ".join(
                        tc["name"]
                        for tc in resp.tool_calls
                    )
                    self.cb.on_status(
                        _t("calling_tool", name=names)
                    )
        except Exception as exc:  # noqa: BLE001
            self.cb.on_message(
                self._new_message(
                    role="system",
                    content=_t("agent_crashed", err=exc),
                )
            )
            self.cb.on_status(_t("agent_finished_crashed"))
            self.cb.on_finished("crashed")
            return "crashed"
        finally:
            # R-2026-06-15 (Phase 0.1):
            # clear the active-loop
            # reference on every
            # exit path so the
            # chat TUI's ``/stop``
            # handler cannot
            # accidentally call
            # ``.interrupt()`` on a
            # loop that has already
            # returned.
            self.active_loop = None
        # Loop returned
        # cleanly.
        final_turns = loop._streaming_turns
        max_steps = loop._streaming_max_steps_reached
        cost_cap = loop._streaming_cost_cap_reached
        if cost_cap:
            # R-audit (2026-06-12):
            # the
            # agent
            # loop
            # exited
            # because
            # the
            # per-run
            # USD
            # cap
            # was
            # hit.
            # Surface
            # this
            # to
            # the
            # user
            # so
            # they
            # know
            # they
            # can
            # raise
            # it
            # or
            # split
            # the
            # task.
            self.cb.on_message(
                self._new_message(
                    role="system",
                    content=(
                        f"agent hit cost cap after "
                        f"{final_turns} turns. Set "
                        f"MANUSIFT_AGENT_MAX_COST_USD to raise "
                        f"it, or ask the agent to continue."
                    ),
                )
            )
            stopped = "cost_cap"
        elif max_steps:
            self.cb.on_message(
                self._new_message(
                    role="system",
                    content=(
                        f"agent hit max_steps={final_turns}; "
                        f"stopped. You can ask the agent to continue."
                    ),
                )
            )
            stopped = "max_steps"
        else:
            stopped = "end_turn"
        self.cb.on_status(
            f"done ({final_turns} turn"
            f"{'s' if final_turns != 1 else ''}, {stopped})"
        )
        self.cb.on_finished(stopped)
        return stopped
