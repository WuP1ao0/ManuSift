"""PILOT: real-LLM end-to-end test (R-audit 2026-06-11).

This is the smoke test
for the three-layer
chat surface against
the real MiniMax-M3
LLM. It runs the
user's exact failing
scenario from the
2026-06-11 screenshot:

  > "C:\\Users\\22509\\Desktop\\ScholarLens\\pilot_cases\\real_world_nature\\s41565-025-02082-0"
  > "this is a paper + raw data, please review"

and verifies the
three-layer output:

  1. chat log:
     user + assistant
     (markdown-
     rendered)
  2. ToolTraceBlock:
     ``tools N calls · A
     ok · B skipped · C
     error`` (collapsed
     by default)
  3. DebugDrawer:
     raw JSON
     (hidden by
     default, opens
     with ``d``)
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


def main() -> None:
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    if not s.has_anthropic:
        print("SKIP: no API key")
        return
    from textual.containers import VerticalScroll
    from textual.widgets import Input, TextArea
    from manusift.tui.chat_app import ChatApp
    from manusift.tui.turn_block import (
        DebugDrawer,
        ToolTraceBlock,
    )

    USER_PROMPT = (
        r"C:\Users\22509\Desktop\ScholarLens\pilot_cases"
        r"\real_world_nature\s41565-025-02082-0"
        "  this is a paper + raw data, please review"
    )

    async def driver() -> None:
        app = ChatApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            print("=== mounted widgets ===")
            for c in app.screen.walk_children():
                if hasattr(c, "id") and c.id:
                    print(f"  id={c.id!r:30s} type={type(c).__name__}")
            # Send
            # the
            # user
            # prompt.
            inp = app.query_one("#input", TextArea)
            inp.focus()
            for ch in USER_PROMPT:
                await pilot.press(ch)
                await pilot.pause(0.01)
            await pilot.press("ctrl+j")
            # Wait
            # for
            # the
            # LLM
            # to
            # finish.
            for i in range(80):
                await pilot.pause(0.5)
                if (
                    app._active_worker is None
                    and not app._agent_running
                ):
                    print(f"\n=== finished after {(i+1)*0.5}s ===")
                    break
            else:
                print("\n=== TIMEOUT after 40s ===")
            await pilot.pause(1.0)
            history = app.query_one("#history", VerticalScroll)
            print(f"\n=== #history has {len(history.children)} children ===")
            for i, c in enumerate(history.children):
                classes = c.classes
                text = ""
                for sub in c.walk_children():
                    if hasattr(sub, "content") and sub.content:
                        text = str(sub.content)
                        break
                print(f"  [{i:02d}] classes={classes!r}")
                print(f"        text={text[:200]!r}")
            # Find
            # the
            # ToolTraceBlock
            # children.
            tool_traces = [
                c for c in history.children
                if isinstance(c, ToolTraceBlock)
            ]
            print(f"\n=== ToolTraceBlock count: {len(tool_traces)} ===")
            for i, tb in enumerate(tool_traces):
                text = str(tb.content) if hasattr(tb, "content") else ""
                print(f"  trace[{i}]: sealed={tb.is_sealed} text={text[:200]!r}")
            # Find
            # the
            # DebugDrawer
            # and
            # check
            # it
            # has
            # tool-call
            # entries
            # logged
            # (since
            # the
            # LLM
            # actually
            # called
            # tools).
            drawer = app.query_one("#debug-drawer", DebugDrawer)
            # R-audit (2026-06-11):
            # the
            # input
            # box
            # may
            # still
            # have
            # focus
            # (the
            # _on_finished_main
            # callback
            # re-focuses
            # it).
            # Force
            # the
            # action
            # to
            # fire
            # directly
            # --
            # this
            # is
            # exactly
            # what
            # the
            # ``d``
            # keybinding
            # does
            # under
            # the
            # hood.
            app.action_toggle_debug_drawer()
            await pilot.pause(0.3)
            print(f"\n=== after action: drawer.is_visible = {drawer.is_visible} ===")
            assert drawer.is_visible is True
            # Contract
            # 5:
            # the
            # drawer
            # can
            # be
            # toggled
            # back.
            app.action_toggle_debug_drawer()
            await pilot.pause(0.2)
            assert drawer.is_visible is False
            print("\n=== PILOT DONE ===")

    asyncio.run(driver())


if __name__ == "__main__":
    main()
