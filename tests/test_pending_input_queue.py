"""Tests for the pending-input queue fix (R-2026-06-14).

The user reported: "I sent a paper to the agent, it processed
the first message, then I sent a second one. It processed
the second one. Then I sent a third one. The third one got
no reply -- the agent is stuck."

Root cause
==========
``ChatApp._submit_user_message`` rejected new input with
"agent is still running; press Esc to cancel" when
``self._agent_running`` was True. The user-typed message
body was *dropped on the floor* -- never appended to
the chat history, never queued, never re-dispatched.

Fix
===
1. When the agent is busy, the user's message is *appended*
   to the chat history (so the user sees their own bubble
   appear) and *enqueued* in ``self._pending_input`` (a
   FIFO list).
2. A one-line system row "queued (N pending) -- the agent
   will pick this up when the current turn finishes"
   tells the user the queue is alive.
3. The runner's ``on_finished`` callback calls
   ``_drain_pending_input()`` when the current turn ends.
   The drain pops the leftmost message, mounts a
   placeholder, and dispatches ``_run_agent(text)`` in the
   normal way. The drain stops after each dispatch if
   ``_agent_running`` flipped to True, so we never run
   two agent loops in parallel.

These tests exercise the *real* chat-app code path
(``ChatApp.__new__`` to skip textual's mount) and
assert the new contract:

  1. Baseline: when the agent is idle, the user's
     message is appended and ``_run_agent`` is called.
  2. When the agent is busy, the user's message is
     appended AND enqueued; a system row reports the
     pending count.
  3. The drain is idempotent: calling
     ``_drain_pending_input`` on an empty queue is a
     no-op.
  4. The drain is FIFO: messages are popped from the
     left in the order they were submitted.
  5. The drain stops at the first dispatch: after
     ``_run_agent`` is called, the drain returns; a
     second call (with another message in the queue)
     picks up the next one.
  6. The drain is re-entrant: a pending message
     submitted while the drain is dispatching the
     previous one is *not* lost -- it stays in the
     queue for the next call.
"""

from __future__ import annotations

import pytest

from manusift.contracts import ChatMessage
from manusift.tui.chat_app import ChatApp


def _build_chat_app_with_minimal_state() -> ChatApp:
    """Bypass ``ChatApp.__init__`` to skip textual's mount.

    The fields ``_submit_user_message`` and
    ``_drain_pending_input`` read are:

      * ``self._agent_running`` (bool)
      * ``self._append_message`` (method)
      * ``self._plan_mode_flag`` (bool)
      * ``self._mount_placeholder`` (method)
      * ``self._run_agent`` (method)
      * ``self._pending_input`` (list[str]) -- initialised
        in ``__init__``, but we set it explicitly here in
        case the field is added in a future refactor.
    """
    app = ChatApp.__new__(ChatApp)
    app._agent_running = False
    app._plan_mode_flag = False
    app._pending_input = []
    # Captured list for messages.
    captured: list[ChatMessage] = []

    def _capture(msg: ChatMessage) -> None:
        captured.append(msg)

    app._append_message = _capture  # type: ignore[method-assign]
    app._mount_placeholder = lambda: None  # type: ignore[method-assign]
    # Default: _run_agent sets _agent_running True (matches
    # the real flow) and records the text.
    dispatched: list[str] = []

    def _run(text: str) -> None:
        dispatched.append(text)
        app._agent_running = True

    app._run_agent = _run  # type: ignore[method-assign]
    app._captured = captured  # type: ignore[attr-defined]
    app._dispatched = dispatched  # type: ignore[attr-defined]
    return app


# ====================================================================
# 1. Baseline: idle agent -> normal dispatch
# ====================================================================


def test_submit_user_message_when_idle_dispatches_normally():
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False

    app._submit_user_message("hello")

    # User message was appended.
    user_rows = [
        m for m in app._captured if m.role == "user"
    ]
    assert len(user_rows) == 1
    assert user_rows[0].content == "hello"
    # Agent run was dispatched.
    assert app._dispatched == ["hello"]
    # Queue is still empty.
    assert app._pending_input == []


