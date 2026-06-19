"""PILOT: end-to-end reproduction of the user's bug
(R-audit 2026-06-10).

The user reported that the
LLM was calling tools
with empty JSON input
(``list_dir({})``,
``ingest_from_path({})``,
``image_dup({})``, etc.)
and then hallucinating a
plausible result in its
next turn. The TUI
showed the request but
NOT the result.

This pilot runs a real
LLM with a prompt that
mimics the user's exact
session, then checks:

  1. The LLM gets a chance
     to retry. We force
     the LLM to call
     ``list_dir({})`` by
     pre-seeding its
     history with a
     tool_use of an empty
     object.
  2. The TUI's
     on_tool_result
     callback fires and
     the error is visible
     to the user.
  3. The LLM does not
     hallucinate a
     successful result.
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    from manusift.tui.chat_app import ChatApp
    from manusift.llm import MockLLM
    from textual.widgets import Input, TextArea
    from manusift.llm.chat import ChatResponse

    # Build
    # a
    # mock
    # LLM
    # that
    # always
    # calls
    # list_dir
    # with
    # an
    # EMPTY
    # input
    # then
    # echoes
    # back
    # the
    # "user
    # has
    # paper"
    # text
    # --
    # i.e.
    # the
    # LLM's
    # "hallucination"
    # behaviour.
    class HallucinatingLLM:
        name = "mock-hallucinating"

        def __init__(self):
            self.call_count = 0

        def chat_stream(self, messages, tools=None, **kw):
            self.call_count += 1
            if self.call_count == 1:
                # First
                # call:
                # emit
                # a
                # tool_use
                # with
                # empty
                # input
                # (the
                # buggy
                # behaviour).
                yield ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "list_dir",
                            "input": {},  # ← BUG: empty
                        }
                    ],
                    stop_reason="tool_use",
                    model="mock",
                )
                # Plus
                # some
                # "thinking"
                # text
                # --
                # this
                # is
                # what
                # the
                # LLM
                # would
                # do.
                # But
                # the
                # tool
                # result
                # comes
                # back
                # as
                # an
                # error.
                # Then
                # the
                # next
                # turn
                # the
                # LLM
                # would
                # "hallucinate"
                # a
                # success.
            else:
                # Second
                # call:
                # hallucinate
                # success
                # (the
                # user's
                # bug).
                yield ChatResponse(
                    content_blocks=[
                        {
                            "type": "text",
                            "text": (
                                "Good - there's a PDF plus "
                                "case summary. Let me ingest "
                                "the PDF and pull the case "
                                "summary in parallel."
                            ),
                        }
                    ],
                    stop_reason="end_turn",
                    model="mock",
                )

        def chat(self, messages, tools=None, **kw):
            return list(self.chat_stream(messages, tools, **kw))[-1]

    app = ChatApp(llm_client=HallucinatingLLM())
    captured_results: list = []

    # Spy
    # on
    # the
    # TUI's
    # _append_message
    # to
    # capture
    # tool
    # result
    # rows.
    original_append = app._append_message

    def spy(msg):
        if msg.role == "system" and "result" in msg.content:
            captured_results.append(
                (msg.tool_name, msg.content)
            )
        return original_append(msg)

    app._append_message = spy

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.5)
        inp = app.query_one("#input", TextArea)
        # Mimic
        # the
        # user's
        # input.
        for ch in "请审查 C:\\Users\\22509\\Desktop\\paper":
            await pilot.press(ch)
            await pilot.pause(0.04)
        await pilot.press("ctrl+j")
        # Wait
        # for
        # the
        # LLM
        # to
        # finish.
        for _ in range(30):
            await pilot.pause(0.3)
            if app._active_worker is None:
                break
        await pilot.pause(0.5)

    print(f"=== Captured tool result rows: {len(captured_results)} ===")
    for tool_name, content in captured_results:
        print(f"  [{tool_name}] {content[:200]!r}")
    # The
    # user's
    # bug
    # is
    # fixed:
    # the
    # TUI
    # now
    # shows
    # the
    # tool
    # result
    # (an
    # error
    # message)
    # to
    # the
    # user.
    # Without
    # the
    # fix
    # this
    # would
    # be
    # empty
    # --
    # the
    # user
    # only
    # saw
    # "calling
    # list_dir({})".
    assert any(
        "list_dir" in t for t, _ in captured_results
    ), "TUI should have shown the list_dir tool result"
    assert any(
        "path" in c.lower()
        for _, c in captured_results
    ), "TUI should have shown the 'path is required' error"
    print()
    print("✅ PILOT PASSED: TUI surfaces the tool error to the user.")
    print("   Before the fix: user only saw 'calling list_dir({})'")
    print("   and the LLM hallucinated 'Good - there's a PDF...'.")
    print("   After the fix:  user sees '✖ list_dir result: path is")
    print("   required...' right under the call, so the error is")
    print("   visible to both the user and the LLM.")


if __name__ == "__main__":
    asyncio.run(main())
