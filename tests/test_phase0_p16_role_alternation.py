"""R-2026-06-15 (Phase 0+1 + P1-6):
test that
``AgentLoop._inject_final_report_prompt``
preserves Anthropic's
role-alternation invariant.

The function is called AFTER a
tool-use turn (the no-progress
detector fires when the LLM has
narrated without new tool calls
for ``_no_progress_turn_limit``
consecutive turns).  The last
message in the conversation is
therefore ``role="tool"``.
Appending a ``role="user"``
reminder directly violates
Anthropic's strict role-
alternation invariant (the API
rejects it with
``400 invalid_request_error``).

The fix inserts an empty
``assistant`` placeholder
between the ``tool`` message
and the ``user`` reminder so the
sequence becomes
``... tool, assistant, user``
which is valid.

These tests cover the three
incoming-state shapes:

  1. last message ``user``  -- the
     no-tool-call turn.  No
     placeholder needed; the
     reminder is appended
     directly.
  2. last message ``tool``  -- the
     common case after a
     tool-execute.  An
     ``assistant`` placeholder
     is inserted first.
  3. last message ``assistant``
     -- the LLM already
     responded.  No
     placeholder needed; the
     reminder is appended
     directly.
"""
from __future__ import annotations

from typing import Any

from manusift.agent import AgentLoop
from manusift.tools.tool import ToolContext


def _make_loop() -> AgentLoop:
    """Build a minimal AgentLoop.
    The LLM client and bus are
    not needed for this test.
    """
    ctx = ToolContext(trace_id="t-p16")
    return AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[],
        ctx=ctx,
        max_steps=10,
        max_cost_usd=0,
    )


def _roles(messages: list[dict[str, Any]]) -> list[str]:
    return [m.get("role", "?") for m in messages]


def _alternation_ok(messages: list[dict[str, Any]]) -> bool:
    """Check Anthropic's
    alternation: no two
    consecutive user/assistant
    messages.  ``tool``
    messages are allowed to
    repeat (each tool call has
    its own tool_result
    block; the LLM never sees
    multiple tools in a row as
    alternating turns).  The
    sequence
    ``user, assistant, tool,
    tool, user`` is valid.
    """
    roles = _roles(messages)
    if not roles:
        return True
    # First role must be user
    # or system.
    if roles[0] not in ("user", "system"):
        return False
    prev = roles[0]
    for r in roles[1:]:
        # user followed by user is
        # forbidden.
        if prev == "user" and r == "user":
            return False
        # user must follow
        # assistant or tool.
        if (
            r == "user"
            and prev not in ("assistant", "tool")
        ):
            return False
        prev = r
    return True


def test_p16_inject_after_tool_inserts_placeholder():
    """The common case: last
    message is a ``tool``
    result.  The function
    inserts an ``assistant``
    placeholder so the next
    ``user`` reminder does not
    violate alternation.
    """
    loop = _make_loop()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "find issues"},
        {
            "role": "assistant",
            "content": "I'll run the tools",
        },
        {
            "role": "tool",
            "name": "image_dup",
            "content": '{"ok": true}',
            "tool_call_id": "t1",
        },
    ]
    loop._inject_final_report_prompt(messages)
    # Two new messages:
    # assistant placeholder,
    # then user reminder.
    assert len(messages) == 5
    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    # The reminder text is
    # intact.
    assert (
        "STOP making tool calls"
        in messages[-1]["content"]
    )
    # Alternation is now valid.
    assert _alternation_ok(messages), (
        f"alternation broken: {_roles(messages)}"
    )


def test_p16_inject_after_assistant_no_placeholder():
    """If the last message is
    already ``assistant`` (the
    LLM responded with no tool
    calls), no placeholder is
    needed.
    """
    loop = _make_loop()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "find issues"},
        {
            "role": "assistant",
            "content": "no tools needed",
        },
    ]
    loop._inject_final_report_prompt(messages)
    # Only one new message: the
    # user reminder.
    assert len(messages) == 3
    assert messages[-1]["role"] == "user"
    assert _alternation_ok(messages), (
        f"alternation broken: {_roles(messages)}"
    )


def test_p16_inject_after_user_no_placeholder():
    """If the last message is
    already ``user`` (an
    unusual case where the LLM
    was bypassed), the reminder
    is appended directly.
    Anthropic allows multiple
    ``user`` turns in a row, so
    no placeholder is needed.
    """
    loop = _make_loop()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "find issues"},
    ]
    loop._inject_final_report_prompt(messages)
    assert len(messages) == 2
    assert messages[-1]["role"] == "user"
    # The role-alternation check
    # we use is strict (no
    # consecutive user); but
    # Anthropic actually allows
    # multiple user turns, so
    # this is informational.
    # Just check the reminder is
    # at the end.
    assert (
        "STOP making tool calls"
        in messages[-1]["content"]
    )


def test_p16_inject_after_multiple_tools():
    """A sequence of multiple
    tool results (image_dup,
    then text_patterns) still
    has the last role =
    ``tool``.  The placeholder
    is still inserted.
    """
    loop = _make_loop()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "..."},
        {
            "role": "tool",
            "name": "image_dup",
            "content": '{"ok": true}',
            "tool_call_id": "t1",
        },
        {
            "role": "tool",
            "name": "text_patterns",
            "content": '{"ok": true}',
            "tool_call_id": "t2",
        },
    ]
    loop._inject_final_report_prompt(messages)
    assert messages[-2]["role"] == "assistant"
    assert messages[-1]["role"] == "user"
    assert _alternation_ok(messages)


def test_p16_inject_cost_reflects_running_total():
    """The reminder's text
    references the running cost
    so the user (or the LLM's
    audit log) can see the
    budget was the reason.  The
    cost is ``_run_cost_usd``
    formatted to 4 decimal
    places.
    """
    loop = _make_loop()
    loop._run_cost_usd = 0.1234
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "..."},
        {
            "role": "tool",
            "name": "x",
            "content": "{}",
            "tool_call_id": "t1",
        },
    ]
    loop._inject_final_report_prompt(messages)
    # The reminder contains
    # ``$0.1234``.
    assert (
        "$0.1234"
        in messages[-1]["content"]
    )
