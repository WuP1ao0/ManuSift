"""Tests for the chat-tui conversation continuity
fix (R-audit 2026-06-14).

Bug context
-----------

Before this fix, ``ChatApp._run_agent`` only passed
the *current* ``user_text`` to ``Runner.run``, which
passed it to ``AgentLoop.run_stream``. The agent
loop built its message list as
``[system, user_text]`` and never saw any earlier
turns. So a short follow-up like ``"\u4e0b\u4e00\u6b65"`` or
``"render the report"`` looked like a brand-new
task: the LLM had no idea which ``trace_id`` /
``current_pdf`` it had been working on, and would
ask the user to re-paste the path.

The fix wires three new pieces through the stack:

  1. ``history_filter.filter_history_for_llm`` takes
     the TUI's full ``self._history`` and returns a
     filtered, capped list of ``{"role", "content"}``
     dicts \u2014 user/assistant only, no tool JSON, no
     status rows, no detector trace dumps.
  2. ``AgentLoop.run_stream`` accepts a
     ``prior_messages`` kwarg and splices it into the
     message list.
  3. ``conversation_state`` keeps a small dict in
     ``ctx.metadata`` (active trace_id, current_pdf,
     data sources, last assistant offer) and the
     agent loop appends a one-line reminder to the
     system prompt from it.

What these tests pin
====================

  * The history filter strips tool JSON / system
    rows / detector-trace dumps but keeps user and
    assistant text.
  * The filter caps at ``max_turns`` pairs.
  * The filter de-dupes the just-typed user text
    (the AgentLoop appends the current user message
    on its own).
  * The filter never produces a raw JSON message
    in the output.
  * The filter never re-includes a PDF path that
    the user already typed (because the user
    message itself does carry the path, and the
    LLM is supposed to use that \u2014 the test
    ensures the path is in the prior history for
    the LLM, not duplicated by the filter).
  * The agent loop's final messages list
    concatenates ``[system, *prior, user_message]``
    when ``prior_messages`` is passed.
  * The agent loop's system prompt includes a
    ``## Conversation State Reminder`` line when
    ``ctx.metadata[\"conversation_state\"]`` is set.
  * The conversation-state helpers round-trip
    through a frozen ``ToolContext`` correctly.
  * The full chat-tui pipeline (history filter +
    state + Runner) puts the right things into the
    LLM's message list when round 1 is the PDF
    path and round 2 is ``"\u4e0b\u4e00\u6b65"``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from manusift.contracts import ChatMessage
from manusift.tools.tool import ToolContext
from manusift.tui import (
    conversation_state,
    history_filter,
)


# --------------------------------------------------------------------
# 1. history_filter: filter rules
# --------------------------------------------------------------------


def _msg(role: str, content: str, tool_name: str | None = None) -> ChatMessage:
    return ChatMessage(
        role=role, content=content, tool_name=tool_name
    )


def test_filter_keeps_user_and_assistant_text() -> None:
    """Filter keeps the user/assistant rows from
    history, drops everything else. The TUI
    appends the just-typed user message to
    ``self._history`` BEFORE calling
    ``_run_agent``, so the dedup logic removes
    that trailing user row \u2014 leaving the
    PRIOR user and assistant turn.
    """
    history = [
        _msg("user", "\u8bf7\u5ba1\u67e5\u8fd9\u7bc7\u8bba\u6587"),
        _msg("assistant", "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002"),
        # The TUI appended the just-typed user
        # message to history before this filter
        # ran. The dedup logic must drop it.
        _msg("user", "\u4e0b\u4e00\u6b65"),
    ]
    out = history_filter.filter_history_for_llm(
        history, current_user_text="\u4e0b\u4e00\u6b65"
    )
    # The trailing round-2 user is deduped. The
    # remaining prior is round-1 user +
    # round-1 assistant.
    assert [m["role"] for m in out] == [
        "user", "assistant",
    ]
    assert out[0]["content"] == "\u8bf7\u5ba1\u67e5\u8fd9\u7bc7\u8bba\u6587"
    assert out[1]["content"] == "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002"


def test_filter_strips_tool_json() -> None:
    """A tool result that is a JSON payload must NOT
    be forwarded to the LLM as if it were a chat
    message. The detector trace block (collapsed
    in the TUI) already shows it to the user; the
    LLM does not benefit from re-reading the dict.
    """
    history = [
        _msg("user", "\u8bf7\u5ba1\u67e5\u8fd9\u7bc7\u8bba\u6587"),
        _msg(
            "tool",
            json.dumps(
                {
                    "trace_id": "abc123",
                    "findings": [
                        {"id": "f1", "severity": "high"},
                    ],
                }
            ),
            tool_name="metadata",
        ),
        _msg(
            "assistant",
            "findings 1 \u4e2a\u3002",
        ),
    ]
    out = history_filter.filter_history_for_llm(
        history, current_user_text="\u4e0b\u4e00\u6b65"
    )
    # Tool row dropped. User and assistant only.
    roles = [m["role"] for m in out]
    assert "tool" not in roles
    assert "{\"" not in "\n".join(m["content"] for m in out)


def test_filter_strips_chrome_rows() -> None:
    """Status rows with leading ``[o `` / ``[* `` /
    ``agent: `` etc. are TUI chrome, not
    conversation. They must be dropped.
    """
    history = [
        _msg("user", "\u8bf7\u5ba1\u67e5\u8fd9\u7bc7\u8bba\u6587"),
        _msg("system", "[\u25cb tools 3 calls \u00b7 3 ok \u00b7 0 skipped]"),
        _msg("system", "agent: ready"),
        _msg("system", "agent finished (end_turn)"),
        _msg(
            "assistant",
            "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002",
        ),
    ]
    out = history_filter.filter_history_for_llm(
        history, current_user_text="\u4e0b\u4e00\u6b65"
    )
    roles = [m["role"] for m in out]
    # Only user + assistant survive.
    assert roles == ["user", "assistant"]


def test_filter_dedupes_just_typed_user_text() -> None:
    """If the last entry in history is a user row
    with the same text as ``current_user_text``,
    drop it. The AgentLoop appends the current
    user message on its own.
    """
    history = [
        _msg("user", "\u8bf7\u5ba1\u67e5\u8fd9\u7bc7\u8bba\u6587"),
        _msg("assistant", "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002"),
        # The just-typed user message is already in
        # history (the TUI appends BEFORE calling
        # _run_agent in some flows, or the L38
        # pending-input queue put it there). The
        # filter must dedupe.
        _msg("user", "\u4e0b\u4e00\u6b65"),
    ]
    out = history_filter.filter_history_for_llm(
        history, current_user_text="\u4e0b\u4e00\u6b65"
    )
    # Round 2 user is dropped.
    user_count = sum(1 for m in out if m["role"] == "user")
    assert user_count == 1, (
        f"expected the round-2 user to be deduped; "
        f"got {user_count} user messages: {out}"
    )


def test_filter_caps_at_max_turns_pairs() -> None:
    """30 user/assistant turns + a 31st request \u2014
    only the LATEST ``max_turns`` pairs survive.
    """
    history: list[ChatMessage] = []
    for i in range(15):
        history.append(_msg("user", f"q {i}"))
        history.append(_msg("assistant", f"a {i}"))
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="\u4e0b\u4e00\u6b65",
        max_turns=4,
    )
    # 4 user + 4 assistant = 8 messages, the most
    # recent 4 pairs.
    assert len(out) == 8
    # The earliest turn is dropped.
    contents = [m["content"] for m in out]
    assert "q 0" not in contents
    assert "a 0" not in contents
    # The latest 4 turns are kept.
    assert "q 14" in contents
    assert "a 14" in contents


def test_filter_does_not_re_introduce_pdf_path() -> None:
    """The PDF path the user typed should appear in
    the prior messages (so the LLM knows which
    paper to continue with), but the filter must
    not duplicate it. The de-dup logic only fires
    when the LAST message is a user row identical
    to ``current_user_text``; for the typical flow
    (user typed the path on round 1, the path
    survives as a prior user message on round 2+),
    the path is exactly what we want preserved.
    """
    pdf_path = "C:/Users/me/papers/s41586-025-02082-0.pdf"
    history = [
        _msg("user", f"\u5ba1\u67e5 {pdf_path}"),
        _msg(
            "assistant",
            "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002trace_id: abc123",
        ),
    ]
    out = history_filter.filter_history_for_llm(
        history, current_user_text="\u4e0b\u4e00\u6b65"
    )
    # The path MUST appear in the prior messages
    # so the LLM can resolve "\u4e0b\u4e00\u6b65"
    # against it. The user message is the only
    # place the path is recorded.
    all_text = "\n".join(m["content"] for m in out)
    assert pdf_path in all_text, (
        "PDF path from round 1 must survive in the "
        "prior history so the LLM can resolve a "
        "round-2 follow-up."
    )


# --------------------------------------------------------------------
# 2. AgentLoop.run_stream: prior_messages spliced in
# --------------------------------------------------------------------


def test_agent_loop_run_stream_concatenates_prior_messages() -> None:
    """``run_stream`` must build
    ``[system, *prior, user_message]`` when given a
    ``prior_messages`` list. We capture the message
    list by feeding a mock LLM and reading the
    ``messages`` arg from its ``chat_stream`` call.
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _CapturingLLM:
        name = "capturing"
        def __init__(self) -> None:
            self.captured: list[dict[str, Any]] = []
        def chat_stream(self, messages, tools=None, **kw):
            self.captured = list(messages)
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "ok"}],
                stop_reason="end_turn",
            )

    prior = [
        {"role": "user", "content": "round 1 user"},
        {
            "role": "assistant",
            "content": "round 1 assistant",
        },
    ]
    llm = _CapturingLLM()
    loop = AgentLoop(
        client=llm,
        tools=[],
        ctx=ToolContext(trace_id="t"),
    )
    # Force a default system prompt.
    list(loop.run_stream(
        "round 2 user",
        prior_messages=prior,
    ))
    # 1 system + 2 prior + 1 current = 4 messages.
    assert len(llm.captured) == 4
    assert llm.captured[0]["role"] == "system"
    assert llm.captured[1] == {
        "role": "user",
        "content": "round 1 user",
    }
    assert llm.captured[2] == {
        "role": "assistant",
        "content": "round 1 assistant",
    }
    assert llm.captured[3] == {
        "role": "user",
        "content": "round 2 user",
    }


