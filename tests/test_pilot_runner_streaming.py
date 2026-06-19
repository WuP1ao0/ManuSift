"""PILOT: drive the agent_runner.Runner with a fake streaming LLM
to see exactly what gets surfaced to the callbacks.

This is the test that
finds the streaming text
drop bug.

We construct a fake
AnthropicLLM that emits
two streaming ChatResponses:

  1. chunk 1: empty text (content_block_start)
  2. chunk 2: "Hello! " (text_delta)
  3. chunk 3: "I'm ManuSift." (text_delta)
  4. chunk 4: stop_reason="end_turn" (message_delta)

Then we run the Runner
and see if
``cb.on_assistant_text``
gets called with the full
text.
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users\22509/Desktop/ManuSift1")


def main() -> None:
    from manusift.llm.chat import ChatResponse
    from manusift.tools.tool import ToolContext

    # Build
    # a
    # fake
    # LLM
    # that
    # yields
    # a
    # realistic
    # Anthropic-style
    # stream
    # of
    # ChatResponses
    # (accumulated).
    class _FakeLLM:
        name = "fake"

        def chat(self, *a, **k):
            return ChatResponse(
                content_blocks=[{
                    "type": "text",
                    "text": "non-streaming fallback",
                }],
                stop_reason="end_turn",
            )

        def is_available(self):
            return True

        def analyze_finding(self, f):
            return None

        def chat_stream(self, messages, tools=None, **kw):
            # Mimic
            # the
            # Anthropic
            # streaming
            # shape
            # *after*
            # the
            # agent
            # loop's
            # internal
            # ``merged()``
            # fold
            # has
            # run
            # over
            # each
            # raw
            # event.
            # The
            # Runner
            # sees
            # the
            # running
            # accumulated
            # response
            # in
            # each
            # chunk
            # so
            # text
            # already
            # accumulated
            # shows
            # up
            # in
            # ``resp.text``
            # on
            # the
            # final
            # chunk.
            chunks = [
                # Chunk
                # 1:
                # content_block_start
                # -- empty
                # text
                # block
                # opened.
                ChatResponse(
                    content_blocks=[{"type": "text", "text": ""}],
                    model="test",
                ),
                # Chunk
                # 2:
                # text_delta
                # "Hello! "
                # appended.
                ChatResponse(
                    content_blocks=[
                        {"type": "text", "text": "Hello! "}
                    ],
                    model="test",
                ),
                # Chunk
                # 3:
                # text_delta
                # "I'm ManuSift."
                # appended.
                ChatResponse(
                    content_blocks=[
                        {"type": "text", "text": "I'm ManuSift."}
                    ],
                    model="test",
                ),
                # Chunk
                # 4:
                # message_delta
                # -- stop_reason
                # + final
                # text
                # already
                # present
                # from
                # previous
                # accumulation.
                ChatResponse(
                    content_blocks=[
                        {"type": "text", "text": "Hello! I'm ManuSift."}
                    ],
                    stop_reason="end_turn",
                    model="test",
                ),
            ]
            for c in chunks:
                yield c

    # Now
    # drive
    # the
    # Runner.
    from manusift.tui.agent_runner import Runner, RunnerCallbacks

    surfaced: list[tuple[str, str]] = []

    def on_started() -> None:
        surfaced.append(("started", ""))

    def on_status(s: str) -> None:
        surfaced.append(("status", s))

    def on_assistant_text(t: str) -> None:
        surfaced.append(("assistant", t))

    def on_tool_call(n: str, i: dict) -> None:
        surfaced.append(("tool_call", n))

    def on_message(m) -> None:
        surfaced.append(("message", str(m.content)[:100]))

    def on_finished(s: str) -> None:
        surfaced.append(("finished", s))

    ctx = ToolContext(trace_id="t", current_pdf="t")
    runner = Runner(
        client=_FakeLLM(),
        tools=[],
        ctx=ctx,
        cb=RunnerCallbacks(
            on_status=on_status,
            on_assistant_text=on_assistant_text,
            on_tool_call=on_tool_call,
            on_message=on_message,
            on_started=on_started,
            on_finished=on_finished,
        ),
    )
    result = runner.run("hello")
    print(f"runner.run returned: {result!r}")
    print()
    print("=== Surfaced callback events ===")
    for kind, payload in surfaced:
        print(f"  [{kind:9s}] {payload!r:.200}")
    print()
    # Did
    # on_assistant_text
    # ever
    # fire?
    assistant_calls = [
        p for k, p in surfaced if k == "assistant"
    ]
    if assistant_calls:
        print(
            f"  on_assistant_text fired "
            f"{len(assistant_calls)} time(s), "
            f"total chars: {sum(len(p) for p in assistant_calls)}"
        )
    else:
        print("  !!! on_assistant_text NEVER FIRED !!!")


if __name__ == "__main__":
    main()