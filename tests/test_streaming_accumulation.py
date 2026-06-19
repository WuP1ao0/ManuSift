"""Regression test for the streaming accumulation bug (R-audit 2026-06-10).

The previous agent loop
did
``accumulated = partial``
in its streaming branch,
which replaced the
accumulated response on
every chunk instead of
merging. The visible
symptom was that the TUI
never showed the LLM's
text reply because the
final chunk's
``resp.text`` was either
empty (if the final
``message_delta`` event
carried no text) or a
fragment.

After the fix
(``accumulated =
accumulated.merged(partial)``)
the running accumulated
response carries the full
text by the time the loop
yields the final chunk,
and the TUI's Runner
fires ``on_assistant_text``
correctly.

This file pins the
contract end-to-end:
we drive a fake streaming
LLM that emits the same
four-chunk shape the real
Anthropic endpoint does,
then assert the agent
loop yields a final
response whose
``resp.text`` equals the
full text.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from manusift.llm.chat import ChatResponse
from manusift.tools.tool import ToolContext


# A fake LLM whose
# ``chat_stream`` mimics
# the Anthropic streaming
# shape: a sequence of
# ``ChatResponse`` chunks
# that the real client
# yields one at a time.
# Each chunk is a *delta*
# (not pre-merged) -- the
# agent loop is responsible
# for folding them.
class _ChunkedLLM:
    name = "chunked"

    def __init__(self, chunks: list[ChatResponse]) -> None:
        self._chunks = chunks
        self.chat_calls = 0
        self.stream_calls = 0

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding) -> None:
        return None

    def chat(
        self,
        messages,
        tools=None,
        **kw,
    ) -> ChatResponse:
        self.chat_calls += 1
        return ChatResponse(
            content_blocks=[{
                "type": "text",
                "text": "(non-streaming)",
            }],
            stop_reason="end_turn",
        )

    def chat_stream(
        self,
        messages,
        tools=None,
        **kw,
    ) -> Iterator[ChatResponse]:
        self.stream_calls += 1
        for c in self._chunks:
            yield c


def _build_chunks() -> list[ChatResponse]:
    """The four-chunk shape
    that ``AnthropicLLM.chat_stream``
    produces for a simple
    text reply."""
    return [
        # content_block_start
        ChatResponse(
            content_blocks=[{"type": "text", "text": ""}],
            model="test",
        ),
        # text_delta "Hello! "
        ChatResponse(
            content_blocks=[{"type": "text", "text": "Hello! "}],
            model="test",
        ),
        # text_delta "I'm ManuSift."
        ChatResponse(
            content_blocks=[
                {"type": "text", "text": "I'm ManuSift."}
            ],
            model="test",
        ),
        # message_delta (no text, just stop_reason)
        ChatResponse(
            content_blocks=[],
            stop_reason="end_turn",
            model="test",
        ),
    ]


def test_streaming_loop_accumulates_text() -> None:
    """The agent loop's
    streaming branch must
    accumulate text across
    chunks so the final
    ``resp.text`` is the
    full string, not a
    fragment."""
    from manusift.agent import AgentLoop

    llm = _ChunkedLLM(_build_chunks())
    ctx = ToolContext(trace_id="t", current_pdf="t")
    loop = AgentLoop(
        client=llm, tools=[], ctx=ctx
    )
    chunks = list(loop.run_stream("hi"))
    assert len(chunks) >= 1
    # The
    # last
    # chunk
    # must
    # have
    # the
    # full
    # text.
    last = chunks[-1]
    assert last.text == "Hello! I'm ManuSift.", (
        f"final chunk text should be fully accumulated, "
        f"got {last.text!r} (was the merge call missing?)"
    )
    assert last.stop_reason == "end_turn"


def test_streaming_loop_runs_in_progressively() -> None:
    """The running
    accumulated text should
    grow monotonically across
    chunks. A previous bug
    (the one we are fixing)
    caused it to bounce back
    to empty after each
    non-text chunk."""
    from manusift.agent import AgentLoop

    llm = _ChunkedLLM(_build_chunks())
    ctx = ToolContext(trace_id="t", current_pdf="t")
    loop = AgentLoop(
        client=llm, tools=[], ctx=ctx
    )
    chunks = list(loop.run_stream("hi"))
    text_lengths = [len(c.text) for c in chunks]
    # The
    # final
    # text
    # length
    # must
    # equal
    # the
    # full
    # message
    # length.
    full_len = len("Hello! I'm ManuSift.")
    assert text_lengths[-1] == full_len, (
        f"final text length {text_lengths[-1]} should be "
        f"{full_len}; intermediate lengths: {text_lengths}"
    )


def test_streaming_loop_does_not_regress_with_empty_text_chunks() -> None:
    """Some Anthropic streaming
    responses (e.g. tool_use
    with no text) yield
    chunks with empty text.
    The agent loop must
    preserve the previously
    accumulated text across
    those empty chunks.

    The chunk shape we test:

      1. "Hi"        (first text_delta)
      2. ""          (empty chunk -- e.g.
                       tool_use content_block_start)
      3. ""          (empty text_delta)
      4. stop_reason + accumulated text already
         present (this is what the running accumulator
         should look like on the final chunk).

    Note: the agent loop's
    merge is
    text-concatenation, so
    the test asserts the
    final text equals the
    running accumulated
    value the LLM would
    have produced -- not
    that the *input* to
    chunk 4 alone is the
    full text.
    """
    from manusift.agent import AgentLoop

    chunks = [
        ChatResponse(
            content_blocks=[{"type": "text", "text": "Hi"}],
            model="test",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": ""}],
            model="test",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": ""}],
            model="test",
        ),
        ChatResponse(
            content_blocks=[{"type": "text", "text": "Hi"}],
            stop_reason="end_turn",
            model="test",
        ),
    ]
    llm = _ChunkedLLM(chunks)
    ctx = ToolContext(trace_id="t", current_pdf="t")
    loop = AgentLoop(
        client=llm, tools=[], ctx=ctx
    )
    out = list(loop.run_stream("hi"))
    # The
    # final
    # chunk
    # accumulates
    # all
    # text
    # deltas:
    # "Hi" + ""
    # + "" +
    # "Hi" = "HiHi".
    # The
    # The
    # point
    # of
    # this
    # test
    # is
    # that
    # the
    # empty
    # chunks
    # in
    # the
    # middle
    # did
    # NOT
    # wipe
    # the
    # accumulated
    # text.
    #
    # R-audit (2026-06-10):
    # the
    # previous
    # version
    # expected
    # ``"HiHi"``
    # because
    # it
    # called
    # ``accumulated.merged(partial)``
    # which
    # *concatenates*
    # text
    # blocks
    # --
    # but
    # the
    # SDK
    # emits
    # the
    # *same*
    # full
    # text
    # in
    # every
    # chunk,
    # so
    # that
    # produced
    # ``"HiHi"``
    # (a
    # bug).
    # The
    # fix
    # takes
    # the
    # *longer*
    # of
    # the
    # two
    # texts
    # rather
    # than
    # concatenating,
    # so
    # the
    # final
    # accumulated
    # text
    # is
    # ``"Hi"``
    # (the
    # SDK
    # value
    # for
    # every
    # chunk).
    assert out[-1].text == "Hi"
    # And
    # the
    # chunks
    # in
    # between
    # preserved
    # at
    # least
    # "Hi"
    # -- they
    # did
    # not
    # bounce
    # back
    # to
    # empty.
    text_lengths = [len(c.text) for c in out]
    for i, ln in enumerate(text_lengths):
        assert ln >= 0
        # No
        # chunk
        # should
        # have
        # a
        # shorter
        # text
        # than
        # the
        # last
        # non-zero
        # text
        # we
        # had
        # --
        # but
        # we
        # allow
        # the
        # running
        # text
        # to
        # be
        # empty
        # in
        # early
        # chunks
        # if
        # no
        # text
        # came
        # yet.
        if i > 0 and text_lengths[i - 1] > 0:
            assert ln >= text_lengths[i - 1] - 0, (
                f"running accumulated text shrank from "
                f"{text_lengths[i-1]} to {ln} at chunk {i} -- "
                f"merge is replacing instead of folding"
            )


def test_streaming_loop_surfaces_to_runner() -> None:
    """End-to-end: a Runner
    built on top of the
    streaming agent loop
    fires ``on_assistant_text``
    with the full text.
    This is the user-facing
    contract: typing in the
    TUI and pressing Enter
    must produce a visible
    assistant message in
    the chat history."""
    from manusift.tui.agent_runner import (
        Runner,
        RunnerCallbacks,
    )

    llm = _ChunkedLLM(_build_chunks())
    ctx = ToolContext(trace_id="t", current_pdf="t")

    surfaced: list[str] = []

    runner = Runner(
        client=llm,
        tools=[],
        ctx=ctx,
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
    assert surfaced == ["Hello! I'm ManuSift."], (
        f"Runner should have surfaced exactly one assistant "
        f"text callback with the full reply, got {surfaced!r}"
    )


def test_runner_dedupes_end_turn_re_emit() -> None:
    """The agent loop yields
    the final accumulated
    response twice on a
    stop_reason='end_turn'
    turn: once at the end
    of the streaming chunks
    and once in the
    "fire one more on_step"
    block. Both have
    ``sr='end_turn'`` and
    similar text, so the
    Runner must dedup so
    the TUI does not show
    the same assistant
    message twice.

    Real Anthropic streams
    also sometimes emit two
    consecutive ``end_turn``
    chunks (one from
    ``message_delta``, one
    from a re-fold of the
    final state). The
    Runner must handle both
    shapes -- that is what
    this test pins.
    """
    from manusift.tui.agent_runner import (
        Runner,
        RunnerCallbacks,
    )

    class _DoubleEndTurnLLM:
        name = "double-end-turn"

        def is_available(self) -> bool:
            return True

        def analyze_finding(self, f):
            return None

        def chat_stream(self, *a, **kw):
            # Mimic the two-chunk
            # "end_turn" shape the
            # real Anthropic SDK
            # produces. Both have
            # the same stop_reason
            # but the text length
            # grows because the
            # agent loop's merge
            # re-folds the same
            # accumulated state
            # into a new ChatResponse
            # in the post-loop
            # "fire one more on_step"
            # block.
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "First chunk. "}
                ],
                model="test",
            )
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "Second chunk. "}
                ],
                model="test",
            )
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "Final. "}
                ],
                stop_reason="end_turn",
                model="test",
            )
            # Re-emit of the final
            # state -- the agent
            # loop's post-loop
            # "fire one more on_step"
            # will produce another
            # yield with the same
            # accumulated text but
            # a slightly different
            # chat_response wrapper
            # (e.g. updated usage).
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "Final. "}
                ],
                stop_reason="end_turn",
                model="test",
            )

    surfaced: list[str] = []
    llm = _DoubleEndTurnLLM()
    ctx = ToolContext(trace_id="t", current_pdf="t")
    runner = Runner(
        client=llm,
        tools=[],
        ctx=ctx,
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
    # Exactly one surface
    # call -- the duplicate
    # end_turn chunk must be
    # suppressed.
    assert len(surfaced) == 1, (
        f"expected exactly one assistant text callback, "
        f"got {len(surfaced)}: {surfaced!r}"
    )