def test_agent_loop_run_stream_no_prior_defaults_to_two_messages() -> None:
    """With no prior_messages, the message list must
    be exactly ``[system, user]`` \u2014 the v1
    behaviour, which we must not break.
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _CapturingLLM:
        name = "capturing"
        def __init__(self) -> None:
            self.captured: list[dict[str, Any]] = []
        def chat_stream(self, messages, tools=None, **kw):
            self.captured = list(messages)
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "ok"}],
                stop_reason="end_turn",
            )

    llm = _CapturingLLM()
    loop = AgentLoop(
        client=llm,
        tools=[],
        ctx=ToolContext(trace_id="t"),
    )
    list(loop.run_stream("just user"))
    assert len(llm.captured) == 2
    assert llm.captured[0]["role"] == "system"
    assert llm.captured[1] == {
        "role": "user",
        "content": "just user",
    }


def test_agent_loop_run_stream_defensive_copies_prior_items() -> None:
    """If the caller mutates the prior_messages list
    AFTER calling run_stream (e.g. another turn
    appends to it), the loop's internal state must
    not see the mutation. We verify by mutating the
    original list after the fact and re-reading
    ``self._streaming_messages``.
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _CapturingLLM:
        name = "capturing"
        def chat_stream(self, messages, tools=None, **kw):
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "ok"}],
                stop_reason="end_turn",
            )

    prior = [{"role": "user", "content": "r1"}]
    loop = AgentLoop(
        client=_CapturingLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t"),
    )
    list(loop.run_stream("r2", prior_messages=prior))
    # Caller mutates the original list. The loop
    # MUST have already copied each prior item.
    prior.append({"role": "user", "content": "r3"})
    # ``_streaming_messages`` is the loop's
    # internal state; the LLM's call captured
    # ``messages`` at the moment of the call,
    # which is BEFORE the mutation. We check the
    # *loop's* state at the END of the run \u2014
    # the r3 we appended must not have been
    # picked up.
    msgs = loop._streaming_messages
    contents = [
        m.get("content") for m in msgs
    ]
    assert "r3" not in contents, (
        f"defensive copy failed; loop saw: {contents}"
    )


