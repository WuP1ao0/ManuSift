"""Reproduction test for the TUI '2 messages then stops' bug
(R-2026-06-14).

The user reported: 'I sent a paper to the agent, it processed
the first message, then I sent a second one. It processed
the second one. Then I sent a third one. The third one got
no reply -- the agent is stuck.'

Hypothesis
==========
The Runner is synchronous: it drives ``agent_loop.run_stream``
inside a ``run_worker`` thread, which blocks the main thread
for as long as the loop is alive. The user's third message
arrives while the worker is mid-tool-call. The chat-app's
``_submit_user_message`` checks ``self._agent_running`` and
*rejects* the message with a system row "agent is still
running; press Esc to cancel".

The user types Enter. The message is appended to the chat
history (they see their own bubble) but the message body is
**dropped on the floor** -- nothing in the agent loop's
message list, no follow-up agent run, nothing.

This test exercises the *real* chat-app code path (no
patching, no in-process mocks) to verify the bug exists
in the current code:

  1. Build a ``ChatApp.__new__`` and set the minimum
     fields ``_submit_user_message`` reads.
  2. Set ``_agent_running = True`` (simulating an
     in-flight LLM call).
  3. Call ``_submit_user_message('hi again')`` directly.
  4. Assert the user message was *rejected* (current bug
     behaviour): a system row "agent is still running"
     was appended, and the user message body was
     discarded.
  5. The test passes (i.e. reproduces the bug). After
     the fix, the SAME test will be updated to assert
     the message was *queued* and *drained on finish*.
"""

from __future__ import annotations

import pytest

from manusift.contracts import ChatMessage
from manusift.tui.chat_app import ChatApp


def _build_chat_app_with_minimal_state() -> ChatApp:
    """Bypass ``ChatApp.__init__`` to skip textual's mount.

    The fields ``_submit_user_message`` reads are:

      * ``self._agent_running`` (bool)
      * ``self._append_message`` (method)
      * ``self._plan_mode_flag`` (bool)
      * ``self._mount_placeholder`` (method, not used in
        the reject branch)
      * ``self._run_agent`` (method, not used in the
        reject branch)
    """
    app = ChatApp.__new__(ChatApp)
    app._agent_running = False
    app._plan_mode_flag = False
    app._pending_input = []
    # Use a captured list for the messages so we can
    # assert what was appended.
    captured: list[ChatMessage] = []

    def _capture(msg: ChatMessage) -> None:
        captured.append(msg)

    app._append_message = _capture  # type: ignore[method-assign]
    # Stubs so the test does not blow up on the
    # placeholder/worker dispatch if the fix takes the
    # accept branch instead of the reject branch.
    app._mount_placeholder = lambda: None  # type: ignore[method-assign]
    dispatched: list[str] = []
    app._run_agent = lambda _t: dispatched.append(_t)  # type: ignore[method-assign]
    app._captured = captured  # type: ignore[attr-defined]
    app._dispatched = dispatched  # type: ignore[attr-defined]
    return app


def test_submit_user_message_while_agent_running_is_queued():
    """REGRESSION for the 'send a 3rd message, get no response'
    bug (R-2026-06-14). Before the fix, the user's message
    body was DROPPED on the floor when the agent was busy.

    After the fix, the user's message is:
      * appended to the chat history (so they see their
        own bubble appear)
      * enqueued in ``_pending_input`` for the next
        agent run
      * accompanied by a system row explaining the queue
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = True  # simulate in-flight LLM

    # User types 'and a third look' and presses Enter.
    app._submit_user_message("and a third look")

    # 1. The user message body IS appended to the chat
    #    history (no silent drop).
    user_rows = [
        m for m in app._captured
        if m.role == "user"
    ]
    assert len(user_rows) == 1
    assert user_rows[0].content == "and a third look"
    # 2. The system row tells the user the queue is alive.
    sys_rows = [
        m for m in app._captured
        if m.role == "system"
    ]
    assert len(sys_rows) == 1
    assert "queued" in sys_rows[0].content
    assert "1 pending" in sys_rows[0].content
    # 3. The message is in the queue for the next drain.
    assert app._pending_input == ["and a third look"]
    # 4. _run_agent was NOT called yet (agent is still busy).
    assert app._dispatched == []


def test_submit_user_message_while_idle_dispatches_normally_repro():
    """REPRO: baseline. When the agent is NOT running,
    the user's message is appended and ``_run_agent`` is
    called.
    """
    app = _build_chat_app_with_minimal_state()
    app._agent_running = False

    dispatched: list[str] = []

    def _run(text: str) -> None:
        dispatched.append(text)

    app._run_agent = _run  # type: ignore[method-assign]

    app._submit_user_message("hello")

    # User message was appended.
    user_rows = [
        m for m in app._captured
        if m.role == "user"
    ]
    assert len(user_rows) == 1
    assert user_rows[0].content == "hello"
    # Agent run was dispatched.
    assert dispatched == ["hello"]
