"""PILOT: force MockLLM in the TUI to see what actually happens when
the user types "你好" while the TUI thinks it has a real LLM.

This is the diagnostic
script for the user's
report: "I see the
MockLLM warning, but
typing 你好 gives no
response."

The TUI may have a code
path that silently
swallows a streaming
yield that the user
never sees rendered
into the chat history.
"""
from __future__ import annotations

import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")

import asyncio
import sys

sys.path.insert(0, r"C:/Users/22509/Desktop/ManuSift1")


async def main() -> None:
    # Force
    # the
    # env
    # to
    # look
    # like
    # "no
    # key
    # configured".
    for k in (
        "MANUSIFT_ANTHROPIC_API_KEY",
        "MANUSIFT_DEFAULT_LLM_PROVIDER",
    ):
        os.environ.pop(k, None)

    from dotenv import load_dotenv
    # Skip
    # .env
    # load
    # so
    # the
    # user
    # scenario
    # (no
    # key
    # in
    # .env)
    # is
    # reproduced.
    # But
    # the
    # .env
    # file
    # is
    # already
    # cached
    # by
    # pydantic.
    # Just
    # use
    # a
    # fresh
    # Settings
    # and
    # manually
    # clear
    # it.
    load_dotenv()  # load .env first

    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    # Force
    # the
    # key
    # to
    # None
    # to
    # simulate
    # "no
    # key".
    if s.anthropic_api_key is not None:
        object.__setattr__(s, "anthropic_api_key", None)
    print(
        f"DEBUG: has_anthropic={s.has_anthropic}, "
        f"key={s.anthropic_api_key!r}"
    )

    from manusift.llm import client as llm_client_mod
    llm_client_mod._client_singleton = None
    from manusift.llm.client import get_llm_client, MockLLM
    test_client = get_llm_client()
    print(f"DEBUG: client type = {type(test_client).__name__}")
    if not isinstance(test_client, MockLLM):
        print(
            "ERROR: still has key? .env is being read by "
            "Pydantic; cannot force MockLLM"
        )
        # Fall
        # back
        # to
        # direct
        # MockLLM
        # construction.
        test_client = MockLLM()

    from manusift.tui.chat_app import ChatApp
    app = ChatApp(llm_client=test_client)

    # Patch
    # the
    # _append_message
    # to
    # see
    # what
    # messages
    # are
    # appended.
    appended: list[tuple[str, str]] = []

    def fake_append(self, msg) -> None:
        appended.append((msg.role, str(msg.content)))
        print(f"  [appended {msg.role!r}] {str(msg.content)[:80]!r}")

    from manusift.tui import chat_app as ca_mod
    ca_mod.ChatApp._append_message = fake_append

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.5)
        from textual.widgets import Input, TextArea
        try:
            inp = app.query_one("#input", TextArea)
            inp.focus()
            print(f"  input focused: {inp.has_focus}")
        except Exception as exc:
            print(f"  focus failed: {exc}")
        await pilot.pause(0.2)
        # Type
        # one
        # char
        # at
        # a
        # time
        # + press
        # enter.
        print()
        print("  typing 你好 via pilot.press + enter")
        for ch in "你好":
            await pilot.press(ch)
            await pilot.pause(0.1)
        await pilot.press("ctrl+j")
        for i in range(20):
            await pilot.pause(0.5)
        print()
        print(f"=== after waiting 10s, {len(appended)} messages appended ===")
        for role, content in appended:
            print(f"  [{role}] {content[:200]!r}")


if __name__ == "__main__":
    asyncio.run(main())