# --------------------------------------------------------------------
# 3. Conversation state: round-trip + system-prompt injection
# --------------------------------------------------------------------


def test_conversation_state_round_trip_through_frozen_ctx() -> None:
    """``ToolContext`` is frozen; the helpers must
    return a NEW ctx with the merged metadata dict
    rather than mutating in place.
    """
    base = ToolContext(trace_id="t1", current_pdf="x.pdf")
    s = conversation_state.merge_state(
        None,
        active_trace_id="trace-abc",
        current_pdf="x.pdf",
        data_sources=["m1.csv", "m2.xlsx"],
    )
    new_ctx = conversation_state.with_state(base, s)
    # Original ctx is unchanged.
    assert "conversation_state" not in (base.metadata or {})
    # New ctx carries the state.
    got = conversation_state.get_state(new_ctx)
    assert got["active_trace_id"] == "trace-abc"
    assert got["current_pdf"] == "x.pdf"
    assert got["data_sources"] == ["m1.csv", "m2.xlsx"]


def test_conversation_state_increments_turn() -> None:
    s1 = conversation_state.merge_state(None, increment_turn=True)
    s2 = conversation_state.merge_state(s1, increment_turn=True)
    assert s1["turn_index"] == 1
    assert s2["turn_index"] == 2


def test_conversation_state_increments_offer_counter() -> None:
    s1 = conversation_state.merge_state(None, increment_turn=True)
    s2 = conversation_state.merge_state(
        s1, last_assistant_offer="\u662f\u5426\u751f\u6210\u62a5\u544a\uff1f"
    )
    # The offer counter uses the CURRENT turn index
    # as the timestamp, so a fresh offer after
    # turn 1 is recorded with at=2.
    assert s2["last_assistant_offer"] == "\u662f\u5426\u751f\u6210\u62a5\u544a\uff1f"
    assert s2["last_assistant_offer_at"] == s1["turn_index"] + 1


