"""E2E: simulate the LLM calling render_report 99 times -- prove
the dedup layer actually rejects them.

The previous pilot called
``render_report`` 99
times. We cannot easily
reproduce the LLM
behaviour reliably, but
we CAN drive the
``AgentLoop`` directly
with a fake
``ChatResponse`` that
emits 99 identical
``render_report`` tool
calls. This proves the
dedup code is wired
correctly end-to-end.

Run with::

  .venv/Scripts/python.exe
    tests/test_pilot_dedup_loop.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.chdir(str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()

    from manusift.tools import iter_registered_tools
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext
    from manusift.llm.chat import ChatResponse

    tools = list(iter_registered_tools())

    # Build
    # a
    # scripted
    # LLM
    # that
    # pretends
    # to
    # be
    # looping:
    # every
    # turn
    # it
    # asks
    # for
    # ``render_report``
    # with
    # the
    # same
    # arguments.
    class LoopingLLM:
        name = "looping"
        def __init__(self) -> None:
            self.turns = 0
        def chat(self, *args, **kwargs):
            self.turns += 1
            return ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": f"id{self.turns}",
                    "name": "render_report",
                    "input": {"markdown": "hello world"},
                }],
                stop_reason="tool_use",
                usage={},
                model="test",
            )
        def chat_stream(self, messages, tools, **kw):
            self.turns += 1
            yield ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": f"id{self.turns}",
                    "name": "render_report",
                    "input": {"markdown": "hello world"},
                }],
                stop_reason="tool_use",
                usage={},
                model="test",
            )
        def is_available(self) -> bool:
            return True
        def analyze_finding(self, f): return None

    ctx = ToolContext(trace_id="t", current_pdf="t")
    loop = AgentLoop(
        client=LoopingLLM(),
        tools=tools,
        ctx=ctx,
    )
    print(f"=== Tools: {len(tools)} ===")
    print(f"=== Starting loop with a LoopingLLM ===")
    print(f"  expected: max_steps=8 turns, but every turn")
    print(f"  has the SAME render_report call, so dedup")
    print(f"  should reject all but the first.")
    try:
        result = loop.run("loop forever")
    except Exception as exc:
        print(f"loop ended: {type(exc).__name__}: {exc}")
    print()
    print(f"=== Loop stats ===")
    print(f"  LLM turns requested: {loop._client.turns}")
    print(f"  distinct signatures recorded: "
          f"{len(loop._called_signatures)}")
    print(f"  total tool calls actually executed: "
          f"{sum(loop._tool_call_counts.values())}")
    print(f"  per-tool counts: "
          f"{dict(loop._tool_call_counts)}")

    # Now
    # also
    # simulate
    # a
    # single
    # render_report
    # call
    # that
    # is
    # exempt
    # from
    # the
    # per-tool
    # cap.
    # Show
    # that
    # render_report
    # can
    # be
    # called
    # 5
    # times
    # with
    # DIFFERENT
    # arguments
    # (signatures
    # differ).
    print()
    print(f"=== render_report with 5 distinct args ===")
    loop2_calls: list[str] = []
    class VaryLLM:
        name = "vary"
        def __init__(self) -> None:
            self.turns = 0
        def chat(self, *args, **kwargs):
            self.turns += 1
            return ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": f"v{self.turns}",
                    "name": "render_report",
                    "input": {"markdown": f"v{self.turns}"},
                }],
                stop_reason="tool_use",
                usage={},
                model="test",
            )
        def chat_stream(self, messages, tools, **kw):
            self.turns += 1
            yield ChatResponse(
                content_blocks=[{
                    "type": "tool_use",
                    "id": f"v{self.turns}",
                    "name": "render_report",
                    "input": {"markdown": f"v{self.turns}"},
                }],
                stop_reason="tool_use",
                usage={},
                model="test",
            )
        def is_available(self) -> bool:
            return True
        def analyze_finding(self, f): return None

    loop2 = AgentLoop(
        client=VaryLLM(),
        tools=tools,
        ctx=ctx,
    )
    # Force
    # the
    # loop
    # to
    # run
    # 5
    # turns.
    loop2._max_steps = 6
    try:
        loop2.run("vary")
    except Exception as exc:
        print(f"loop2 ended: {type(exc).__name__}: {exc}")
    print(f"  LLM turns: {loop2._client.turns}")
    print(f"  total render_report runs: "
          f"{loop2._tool_call_counts.get('render_report', 0)}")
    print(f"  (expected: 5 -- exempt from per-tool cap)")


if __name__ == "__main__":
    main()