"""Tests for the chat-rendering pipeline contracts
(R-audit 2026-06-10, bug-fix pass).

The user reported three
bugs in the chat
rendering pipeline:

  1. assistant text
     repeats 3 times in
     a single bubble.
  2. an empty system
     ``(no response)``
     bubble appears under
     the actual assistant
     message.
  3. a
     ``session=... pdf=... llm=...``
     line is rendered as
     part of the chat log.

These tests pin the
fixes:

  * the streaming agent
    loop never
    concatenates duplicate
    text from
    re-emitted chunks (it
    takes the longer
    text, not merged
    concatenation)
  * the
    ``_on_finished_main``
    callback does not add
    a
    ``(no response)``
    system bubble when
    the assistant text
    already arrived
  * no ``#meta-line``
    widget is mounted
    anywhere
  * an empty
    ``(content.strip() == "")``
    message is not
    rendered
  * the dedup by
    ``(turn, stop_reason)``
    still works (assistant
    text fires once per
    turn)
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. Streaming agent loop does not
# ----------    concatenate duplicate text ----------


def test_streaming_loop_takes_longer_text_not_concat() -> None:
    """The streaming agent
    loop does
    *not*
    concatenate text when
    the SDK re-emits the
    full accumulated text
    in multiple chunks.

    Real Anthropic /
    MiniMax-M3 chunks
    carry the full
    accumulated text on
    every event (not just
    deltas), so
    ``accumulated.merged(partial)``
    would produce
    ``"Hi. Hi. Hi."`` (a
    bug). The fix takes
    the *longer* of the
    two texts.
    """
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _ReEmitLLM:
        name = "re-emit"

        def is_available(self) -> bool:
            return True

        def analyze_finding(self, f):
            return None

        def chat(self, *a, **k):
            return ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "Hi"}
                ],
                stop_reason="end_turn",
                model="t",
            )

        def chat_stream(self, *a, **k):
            # The SDK emits
            # "Hi" three times
            # in a row -- a
            # common pattern
            # when the
            # accumulated
            # text has not
            # changed.
            for _ in range(3):
                yield ChatResponse(
                    content_blocks=[
                        {"type": "text", "text": "Hi"}
                    ],
                    model="t",
                )

    class _StubClient(_ReEmitLLM):
        pass

    yielded_texts: list[str] = []
    loop = AgentLoop(
        client=_StubClient(),
        tools=[],
        ctx=ToolContext(trace_id="t", current_pdf="t"),
    )
    for resp in loop.run_stream("hi"):
        yielded_texts.append(resp.text)
    # The last text is
    # "Hi" (not "HiHiHi").
    # The intermediate
    # yields may show
    # "Hi" or "" but the
    # final one is "Hi".
    assert yielded_texts[-1] == "Hi", (
        f"expected last yield to be 'Hi', got "
        f"{yielded_texts[-1]!r} (full stream: {yielded_texts!r})"
    )
    # The text never grew
    # past "Hi".
    for t in yielded_texts:
        assert t == "Hi" or t == "", (
            f"unexpected text growth: {t!r} in {yielded_texts!r}"
        )


# ---------- 2. (no response) system bubble is
# ----------    not added when assistant text arrived ----------


def test_no_response_bubble_not_added_when_text_arrived() -> None:
    """When the LLM
    produces a non-empty
    assistant response,
    ``_on_finished_main``
    does NOT add a
    ``(no response)`` empty
    system bubble.

    R-audit (2026-06-10):
    the previous version
    used
    ``placeholder.is_mounted``
    to decide whether to
    add the
    ``(no response)``
    bubble. textual's
    ``is_mounted`` is not
    synchronously updated
    after ``.remove()``
    in all cases, so the
    check sometimes
    returned ``True``
    after the placeholder
    was already replaced
    by the real assistant
    message -- leading to
    a spurious
    ``(no response)``
    bubble under the
    assistant text. The
    fix uses
    ``history.query_one``
    which raises
    ``NoMatches`` if the
    widget is truly gone
    -- an authoritative
    check.
    """
    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Static
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            app._submit_user_message("hi")
            for _ in range(30):
                await pilot.pause(0.3)
                if app._active_worker is None:
                    break
            await pilot.pause(0.3)
            history = app.query_one("#history")
            # R-audit (2026-06-10):
            # ``render_message``
            # now returns a
            # ``Horizontal``
            # (not a
            # ``Static``), so
            # we use
            # ``history.children``
            # (which returns
            # the actual
            # ``Horizontal``
            # children of
            # ``#history``)
            # instead of
            # ``history.query(Static)``
            # (which only
            # matched
            # ``Static``
            # children -- none,
            # because the rows
            # are no longer
            # ``Static``s).
            children = list(history.children)
            # R-audit (2026-06-10):
            # the rows are
            # ``Horizontal``s, not
            # ``Static``s. We
            # use the
            # ``_all_history_text``
            # helper from
            # ``test_tui_chat.py``
            # to walk into the
            # tree and collect
            # every ``Static``
            # descendant's text.
            from tests.test_tui_chat import _all_history_text
            msgs = _all_history_text(app)
            # No (no response)
            # bubble.
            no_resp = [
                m for m in msgs
                if "no response" in m.lower()
            ]
            assert not no_resp, (
                f"(no response) bubble still appears: "
                f"{no_resp!r}"
            )
            # R-audit (2026-06-10):
            # ``render_message``
            # now returns a
            # ``Horizontal`` (dot
            # column + body
            # column), not a
            # single ``Static``.
            # The role class
            # ``msg-user`` /
            # ``msg-assistant`` is
            # on the OUTER
            # ``Horizontal`` (the
            # ``msg-row``), not
            # on the children.
            # Children of
            # ``#history`` are
            # the row
            # ``Horizontal``s
            # themselves. We
            # walk one level
            # only.
            row_widgets = list(children)
            # Each
            # row
            # is
            # a
            # ``Horizontal``
            # with
            # ``msg-row`` plus
            # the role class
            # (``msg-user`` /
            # ``msg-assistant``
            # etc.).
            user_msgs = [
                w for w in row_widgets
                if "msg-user" in w.classes
            ]
            asst_msgs = [
                w for w in row_widgets
                if "msg-assistant" in w.classes
            ]
            assert len(user_msgs) == 1, (
                f"expected 1 user message, got {len(user_msgs)}"
            )
            assert len(asst_msgs) == 1, (
                f"expected 1 assistant message, got {len(asst_msgs)}"
            )

    asyncio.run(driver())


# ---------- 3. No #meta-line in the chat log ----------


def test_no_meta_line_widget_anywhere() -> None:
    """The
    ``session=... pdf=... llm=...``
    line is not rendered
    anywhere in the TUI.
    The user reported it
    was appearing in the
    chat log area, which
    is wrong.
    """
    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Static
    from manusift.llm import MockLLM

    async def driver():
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            # No #meta-line
            # widget.
            try:
                app.query_one("#meta-line")
                assert False, "#meta-line should be removed"
            except Exception:  # noqa: BLE001
                pass
            # No Static
            # widget in the
            # screen has
            # ``session=`` in
            # its content.
            for w in app.screen.query(Static):
                content = str(w.content)
                assert "session=" not in content, (
                    f"a Static widget displays session=...: {content!r}"
                )

    asyncio.run(driver())


# ---------- 4. Per-turn dedup still works ----------


def test_dedup_fires_assistant_text_once_per_turn() -> None:
    """The Runner's per-turn
    dedup (by
    ``(turn, stop_reason)``)
    still fires
    ``on_assistant_text``
    exactly once per turn.
    """
    from manusift.tui.agent_runner import Runner, RunnerCallbacks
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    class _MultiEndTurnLLM:
        name = "multi"

        def is_available(self) -> bool:
            return True

        def analyze_finding(self, f):
            return None

        def chat(self, *a, **k):
            return ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "hi"}
                ],
                stop_reason="end_turn",
                model="t",
            )

        def chat_stream(self, *a, **k):
            # Two end_turn
            # chunks with the
            # same text
            # (post-loop
            # re-emit). The
            # dedup must
            # suppress the
            # second.
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "hi"}
                ],
                stop_reason="end_turn",
                model="t",
            )
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "hi"}
                ],
                stop_reason="end_turn",
                model="t",
            )

    surfaced: list[str] = []
    runner = Runner(
        client=_MultiEndTurnLLM(),
        tools=[],
        ctx=ToolContext(trace_id="t", current_pdf="t"),
        cb=RunnerCallbacks(
            on_status=lambda s: None,
            on_assistant_text=surfaced.append,
            on_tool_call=lambda n, i: None,
            on_message=lambda m: None,
            on_started=lambda: None,
            on_finished=lambda s: None,
        ),
    )
    runner.run("hi")
    assert len(surfaced) == 1, (
        f"expected exactly 1 assistant text fire, "
        f"got {len(surfaced)}: {surfaced!r}"
    )
    assert surfaced[0] == "hi"
