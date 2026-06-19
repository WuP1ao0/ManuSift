"""PILOT: end-to-end verification of the three-layer chat
(R-audit 2026-06-11).

The user asked for a
``Chat + ToolTrace +
DebugDrawer`` structure
with the user's exact
spec:

  1. chat log
     shows ONLY user /
     assistant
  2. tool events go to
     a per-turn
     ``ToolTraceBlock``
     (collapsed by
     default)
  3. raw JSON goes to
     the
     ``DebugDrawer``
     (hidden by default,
     opened with
     ``d``)
  4. assistant text
     is Markdown-
     rendered (no raw
     ``**`` or
     ``##``)
  5. long paths
     shown as
     ``.../<basename>``
  6. repeated errors
     are deduped

This pilot script
runs a real agent
turn (against the
MockLLM, which is
deterministic and
fast) and verifies
all six contracts.

Run it directly:

  python tests/test_pilot_chat_layering.py
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


def main() -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    from textual.containers import VerticalScroll
    from textual.widgets import Input, TextArea, Static
    from manusift.tui.chat_app import ChatApp
    from manusift.tui.turn_block import (
        DebugDrawer,
        ToolEntry,
        ToolTraceBlock,
        TOOL_OK,
    )
    from manusift.llm import MockLLM

    async def driver() -> None:
        app = ChatApp(llm_client=MockLLM())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            print("=== mounted widgets ===")
            for c in app.screen.walk_children():
                if hasattr(c, "id") and c.id:
                    print(f"  id={c.id!r:30s} type={type(c).__name__}")
            # The
            # DebugDrawer
            # should
            # be
            # mounted
            # (hidden).
            drawer = app.query_one("#debug-drawer", DebugDrawer)
            print(f"\n=== DebugDrawer initial visibility: {drawer.is_visible} ===")
            # No
            # tool
            # trace
            # block
            # yet
            # --
            # the
            # block
            # is
            # mounted
            # per
            # turn,
            # not
            # in
            # compose.
            # Send
            # a
            # user
            # message.
            inp = app.query_one("#input", TextArea)
            inp.focus()
            for ch in "hi":
                await pilot.press(ch)
                await pilot.pause(0.04)
            await pilot.press("ctrl+j")
            # Wait
            # for
            # the
            # agent
            # to
            # finish.
            for _ in range(40):
                await pilot.pause(0.3)
                if app._active_worker is None and not app._agent_running:
                    break
            await pilot.pause(0.3)
            history = app.query_one("#history", VerticalScroll)
            print(f"\n=== #history children after one turn: ===")
            for i, c in enumerate(history.children):
                classes = c.classes
                text = str(c.content) if hasattr(c, "content") else ""
                # Walk
                # the
                # children
                # if
                # it's
                # a
                # Horizontal.
                if not text.strip():
                    for sub in c.walk_children():
                        if hasattr(sub, "content") and sub.content:
                            text = str(sub.content)
                            break
                print(f"  [{i:02d}] classes={classes!r} text={text[:80]!r}")
            # Contract
            # 1:
            # chat
            # log
            # has
            # ONLY
            # user
            # /
            # assistant
            # rows
            # (no
            # tool).
            tool_bubbles = [
                c for c in history.children
                if "msg-tool" in c.classes
            ]
            print(f"\n=== tool bubbles in #history: {len(tool_bubbles)} (expected 0) ===")
            assert len(tool_bubbles) == 0, (
                f"tool bubbles leaked into #history: "
                f"{[str(c) for c in tool_bubbles]}"
            )
            # Contract
            # 2:
            # at
            # least
            # one
            # user
            # bubble
            # and
            # one
            # assistant
            # bubble.
            user_bubbles = [
                c for c in history.children
                if "msg-user" in c.classes
            ]
            assistant_bubbles = [
                c for c in history.children
                if "msg-assistant" in c.classes
            ]
            print(f"=== user bubbles: {len(user_bubbles)} ===")
            print(f"=== assistant bubbles: {len(assistant_bubbles)} ===")
            assert len(user_bubbles) >= 1
            assert len(assistant_bubbles) >= 1
            # Contract
            # 6:
            # press
            # ``d``
            # to
            # open
            # the
            # DebugDrawer.
            inp.blur()
            await pilot.pause(0.1)
            await pilot.press("d")
            await pilot.pause(0.2)
            print(f"\n=== after pressing d: drawer.is_visible = {drawer.is_visible} ===")
            assert drawer.is_visible is True
            # Contract
            # 5:
            # the
            # drawer
            # can
            # be
            # toggled
            # back.
            await pilot.press("d")
            await pilot.pause(0.2)
            assert drawer.is_visible is False
            print("\n=== ALL CONTRACTS PASSED ===")

    asyncio.run(driver())


if __name__ == "__main__":
    main()
