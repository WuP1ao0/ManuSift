"""Real end-to-end test of the Manusift agent loop with a live LLM.

E2 pilot: drive the full
agent loop against a
Nature paper PDF using
the user's Anthropic-
compatible endpoint.

Test surface:

  1. Build the real
     AnthropicLLM with
     the user's
     ``MANUSIFT_*`` env
     settings.
  2. Construct the 14
     tools (10 detector
     adapters + 4
     knowledge tools).
  3. Verify the LLM is
     reachable (single
     chat call).
  4. Run the agent loop
     on the uploaded PDF
     with a user prompt
     that asks the LLM
     to consult the
     knowledge base.
  5. Capture every
     tool call the LLM
     makes + the final
     answer.
  6. Verify the
     knowledge tools
     were actually called
     end-to-end (i.e.
     the new E-audit
     integration really
     works).

Saves the full
conversation log to
``docs/screenshots/pilot_log.json``
so the user can read it
back.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    # Repo-relative working directory (works on any machine).
    os.chdir(str(Path(__file__).resolve().parents[1]))
    # The API key must come from the environment (or .env) --
    # never hard-code credentials in the repo. Missing key ->
    # clear message instead of a cryptic downstream failure.
    if not os.environ.get("MANUSIFT_ANTHROPIC_API_KEY"):
        raise SystemExit(
            "MANUSIFT_ANTHROPIC_API_KEY is not set; export it "
            "(or put it in .env) before running this pilot."
        )
    os.environ.setdefault(
        "MANUSIFT_ANTHROPIC_BASE_URL",
        "https://api.minimaxi.com/anthropic",
    )
    os.environ.setdefault("MANUSIFT_ANTHROPIC_MODEL", "MiniMax-Text-01")
    os.environ.setdefault("MANUSIFT_DEFAULT_LLM_PROVIDER", "anthropic")
    os.environ.setdefault(
        "MANUSIFT_WORKSPACE_DIR",
        str(Path("data/pilot_jobs").resolve()),
    )

    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    print("=== Settings ===")
    print(f"  workspace_dir:      {s.workspace_dir}")
    print(f"  anthropic_model:    {s.anthropic_model}")
    print(f"  anthropic_base_url: {s.anthropic_base_url}")
    print(f"  has_anthropic:      {s.has_anthropic}")
    print(
        f"  obsidian_vault_path: {s.obsidian_vault_path!r}"
    )
    print()

    # ---- 1. Tools ----
    from manusift.tools import (
        iter_registered_tools,
        ToolContext,
    )
    from manusift.llm.client import AnthropicLLM
    tools = list(iter_registered_tools())
    print(f"=== {len(tools)} tools ===")
    for t in tools:
        print(f"  {t.name}")
    print()

    # ---- 2. Real LLM ----
    print("=== AnthropicLLM ===")
    llm = AnthropicLLM(s)
    print(f"  model:    {llm._model}")
    print(f"  base_url: {llm._base_url}")
    print(f"  key len:  {len(llm._api_key) if llm._api_key else 0}")
    print()

    # ---- 3. Single chat
    # ping ----
    print("=== LLM ping (single chat) ===")
    try:
        ping = llm.chat(
            messages=[
                {
                    "role": "user",
                    "content": "Reply with exactly one word: READY",
                }
            ],
            tools=[],
        )
        print(f"  status:  ok")
        print(f"  text:    {ping.text!r}")
        print(f"  stop:    {ping.stop_reason!r}")
        print(f"  model:   {ping.model!r}")
    except Exception as exc:
        print(f"  ERROR:    {type(exc).__name__}: {exc}")
        # Print a
        # stacktrace to
        # the log too.
        import traceback
        traceback.print_exc()
        return
    print()

    # ---- 4. Agent loop
    # with the
    # knowledge tool
    # actually called
    # ----
    print("=== Agent loop (real PDF + knowledge tool) ===")
    trace_id = "pilot-real"
    pdf_trace = "373ccfab0692"
    ctx = ToolContext(
        trace_id=trace_id, current_pdf=pdf_trace
    )

    from manusift.agent import AgentLoop
    from manusift.contracts import ChatMessage

    # Build the loop.
    loop = AgentLoop(
        client=llm,
        tools=tools,
        ctx=ctx,
    )

    # The user prompt.
    # We deliberately
    # ask the LLM to
    # consult the
    # knowledge base
    # so the new E
    # integration is
    # exercised.
    user_prompt = (
        "I just uploaded a PDF (Nature Nanotechnology, "
        "s41565-025-02082-0). My knowledge base in "
        "the configured Obsidian vault has a note about "
        "this case. \n"
        "1. List the notes in my vault so you can see "
        "what is there.\n"
        "2. Read the note that matches this case.\n"
        "3. Search the vault for any other notes that "
        "mention 'editorial' or 'reliability'.\n"
        "4. Summarise what my knowledge base says about "
        "this case, citing the note ids / paths you used."
    )

    print(f"User prompt ({len(user_prompt)} chars):")
    print(f"  {user_prompt[:200]!r}...")
    print()

    # Capture every
    # chunk and every
    # tool call.
    chunks: list = []
    tool_calls_made: list = []
    final_text: str = ""
    final_turns = 0
    t0 = time.time()
    try:
        for resp in loop.run_stream(user_prompt):
            chunks.append(
                {
                    "text": resp.text,
                    "stop_reason": resp.stop_reason,
                    "model": resp.model,
                    "usage": resp.usage,
                    "tool_calls": [
                        {
                            "id": tc.get("id"),
                            "name": tc.get("name"),
                            "input": tc.get("input", {}),
                        }
                        for tc in resp.tool_calls
                    ],
                }
            )
            for tc in resp.tool_calls:
                tool_calls_made.append(
                    {
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "input": tc.get("input", {}),
                    }
                )
            final_text = resp.text
            final_turns = loop._streaming_turns
    except Exception as exc:
        print(f"  ERROR in run_stream: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()

    elapsed = time.time() - t0

    # ---- 5. Report ----
    print()
    print(f"=== Run summary ({elapsed:.1f}s) ===")
    print(f"  total chunks:  {len(chunks)}")
    print(f"  final turns:   {final_turns}")
    print(f"  final text:    {final_text[:300]!r}")
    print()
    print(f"=== Tool calls ({len(tool_calls_made)}) ===")
    for i, tc in enumerate(tool_calls_made):
        print(
            f"  [{i+1}] {tc['name']!r} "
            f"input={json.dumps(tc['input'], ensure_ascii=False)[:120]}"
        )
    print()

    # ---- 6. Save the
    # log ----
    out = {
        "trace_id": trace_id,
        "pdf_trace_id": pdf_trace,
        "user_prompt": user_prompt,
        "elapsed_seconds": elapsed,
        "total_chunks": len(chunks),
        "final_turns": final_turns,
        "final_text": final_text,
        "tool_calls": tool_calls_made,
        "chunk_summaries": [
            {
                "stop_reason": c["stop_reason"],
                "tool_calls_n": len(c["tool_calls"]),
                "text_len": len(c["text"] or ""),
            }
            for c in chunks
        ],
    }
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pilot_log.json"
    out_path.write_text(
        json.dumps(out, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"=== Saved log to {out_path} ===")

    # Verdict.
    knowledge_calls = [
        tc
        for tc in tool_calls_made
        if tc["name"]
        in (
            "list_vault_notes",
            "read_note",
            "search_vault",
            "recent_vault_notes",
        )
    ]
    print()
    if knowledge_calls:
        print(
            f"VERDICT: SUCCESS. The LLM called {len(knowledge_calls)} "
            f"knowledge tools during the agent run, exercising "
            f"the new E-audit integration end-to-end."
        )
    else:
        print(
            "VERDICT: LLM did not call any knowledge tools. "
            "Possible reasons: (a) the LLM decided it did not "
            "need the vault; (b) the LLM hallucinated the path; "
            "(c) tool calling is not yet enabled on this "
            "model. Check the chunk log."
        )


if __name__ == "__main__":
    main()