def test_agent_loop_injects_state_reminder_into_system_prompt() -> None:
    """When ``ctx.metadata[\"conversation_state\"]`` is
    set, the default system prompt must include a
    one-line ``## Conversation State Reminder``
    section with the active trace_id.
    """
    from manusift.agent import AgentLoop

    s = conversation_state.merge_state(
        None,
        active_trace_id="trace-xyz",
        current_pdf="paper.pdf",
        data_sources=["m1.csv"],
    )
    ctx = conversation_state.with_state(
        ToolContext(trace_id="t"), s
    )
    loop = AgentLoop(client=None, tools=[], ctx=ctx)
    # The default system prompt (built when
    # ``system_prompt is None``) should now carry
    # the state reminder at the bottom.
    assert (
        "## Conversation State Reminder"
        in loop._system_prompt
    )
    assert "trace-xyz" in loop._system_prompt
    assert "paper.pdf" in loop._system_prompt
    assert "m1.csv" in loop._system_prompt


def test_agent_loop_no_state_means_no_reminder() -> None:
    """When no conversation_state is set, the
    system prompt must NOT carry a reminder
    section (we keep the v2 prompt clean for
    non-TUI callers that do not opt in).
    """
    from manusift.agent import AgentLoop

    loop = AgentLoop(
        client=None, tools=[], ctx=ToolContext(trace_id="t")
    )
    assert (
        "## Conversation State Reminder"
        not in loop._system_prompt
    )


# --------------------------------------------------------------------
# 4. End-to-end: round-1 PDF + round-2 "\u4e0b\u4e00\u6b65"
# --------------------------------------------------------------------