# ====================================================================
# 2. Busy agent: queue, do not drop
# ====================================================================


def test_submit_user_message_while_agent_running_is_queued():
    """REGRESSION: the user's 3rd message must NOT be
    dropped when the agent is busy. It is appended to
    the chat history AND enqueued.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True  # simulate in-flight turn

    app._submit_user_message("and a third look")

    # 1. The user message body is in the chat history.
    user_rows = [
        m for m in app._captured if m.role == "user"
    ]
    assert len(user_rows) == 1
    assert user_rows[0].content == "and a third look"
    # 2. The system row tells the user the queue is alive.
    sys_rows = [m for m in app._captured if m.role == "system"]
    assert len(sys_rows) == 1
    assert "queued" in sys_rows[0].content
    assert "1 pending" in sys_rows[0].content
    # 3. The message is in the queue.
    assert app._pending_input == ["and a third look"]
    # 4. _run_agent was NOT called (agent is still busy).
    assert app._dispatched == []


def test_submit_user_message_multiple_queued_in_order():
    """Multiple messages while busy get FIFO ordering."""
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True

    app._submit_user_message("first")
    app._submit_user_message("second")
    app._submit_user_message("third")

    assert app._pending_input == ["first", "second", "third"]
    # The system row reports the count.
    last_sys = [m for m in app._captured if m.role == "system"][-1]
    assert "3 pending" in last_sys.content


# ====================================================================
# 3. _drain_pending_input is idempotent on an empty queue
# ====================================================================


def test_drain_pending_input_is_noop_when_empty():
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False
    assert app._pending_input == []

    app._drain_pending_input()

    # Nothing happened.
    assert app._dispatched == []
    assert app._captured == []
    assert app._pending_input == []


# ====================================================================
# 4. Drain is FIFO
# ====================================================================


def test_drain_pending_input_pops_in_fifo_order():
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True  # simulate: drain happens from on_finished,
    # so agent_running was just set False by on_finished
    # before the drain. But here we test the drain itself:
    # we set it back to False so the drain can run.
    app._agent_running = False
    app._pending_input = ["first", "second", "third"]

    app._drain_pending_input()

    # The drain dispatches the first message, which sets
    # _agent_running to True (per our stub). The drain
    # then stops. The remaining two stay in the queue.
    assert app._dispatched == ["first"]
    assert app._pending_input == ["second", "third"]
    # The drain must NOT re-append the user message to
    # the chat history (it was already appended when the
    # user submitted).
    user_rows = [
        m for m in app._captured if m.role == "user"
    ]
    assert user_rows == []


def test_drain_pending_input_continues_after_turn_finishes():
    """Simulate the realistic on_finished loop:
    1. Drain dispatches message 1, sets _agent_running True.
    2. The new turn runs and finishes; on_finished sets
       _agent_running False and calls _drain_pending_input.
    3. Drain dispatches message 2, etc.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False
    app._pending_input = ["first", "second", "third"]

    # Simulate: on_finished has just been called, the
    # agent is now idle, and the drain runs.
    app._drain_pending_input()  # dispatches "first"
    assert app._dispatched == ["first"]
    assert app._pending_input == ["second", "third"]

    # Simulate: the new turn finished, agent_running is
    # False again, drain runs.
    app._agent_running = False
    app._drain_pending_input()  # dispatches "second"
    assert app._dispatched == ["first", "second"]
    assert app._pending_input == ["third"]

    app._agent_running = False
    app._drain_pending_input()  # dispatches "third"
    assert app._dispatched == ["first", "second", "third"]
    assert app._pending_input == []


# ====================================================================
# 5. Drain stops at the first dispatch (no parallel runs)
# ====================================================================


def test_drain_stops_after_first_dispatch():
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False
    app._pending_input = ["a", "b", "c"]

    app._drain_pending_input()

    # Only "a" was dispatched in this call.
    assert app._dispatched == ["a"]
    # "b" and "c" stay in the queue.
    assert app._pending_input == ["b", "c"]


