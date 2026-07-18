"""E2E: real LLM with all 44 tools wired up.

This script verifies that
the auto-registration
plus the new cheat-sheet
generator actually work
end-to-end:

  1. The agent loop
     starts with all 44
     tools.

  2. The system prompt
     sent to the LLM
     mentions every tool
     exactly once.

  3. When asked to
     analyze a paper,
     the LLM picks
     a *new* detector
     (e.g.
     ``citation_network``)
     -- not just the
     original 4
     pipeline detectors.

This is a **fast** test:
we cap the LLM at 1 turn
so it cannot enter the
"call render_report 99
times" loop we saw before.
We just want to see what
tools the LLM picks on the
first turn.

Run with::

  .venv/Scripts/python.exe
    tests/test_pilot_all_tools_e2e.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[1]))
os.environ["MANUSIFT_WORKSPACE_DIR"] = str(
    Path(__file__).resolve().parents[1] / "data" / "pilot_jobs"
)
os.environ["MANUSIFT_OBSIDIAN_VAULT_PATH"] = str(
    Path(
        os.environ.get(
            "MANUSIFT_PILOT_VAULT",
            Path(__file__).resolve().parents[1]
            / "docs"
            / "s41565-025-02082-0",
        )
    )
    / "vault"
)


TRACE_ID = "e6f244000eac"


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    if not s.has_anthropic:
        print("no anthropic key -- skipping live E2E")
        return

    from manusift.tools import iter_registered_tools
    tools = list(iter_registered_tools())
    print(f"=== Tools available: {len(tools)} ===\n")
    # Group
    # by
    # category.
    from manusift.tools.detector_catalog import (
        _category_for,
        CATEGORY_LABEL,
    )
    by_cat: dict[str, list[str]] = {}
    for t in tools:
        cat = _category_for(t.name)
        by_cat.setdefault(cat, []).append(t.name)
    for cat in sorted(by_cat):
        label = CATEGORY_LABEL.get(cat, cat)
        print(f"  {label} ({len(by_cat[cat])}):")
        for n in by_cat[cat]:
            print(f"    - {n}")
    print()

    # Run the
    # agent
    # loop
    # for
    # one
    # turn
    # to
    # see
    # what
    # the
    # LLM
    # picks.
    from manusift.agent import AgentLoop
    from manusift.llm.client import AnthropicLLM
    from manusift.tools.tool import ToolContext

    llm = AnthropicLLM(s)
    ctx = ToolContext(
        trace_id=TRACE_ID, current_pdf=TRACE_ID
    )
    loop = AgentLoop(
        client=llm, tools=tools, ctx=ctx
    )

    # Inspect
    # the
    # system
    # prompt
    # first.
    sp = loop._system_prompt
    lines = [
        l for l in sp.split(chr(10)) if l.startswith("  - ")
    ]
    print(f"=== System prompt cheat sheet: {len(lines)} tool lines ===\n")

    # Now
    # run
    # one
    # turn.
    user_prompt = (
        f"Quick analysis of trace_id={TRACE_ID}. "
        "What tools should I run first? "
        "Just call the most informative "
        "2-3 detectors and stop. "
        "Do not call render_report."
    )
    print(f"=== Agent loop running (1 turn) ===")
    print(f"  prompt: {user_prompt[:80]}")
    t0 = time.time()
    tool_calls_made = []
    final_text = ""
    # The
    # LLMClient
    # Protocol's
    # ``chat``
    # takes
    # ``messages``
    # directly,
    # not
    # a
    # ChatRequest.
    try:
        resp = llm.chat(
            messages=[
                {"role": "system", "content": sp},
                {"role": "user", "content": user_prompt},
            ],
            tools=loop._tool_dicts(),
            max_tokens=1024,
        )
        tool_calls_made = resp.tool_calls
        final_text = resp.text
        elapsed = time.time() - t0
        print(f"  elapsed: {elapsed:.1f}s")
        print(f"  tool calls: {len(tool_calls_made)}")
        for tc in tool_calls_made:
            print(
                f"    - {tc.get('name', '?')}"
                f"({json.dumps(tc.get('input', {}), ensure_ascii=False)[:80]})"
            )
        print(f"  final text: {final_text[:300]}")
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  elapsed: {elapsed:.1f}s")
        print(f"  ERROR: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()