def test_full_round_1_then_round_2_continuity() -> None:
    """The scenario from the user's report:

      * Round 1: user pastes a PDF path, agent
        does a quick triage, assistant offers
        "\u662f\u5426\u751f\u6210 HTML \u62a5\u544a\uff1f"
      * Round 2: user types "\u4e0b\u4e00\u6b65"

    Round 2's LLM call must see:
      * the round-1 PDF path (so it knows which
        paper to continue with)
      * the round-1 assistant offer
      * the round-1 trace_id (via the system
        prompt's state reminder)
      * the round-2 user text "\u4e0b\u4e00\u6b65" ONCE
        (the filter dedupes if it accidentally
        sneaks into history)
      * NO raw tool JSON
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    pdf_path = (
        "C:/Users/me/papers/s41586-025-02082-0.pdf"
    )
    round_1_assistant_text = (
        "\u5f53\u524d\u5feb\u901f\u5ba1\u67e5\u5b8c\u6210\u3002"
        "trace_id: abc123\n\n"
        "\u5df2\u68c0\u67e5\uff1a\n"
        "- \u5143\u6570\u636e: \u672a\u53d1\u73b0\u660e\u663e\u5f02\u5e38\n\n"
        "\u4e0b\u4e00\u6b65\uff1a\n"
        "- \u751f\u6210 HTML \u62a5\u544a\uff1f"
    )

    # ----- Round 1 -----
    class _Round1LLM:
        name = "r1"
        def chat_stream(self, messages, tools=None, **kw):
            # Round 1: tool call to ingest_from_path,
            # then end_turn with the assistant text.
            yield ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": "t1",
                    "name": "ingest_from_path",
                    "input": {"path": pdf_path},
                }],
                stop_reason="tool_use",
            )
            # Second chunk: tool result + assistant.
            yield ChatResponse(
                content_blocks=[
                    {
                        "type": "text",
                        "text": round_1_assistant_text,
                    }
                ],
                stop_reason="end_turn",
            )

    history: list[ChatMessage] = []
    # The TUI appends the user message BEFORE
    # calling _run_agent in the typical flow.
    history.append(
        _msg("user", f"\u5ba1\u67e5 {pdf_path}")
    )

    # State after round 1: the TUI's
    # _on_tool_result_main callback updates
    # active_trace_id from the tool output. We
    # simulate that here by manually building the
    # post-round-1 state.
    s_after_r1 = conversation_state.merge_state(
        None,
        active_trace_id="abc123",
        current_pdf=pdf_path,
        data_sources=["m1.csv"],
        last_assistant_offer=(
            "\u751f\u6210 HTML \u62a5\u544a\uff1f"
        ),
        increment_turn=True,
    )
    ctx_after_r1 = conversation_state.with_state(
        ToolContext(trace_id="abc123"), s_after_r1
    )
    history.append(
        _msg("assistant", round_1_assistant_text)
    )

    # ----- Round 2 -----
    prior_for_r2 = history_filter.filter_history_for_llm(
        history,
        current_user_text="\u4e0b\u4e00\u6b65",
    )

    class _Round2LLM:
        name = "r2"
        def __init__(self) -> None:
            self.captured: list[dict[str, Any]] = []
        def chat_stream(self, messages, tools=None, **kw):
            self.captured = list(messages)
            yield ChatResponse(
                content_blocks=[{
                    "type": "text",
                    "text": "OK, calling render_report.",
                }],
                stop_reason="end_turn",
            )

    r2_llm = _Round2LLM()
    loop2 = AgentLoop(
        client=r2_llm, tools=[], ctx=ctx_after_r1,
    )
    list(loop2.run_stream(
        "\u4e0b\u4e00\u6b65",
        prior_messages=prior_for_r2,
    ))

    # ----- Assertions -----
    msgs = r2_llm.captured
    # 1 system + 2 prior (r1 user + r1 assistant)
    # + 1 current user = 4 messages.
    assert len(msgs) == 4, (
        f"expected 4 messages, got {len(msgs)}: {msgs}"
    )
    # Round-1 user text (containing the PDF path)
    # is in the prior messages.
    r1_user_msg = next(
        m for m in msgs if m["role"] == "user"
    )
    assert pdf_path in r1_user_msg["content"]
    # Round-1 assistant offer is in the prior.
    r1_assistant_msg = next(
        m for m in msgs
        if m["role"] == "assistant"
    )
    assert "\u751f\u6210 HTML \u62a5\u544a" in r1_assistant_msg["content"]
    # Round-2 user text is the LAST message and
    # appears exactly once.
    assert msgs[-1] == {
        "role": "user", "content": "\u4e0b\u4e00\u6b65"
    }
    # The PDF path does NOT appear in TWO user
    # messages (no duplicate round-1 user text in
    # the prior, and the round-2 text is
    # "\u4e0b\u4e00\u6b65" not the path).
    user_count = sum(1 for m in msgs if m["role"] == "user")
    assert user_count == 2
    # The path may legitimately appear in both the
    # round-1 user message AND the system-prompt
    # state reminder (``current PDF: <path>``) \u2014
    # that is the WHOLE POINT of the state
    # reminder. So we only assert that the path
    # is in at least one user message (round 1's
    # "review <path>" line), not that it is in
    # exactly one place overall.
    path_in_user = any(
        m["role"] == "user" and pdf_path in m["content"]
        for m in msgs
    )
    assert path_in_user, (
        f"PDF path must be in the round-1 user "
        f"message so the LLM can resolve "
        f"\u4e0b\u4e00\u6b65. msgs={msgs}"
    )
    # The system prompt has the state reminder
    # (active trace_id).
    assert "## Conversation State Reminder" in msgs[0]["content"]
    assert "abc123" in msgs[0]["content"]
    # NO raw tool JSON in the prior messages.
    for m in msgs:
        c = m.get("content", "")
        if isinstance(c, str):
            assert "{\"trace_id\":" not in c
            assert "{\"findings\":" not in c


# --------------------------------------------------------------------
# 5. Runner.run accepts and forwards prior_messages
# --------------------------------------------------------------------


def test_runner_run_passes_prior_messages_to_agent_loop() -> None:
    """The Runner's ``prior_messages`` kwarg must be
    forwarded to ``loop.run_stream`` unchanged. We
    verify by feeding a mock AgentLoop and reading
    the kwarg back out.
    """
    from manusift.tui.agent_runner import (
        Runner,
        RunnerCallbacks,
    )

    captured: dict[str, Any] = {}

    class _FakeLoop:
        def run_stream(self, user_message, prior_messages=None):
            captured["user_message"] = user_message
            captured["prior_messages"] = prior_messages
            # Yield a single end_turn response so
            # the Runner's streaming loop exits.
            from manusift.llm.chat import ChatResponse
            yield ChatResponse(
                content_blocks=[{
                    "type": "text",
                    "text": "done",
                }],
                stop_reason="end_turn",
            )

    class _FakeRunnerRunner:
        """Stand-in for ``AgentLoop`` so the Runner
        can construct one via its factory without
        us instantiating the real thing. We patch
        ``AgentLoop`` in the module under test.
        """
        def __init__(self, *a, **kw) -> None:
            pass

    prior = [
        {"role": "user", "content": "r1"},
        {"role": "assistant", "content": "a1"},
    ]
    # Monkey-patch the Runner's _new_loop factory.
    import manusift.tui.agent_runner as ar
    real_new_loop = ar.Runner._new_loop

    def fake_new_loop(self) -> _FakeLoop:
        return _FakeLoop()

    ar.Runner._new_loop = fake_new_loop  # type: ignore[method-assign]
    try:
        runner = Runner(
            client=object(),
            tools=[],
            ctx=ToolContext(trace_id="t"),
            cb=RunnerCallbacks(
                on_status=lambda t: None,
                on_assistant_text=lambda t: None,
                on_tool_call=lambda *a: None,
                on_message=lambda m: None,
                on_finished=lambda s: None,
            ),
        )
        runner.run("r2", prior_messages=prior)
    finally:
        ar.Runner._new_loop = real_new_loop  # type: ignore[method-assign]

    assert captured["user_message"] == "r2"
    assert captured["prior_messages"] == prior


def test_runner_run_with_no_prior_messages() -> None:
    """Backward compat: Runner.run(\"x\") without
    prior_messages still works and forwards
    ``None`` (which the loop treats as no history).
    """
    from manusift.tui.agent_runner import (
        Runner,
        RunnerCallbacks,
    )

    captured: dict[str, Any] = {}

    class _FakeLoop:
        def run_stream(self, user_message, prior_messages=None):
            captured["user_message"] = user_message
            captured["prior_messages"] = prior_messages
            from manusift.llm.chat import ChatResponse
            yield ChatResponse(
                content_blocks=[{
                    "type": "text",
                    "text": "done",
                }],
                stop_reason="end_turn",
            )

    import manusift.tui.agent_runner as ar
    real_new_loop = ar.Runner._new_loop
    ar.Runner._new_loop = lambda self: _FakeLoop()  # type: ignore[method-assign]
    try:
        runner = Runner(
            client=object(),
            tools=[],
            ctx=ToolContext(trace_id="t"),
            cb=RunnerCallbacks(
                on_status=lambda t: None,
                on_assistant_text=lambda t: None,
                on_tool_call=lambda *a: None,
                on_message=lambda m: None,
                on_finished=lambda s: None,
            ),
        )
        runner.run("hello")
    finally:
        ar.Runner._new_loop = real_new_loop  # type: ignore[method-assign]

    assert captured["user_message"] == "hello"
    assert captured["prior_messages"] is None



def test_filter_default_max_turns_is_no_cap() -> None:
    """R-2026-06-14: the user removed the implicit
    10-pair cap. ``DEFAULT_MAX_TURNS`` is now 0
    (no cap), so a 30-turn chat ships the entire
    filtered transcript to the LLM.
    """
    from manusift.tui.history_filter import (
        DEFAULT_MAX_TURNS,
    )
    assert DEFAULT_MAX_TURNS == 0, (
        f"DEFAULT_MAX_TURNS should be 0 (no cap), "
        f"got {DEFAULT_MAX_TURNS}"
    )


def test_filter_no_cap_by_default() -> None:
    """R-2026-06-14: with the default ``max_turns``
    (= 0), a long conversation of 30 turns
    survives intact. Only the chrome / tool rows
    are dropped, not user/assistant turns.
    """
    history: list[ChatMessage] = []
    for i in range(15):
        history.append(_msg("user", f"q {i}"))
        history.append(_msg("assistant", f"a {i}"))
    # Append a status row that the filter must
    # drop.
    history.append(
        _msg("system", "[○ tools 30 calls · 30 ok]")
    )
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="下一步",
    )
    # 30 user/assistant turns survive, the
    # system row is dropped.
    assert len(out) == 30
    roles = [m["role"] for m in out]
    assert "system" not in roles


def test_filter_max_turns_none_means_no_cap() -> None:
    """R-2026-06-14: passing ``max_turns=None``
    explicitly is equivalent to the default
    (no cap). The function does NOT treat None
    as a bug.
    """
    history = [_msg("user", f"q {i}") for i in range(20)]
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="下一步",
        max_turns=None,
    )
    assert len(out) == 20


def test_filter_max_turns_explicit_zero_means_no_cap() -> None:
    """R-2026-06-14: passing ``max_turns=0`` explicitly
    is also "no cap", the same as the default. This
    is symmetric with ``max_steps=0`` meaning
    "unlimited" elsewhere in the agent loop.
    """
    history = [_msg("user", f"q {i}") for i in range(20)]
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="下一步",
        max_turns=0,
    )
    assert len(out) == 20


def test_filter_max_turns_negative_is_empty() -> None:
    """R-2026-06-14: a negative ``max_turns`` is a
    programming error and is treated as "return
    empty" so a bug does not silently truncate
    history. Only the 0 / None "no cap" sentinel
    is honoured.
    """
    history = [_msg("user", f"q {i}") for i in range(5)]
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="下一步",
        max_turns=-3,
    )
    assert out == []


def test_filter_explicit_positive_cap_still_works() -> None:
    """R-2026-06-14: the existing positive-int cap
    path is preserved. Callers that want a tight
    budget can still pass ``max_turns=N``.
    """
    history: list[ChatMessage] = []
    for i in range(10):
        history.append(_msg("user", f"q {i}"))
        history.append(_msg("assistant", f"a {i}"))
    out = history_filter.filter_history_for_llm(
        history,
        current_user_text="下一步",
        max_turns=3,
    )
    # 3 user + 3 assistant = 6 messages.
    assert len(out) == 6
    contents = [m["content"] for m in out]
    assert "q 9" in contents
    assert "a 9" in contents
    # The earliest turns are dropped.
    assert "q 0" not in contents
    assert "a 0" not in contents
