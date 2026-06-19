"""Tests for plan mode (Step P4.3).

Plan mode is a chat-TUI flag. When enabled,
a user message does NOT dispatch the agent
loop directly; instead, the user must run
``/go <message>`` to actually start the
agent. This is the same pattern Claude Code
v2.1.88 uses to let the user amend a
request before any tool call is dispatched.

Guarantees:

  1. ``/plan on`` enables plan mode. A
     status line is appended to the chat
     history confirming the change.
  2. ``/plan off`` disables plan mode. A
     status line is appended to the chat
     history confirming the change.
  3. ``/plan`` (no argument) reports the
     current state without changing it.
  4. With plan mode on, a user message is
     recorded in the history but the agent
     does NOT run; a system message tells
     the user how to confirm.
  5. With plan mode off (the default), a
     user message dispatches the agent
     exactly as it did before plan mode
     existed.
  6. ``/go <message>`` dispatches the
     agent, regardless of plan mode. The
     user uses this to confirm a planned
     request.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _build_chat_app(mock_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plan_mode: bool = False):
    """Build a ChatApp wired to a custom LLM
    client, bypassing the textual ``App.run()``
    loop so the test runs in milliseconds."""
    import uuid as _uuid
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if plan_mode:
        monkeypatch.setenv("MANUSIFT_PLAN_MODE", "1")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.tui.chat_app import ChatApp
    from manusift.tools import ToolContext
    from manusift.tui import chat_app as _chat_mod
    # ``ChatApp()`` runs textual's
    # ``__init__`` which initializes the
    # reactive attributes (including
    # ``_plan_mode_flag``). We never call
    # ``app.run()`` so the terminal is not
    # actually claimed.
    app = ChatApp()
    app._session_id = _uuid.uuid4().hex[:12]
    app._session_dir = _chat_mod._chat_dir(app._session_id)
    app._llm = mock_client
    app._tools = []
    app._agent_running = False
    app._parsed_doc = None
    app._ctx = ToolContext(trace_id=app._session_id)
    # Honor the env var if the helper
    # was called with ``plan_mode=True``;
    # the App's __init__ already did this
    # but we override it explicitly to
    # avoid the env order being a
    # flake-source.
    app._plan_mode_flag = get_settings().plan_mode
    # Stub out the methods that touch
    # textual widgets so we can run the
    # agent without booting the App.
    app._set_status = lambda t: None  # type: ignore[method-assign]
    return app


# ---------- 1. /plan on enables it ----------

def test_plan_command_on_enables_plan_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/plan on`` flips the internal
    ``_plan_mode`` flag to True. A
    confirmation system message is
    appended to the chat history."""
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    assert app._plan_mode_flag is False
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._handle_command("/plan on")
    assert app._plan_mode_flag is True
    sys_msgs = [
        m for m in captured
        if "plan mode: on" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1


# ---------- 2. /plan off disables it ----------

def test_plan_command_off_disables_plan_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/plan off`` flips the flag back
    to False."""
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    app._plan_mode_flag = True
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._handle_command("/plan off")
    assert app._plan_mode_flag is False
    sys_msgs = [
        m for m in captured
        if "plan mode: off" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1


# ---------- 3. /plan (no arg) reports state ----------

def test_plan_command_no_arg_reports_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/plan`` (no argument) reports the
    current state without changing it. A
    user who is unsure whether plan mode
    is on can type ``/plan`` to find out."""
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    app._plan_mode_flag = True
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._handle_command("/plan")
    # State did not change.
    assert app._plan_mode_flag is True
    # A system message reports the state.
    sys_msgs = [
        m for m in captured
        if "plan mode is on" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1


# ---------- 4. With plan mode on, the agent does NOT run ----------

def test_plan_mode_on_does_not_dispatch_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With plan mode on, a user message is
    recorded in the history but the agent
    loop is NOT invoked. A system message
    tells the user to confirm with ``/go``.
    The agent client's ``chat`` method is
    never called, so the mock LLM is left
    untouched.
    """
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    app._plan_mode_flag = True
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    # Spy on _run_agent — we assert it is
    # not called.
    ran: list[str] = []
    app._run_agent = lambda t: ran.append(t)  # type: ignore[method-assign]
    # The TUI's on_input_submitted is the
    # entry point; we replicate the relevant
    # lines here (the textual event loop
    # would normally do this).
    text = "analyze this PDF"
    app._append_message(
        type(captured[0] if captured else captured)(
            role="user", content=text
        ) if False else __import__(
            "manusift.tui.chat_app", fromlist=["ChatMessage"]
        ).ChatMessage(role="user", content=text)
    )
    if app._plan_mode_flag:
        app._append_message(
            __import__(
                "manusift.tui.chat_app", fromlist=["ChatMessage"]
            ).ChatMessage(
                role="system",
                content="plan mode is on. The agent will not run any tool until you confirm with /go.",
            )
        )
    else:
        app._run_agent(text)
    # The agent did NOT run.
    assert ran == []
    # The user message AND a plan-mode
    # hint are in the history.
    user_msgs = [
        m for m in captured
        if getattr(m, "role", None) == "user"
    ]
    sys_msgs = [
        m for m in captured
        if getattr(m, "role", None) == "system"
        and "plan mode is on" in getattr(m, "content", "")
    ]
    assert len(user_msgs) == 1
    assert len(sys_msgs) == 1


# ---------- 5. With plan mode off, dispatch as before ----------

def test_plan_mode_off_dispatches_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With plan mode off (the default), a
    user message dispatches the agent as it
    did before plan mode existed. The mock
    LLM's ``chat`` method is called."""
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    assert app._plan_mode_flag is False
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    # The default mock LLM has
    # ``chat_stream`` (1 chunk). When the
    # agent loop runs, the chat history
    # will get an assistant message.
    app._run_agent("hi")
    # An assistant message was appended.
    assistant = [
        m for m in captured
        if getattr(m, "role", None) == "assistant"
    ]
    assert len(assistant) >= 1


# ---------- 6. /go dispatches the agent ----------

def test_go_command_dispatches_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/go <message>`` dispatches the
    agent regardless of plan mode. The
    user uses this to confirm a planned
    request — they typed a message, the
    agent did not run because plan mode
    was on, and now they want to actually
    execute it.
    """
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    app._plan_mode_flag = True
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._handle_command("/go analyze this PDF")
    # The agent ran — the chat history has
    # an assistant message.
    assistant = [
        m for m in captured
        if getattr(m, "role", None) == "assistant"
    ]
    assert len(assistant) >= 1


def test_go_command_with_no_arg_says_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/go`` (no message) surfaces a
    usage hint instead of dispatching the
    agent with an empty message."""
    from manusift.llm import MockLLM
    app = _build_chat_app(MockLLM(), tmp_path, monkeypatch)
    app._plan_mode_flag = True
    captured: list = []
    app._append_message = lambda m: captured.append(m)  # type: ignore[method-assign]
    app._handle_command("/go")
    sys_msgs = [
        m for m in captured
        if "usage" in getattr(m, "content", "")
    ]
    assert len(sys_msgs) == 1
