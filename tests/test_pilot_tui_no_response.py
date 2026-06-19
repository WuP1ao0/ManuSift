"""PILOT (not a pytest test): drive the TUI through pilot_test to
see why 'no response' on a chat-style message.

This is the script that
found the bug. We keep
it as a pilot because the
assertion ("the LLM IS
responding but the TUI
drops the text") is best
debugged by reading the
output, not by an
assertEquals.

Run::

  .venv/Scripts/python.exe
    tests/test_pilot_tui_no_response.py
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")
os.environ["MANUSIFT_WORKSPACE_DIR"] = (
    r"C:\Users\22509\Desktop\ManuSift1\data\pilot_jobs"
)


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    print("has_anthropic:", s.has_anthropic)

    from manusift.tui.chat_app import ChatApp
    from textual.widgets import Input, TextArea, Static

    app = ChatApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # Focus
        # the
        # input.
        for _ in range(5):
            await pilot.press("tab")
            await pilot.pause()
            if app.focused and getattr(
                app.focused, "id", ""
            ) == "input":
                break

        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause(0.5)
        await pilot.press("ctrl+j")
        # Wait
        # 10s
        # for
        # the
        # LLM
        # to
        # respond.
        for _ in range(100):
            await pilot.pause(0.1)

        # Dump
        # history.
        history = app.query_one("#history")
        print(f"=== #history Static children: "
              f"{len(history.query(Static))} ===")
        for i, w in enumerate(history.query(Static)):
            try:
                # Try
                # the
                # standard
                # Static.renderable
                # attribute
                # first.
                try:
                    rp = w.renderable
                except AttributeError:
                    rp = None
                    for attr in (
                        "text", "_text", "content",
                        "value", "render_str",
                    ):
                        if hasattr(w, attr):
                            rp = getattr(w, attr)
                            break
                plain = (
                    rp.plain
                    if hasattr(rp, "plain")
                    else str(rp)
                )
                print(f"  [{i:02d}] {plain!r:.300}")
            except Exception as exc:
                print(f"  [{i:02d}] err={exc}")
        print()
        print(f"  _plan_mode_flag: {app._plan_mode_flag}")
        print(f"  _agent_running: {app._agent_running}")
        # Count
        # how
        # many
        # assistant
        # messages
        # were
        # appended.
        try:
            asst_count = sum(
                1 for w in history.query(Static)
                if "«" in str(
                    getattr(w, "_text", "")
                    or getattr(w, "renderable", "")
                )
            )
            print(f"  assistant messages in #history: {asst_count}")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())