# ====================================================================
# 6. Drain is re-entrant: new submissions during a drain
#    are preserved, not lost.
# ====================================================================


def test_drain_does_not_lose_new_submissions():
    """If the user submits a 4th message between the drain
    dispatching message 1 and the next call to drain,
    the 4th message must stay in the queue.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False
    app._pending_input = ["first"]

    app._drain_pending_input()  # dispatches "first"
    # Simulate the new turn finished; user submits
    # a new message WHILE the drain is "between turns".
    app._agent_running = False
    # But the user types 2 more things in rapid succession.
    app._agent_running = True  # new turn running
    app._submit_user_message("second")
    app._submit_user_message("third")
    # The new turn finishes; agent_running goes False.
    app._agent_running = False

    # The drain should pick up the 2 messages in order.
    app._drain_pending_input()
    assert app._dispatched == ["first", "second"]
    assert app._pending_input == ["third"]

    # Next turn finishes.
    app._agent_running = False
    app._drain_pending_input()
    assert app._dispatched == ["first", "second", "third"]
    assert app._pending_input == []


# ====================================================================
# 7. Drain does not dispatch when agent_running is True
#    (a new turn somehow started before drain was called)
# ====================================================================


def test_drain_does_nothing_when_agent_running():
    """If a new turn started between the previous on_finished
    and the drain call, the drain must not dispatch another
    agent run -- that would be two parallel runs.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True  # new turn already running
    app._pending_input = ["a", "b"]

    app._drain_pending_input()

    # Nothing was dispatched; the queue is intact.
    assert app._dispatched == []
    assert app._pending_input == ["a", "b"]


# ====================================================================
# 8. The system message reports the right pending count
# ====================================================================


def test_system_message_count_reflects_queue_size():
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True

    app._submit_user_message("a")
    # captured system row should say "1 pending"
    sys1 = [m for m in app._captured if m.role == "system"][-1]
    assert "1 pending" in sys1.content

    app._submit_user_message("b")
    sys2 = [m for m in app._captured if m.role == "system"][-1]
    assert "2 pending" in sys2.content

    app._submit_user_message("c")
    sys3 = [m for m in app._captured if m.role == "system"][-1]
    assert "3 pending" in sys3.content


# ====================================================================
# 9. End-to-end: simulate the real bug scenario
# ====================================================================


def test_e2e_three_messages_while_busy_then_drain():
    """The exact user-reported scenario:

    1. User sends message 1 (agent idle). Agent dispatches
       and starts running.
    2. User sends message 2 (agent busy). Message 2 is
       queued.
    3. User sends message 3 (agent still busy). Message 3
       is queued.
    4. The agent finishes the first turn. on_finished
       drains the queue, dispatching message 2.
    5. The agent finishes message 2. on_finished drains
       again, dispatching message 3.
    6. The agent finishes message 3. on_finished drains
       again, queue is empty, no-op.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False

    # 1. First message.
    app._submit_user_message("first message")
    assert app._dispatched == ["first message"]
    assert app._pending_input == []
    # (After _run_agent, _agent_running is True.)

    # 2 & 3. While the first message is running, user types
    # two more.
    app._submit_user_message("second message")
    app._submit_user_message("third message")
    assert app._pending_input == [
        "second message",
        "third message",
    ]
    # Only the first message was dispatched.
    assert app._dispatched == ["first message"]

    # 4. The first turn finishes; on_finished sets
    # _agent_running False and calls _drain_pending_input.
    app._agent_running = False
    app._drain_pending_input()
    assert app._dispatched == [
        "first message",
        "second message",
    ]
    assert app._pending_input == ["third message"]

    # 5. The second turn finishes; drain again.
    app._agent_running = False
    app._drain_pending_input()
    assert app._dispatched == [
        "first message",
        "second message",
        "third message",
    ]
    assert app._pending_input == []

    # 6. The third turn finishes; drain is a no-op.
    app._agent_running = False
    app._drain_pending_input()
    assert app._dispatched == [
        "first message",
        "second message",
        "third message",
    ]
    assert app._pending_input == []
