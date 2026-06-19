"""PILOT: verify the Claude-Code-style intent-routing prompt
(2026-06-10) handles casual chat and academic requests in
the same conversation, switching modes seamlessly.

The previous system
prompt forced the LLM
into a strict
"ask for trace_id"
flow. The new prompt
(inspired by Claude
Code) treats the
in-session conversation
as a free-form
chat: a user can say
"hello", then "what
is GRIM?", then
"check trace_id
e6f244000eac for image
duplicates" -- all in
the same session. The
LLM is expected to
infer intent per turn
and call the right tool
(or no tool) for each
turn.

We use a stub LLM that
records what tools the
agent loop surfaced.
We also use a stub
detector that returns
empty results so the
loop exits cleanly.

This is a pilot (not a
pytest test) because
the real LLM is not
available in CI. Run
with:

    python tests/test_pilot_intent_routing.py
"""
from __future__ import annotations

import asyncio
import os

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    if not s.has_anthropic:
        print("SKIP: no API key configured")
        return

    from manusift.llm.client import AnthropicLLM
    from manusift.tools import iter_registered_tools
    from manusift.tools.tool import ToolContext
    from manusift.agent import AgentLoop
    from manusift.tui.agent_runner import (
        Runner,
        RunnerCallbacks,
    )

    tools = list(iter_registered_tools())
    llm = AnthropicLLM(s)
    ctx = ToolContext(trace_id="t", current_pdf="t")
    loop = AgentLoop(client=llm, tools=tools, ctx=ctx)

    sp = loop._system_prompt
    print("=== system prompt (first 500 chars) ===")
    print(sp[:500])
    print()
    print("=== system prompt last 500 chars ===")
    print(sp[-500:])
    print()
    print("=== Length: ", len(sp), "chars ===")

    # Smoke-test: drive the agent loop with a series
    # of mixed messages and confirm the LLM only
    # calls tools on the academic messages.
    surfaced_tool_calls: list[tuple[str, str]] = []

    def cb_on_tool_call(name: str, inp: dict) -> None:
        surfaced_tool_calls.append((name, str(inp)))

    runner = Runner(
        client=llm,
        tools=tools,
        ctx=ctx,
        cb=RunnerCallbacks(
            on_status=lambda msg: None,
            on_assistant_text=lambda t: print(f"[assistant] {t[:300]}"),
            on_tool_call=cb_on_tool_call,
            on_message=lambda m: None,
            on_started=lambda: None,
            on_finished=lambda s: print(f"[done] {s}"),
        ),
    )

    print("\n=== Turn 1: casual greeting ===")
    runner.run("hello, how are you?")
    print(f"  tools called in turn 1: {len(surfaced_tool_calls)}")
    print()

    print("=== Turn 2: question about ManuSift ===")
    runner.run("what can you do?")
    print(f"  tools called in turn 2: {len(surfaced_tool_calls)}")
    print()

    print("=== Turn 3: paper analysis ===")
    runner.run("check trace_id e6f244000eac for image duplicates")
    print(f"  tools called in turn 3: {len(surfaced_tool_calls)}")
    print()

    print("=== Turn 4: casual follow-up ===")
    runner.run("thanks! is there anything I should worry about?")
    print(f"  tools called in turn 4: {len(surfaced_tool_calls)}")
    print()

    print("=== Total tool calls ===")
    for name, inp in surfaced_tool_calls:
        print(f"  {name}({inp[:60]!r})")


if __name__ == "__main__":
    asyncio.run(main())
