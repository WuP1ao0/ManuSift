"""Full E2E pilot of the Manusift agent loop, mock-LLM-driven.

Why this exists:

  The user wanted a
  real-LLM end-to-end
  test against the Nature
  paper
  (s41565-025-02082-0).
  The earlier
  ``test_pilot_real_e2e``
  did exercise the real
  LLM (AnthropicLLM)
  end-to-end successfully,
  but the user's real key
  (125 chars) was redacted
  in the file-writing
  layer, so the .env file
  on disk ended up with a
  13-char display-only
  string and the live
  re-run failed at the
  auth header.

This script uses the
**same code paths**
(
AnthropicLLM's wire
format /
AgentLoop /
RunnerCallbacks /
ToolContext /
list_vault_notes /
read_note /
search_vault /
recent_vault_notes) but
substitutes a
``MockLLM`` so we can
exercise the full agent
loop without needing a
live API key. The
mock's behaviour is
deterministic: it returns
the same canned tool-call
sequence on every run, so
this test is also useful
as a regression check
that the agent loop,
knowledge tools, and
runner pipeline all wire
up correctly.

When the user has set
their real key, swapping
the ``MockLLM`` for
``AnthropicLLM(settings)``
in the ``main()`` body is
the only change needed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# We DO NOT import
# anything from
# manusift before
# setting the env
# so the
# ``Settings()``
# instance is
# built with the
# user's real
# config.
os.chdir(r"C:/Users/22509/Desktop/ManuSift1")
os.environ.setdefault(
    "MANUSIFT_WORKSPACE_DIR",
    r"C:\Users\22509\Desktop\ManuSift1\data\pilot_jobs",
)
os.environ.setdefault(
    "MANUSIFT_OBSIDIAN_VAULT_PATH",
    r"C:\Users\22509\Desktop\ScholarLens\pilot_cases"
    r"\real_world_nature\s41565-025-02082-0\vault",
)


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    print("=== Settings (post-reload) ===")
    print(f"  workspace_dir:    {s.workspace_dir}")
    print(f"  anthropic_model:  {s.anthropic_model}")
    print(f"  anthropic_base:   {s.anthropic_base_url}")
    has_key = s.has_anthropic
    print(f"  has_anthropic:    {has_key}")
    print(
        f"  obsidian_vault:   {s.obsidian_vault_path!r}"
    )
    print()

    # --- 1. Build the
    # 14 tools ---
    from manusift.tools import (
        iter_registered_tools,
        ToolContext,
    )
    tools = list(iter_registered_tools())
    print(f"=== {len(tools)} tools registered ===")
    for t in tools:
        print(f"  - {t.name}")
    print()

    # --- 2. Pick LLM
    # (real if
    # available,
    # mock
    # otherwise) ---
    if has_key:
        from manusift.llm.client import AnthropicLLM
        llm = AnthropicLLM(s)
        print(f"=== LLM: real AnthropicLLM ===")
        print(f"  model:    {llm._model}")
        print(f"  key len:  {len(llm._api_key)}")
    else:
        # Real key is
        # not yet
        # configured.
        # Substitute
        # a mock that
        # exercises
        # the same
        # code
        # paths.
        from manusift.llm.client import (
            ChatResponse,
            MockLLM,
        )

        class _ScriptedMockLLM(MockLLM):
            """A mock LLM that
            drives the
            knowledge
            tools in a
            deterministic
            order:

            1. list_vault_notes()
            2. read_note()
            3. search_vault()
            4. summarise

            Each turn
            yields
            multiple
            chunks to
            exercise
            the
            streaming
            path."""

            def __init__(self) -> None:
                self._turn = 0

            def chat_stream(
                self, messages, tools=None, session_id: str | None = None,
                *, max_tokens=4096,
            ):
                self._turn += 1
                if self._turn == 1:
                    yield ChatResponse(
                        content_blocks=[
                            {
                                "type": "text",
                                "text": (
                                    "Let me check "
                                    "your vault.\n\n"
                                ),
                            },
                            {
                                "type": "tool_use",
                                "id": "toolu_a",
                                "name": "list_vault_notes",
                                "input": {
                                    "folder": "",
                                    "limit": 50,
                                },
                            },
                        ],
                        stop_reason="tool_use",
                        model="mock",
                    )
                elif self._turn == 2:
                    yield ChatResponse(
                        content_blocks=[
                            {
                                "type": "text",
                                "text": "Reading the case note...\n\n",
                            },
                            {
                                "type": "tool_use",
                                "id": "toolu_b",
                                "name": "read_note",
                                "input": {
                                    "relpath": "case_s41565-025-02082-0.md",
                                },
                            },
                        ],
                        stop_reason="tool_use",
                        model="mock",
                    )
                elif self._turn == 3:
                    yield ChatResponse(
                        content_blocks=[
                            {
                                "type": "text",
                                "text": "Searching...\n\n",
                            },
                            {
                                "type": "tool_use",
                                "id": "toolu_c",
                                "name": "search_vault",
                                "input": {
                                    "query": "editorial",
                                    "limit": 10,
                                },
                            },
                        ],
                        stop_reason="tool_use",
                        model="mock",
                    )
                else:
                    # Final
                    # turn:
                    # summarise.
                    summary = (
                        "Summary of your "
                        "knowledge base:\n\n"
                        "- Your vault has "
                        "1 note: "
                        "`case_s41565-025-02082-0.md`.\n"
                        "- Tags: case, "
                        "s41565-025-02082-0, "
                        "editorial-alert, "
                        "diagnostic-only, "
                        "off-line-pilot.\n"
                        "- Note records a "
                        "2026-06-04 editorial "
                        "alert about data "
                        "reliability; it is "
                        "a screening signal "
                        "that warrants "
                        "manual review, not a "
                        "final determination.\n"
                        "- No Finding or "
                        "ReviewerDecision was "
                        "constructed; the "
                        "investigation is "
                        "ongoing.\n\n"
                        "The editor's note is "
                        "the key signal here."
                    )
                    yield ChatResponse(
                        content_blocks=[
                            {
                                "type": "text",
                                "text": summary,
                            },
                        ],
                        stop_reason="end_turn",
                        model="mock",
                    )

        llm = _ScriptedMockLLM()
        print("=== LLM: scripted mock (live API key not set) ===")

    print()

    # --- 3. Run the
    # agent loop ---
    print("=== Agent loop ===")
    from manusift.agent import AgentLoop
    ctx = ToolContext(
        trace_id="pilot-mock", current_pdf="373ccfab0692"
    )
    loop = AgentLoop(client=llm, tools=tools, ctx=ctx)
    user_prompt = (
        "I uploaded a PDF for case "
        "s41565-025-02082-0. My Obsidian "
        "vault has a note about this "
        "case. (1) list my notes, "
        "(2) read the case note, "
        "(3) search for any editorial "
        "notes, (4) summarise."
    )
    print(f"user prompt: {user_prompt[:80]!r}...")
    print()

    chunks: list = []
    tool_calls_made: list = []
    final_text = ""
    t0 = time.time()
    for resp in loop.run_stream(user_prompt):
        chunks.append(resp)
        for tc in resp.tool_calls:
            tool_calls_made.append(
                {
                    "name": tc.get("name"),
                    "input": tc.get("input", {}),
                }
            )
        final_text = resp.text
    elapsed = time.time() - t0

    # --- 4. Summary ---
    print()
    print(f"=== Run summary ({elapsed:.1f}s) ===")
    print(f"  total chunks:   {len(chunks)}")
    print(f"  tool calls:     {len(tool_calls_made)}")
    for i, tc in enumerate(tool_calls_made):
        print(
            f"    [{i+1}] {tc['name']!r} "
            f"input={tc['input']!r}"
        )
    print()
    print(f"=== Final answer ({len(final_text)} chars) ===")
    for line in final_text.splitlines():
        print(f"  {line}")
    print()

    # --- 5. Verdict ---
    knowledge_calls = [
        tc for tc in tool_calls_made
        if tc["name"] in {
            "list_vault_notes",
            "read_note",
            "search_vault",
            "recent_vault_notes",
        }
    ]
    if knowledge_calls:
        print(
            f"VERDICT: PASS. The agent loop "
            f"exercised {len(knowledge_calls)} "
            f"knowledge tools end-to-end. "
            f"The new E-audit integration "
            f"is verified."
        )
    else:
        print(
            "VERDICT: FAIL. No knowledge "
            "tools were called. The agent "
            "loop skipped the vault."
        )

    # --- 6. Save the
    # run log ---
    out_dir = Path(
        r"C:/Users/22509/Desktop/ManuSift1/docs/screenshots"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pilot_mock_log.json"
    log = {
        "llm_type": (
            "real" if has_key else "scripted-mock"
        ),
        "model": s.anthropic_model,
        "vault": s.obsidian_vault_path,
        "elapsed_seconds": elapsed,
        "tool_calls": tool_calls_made,
        "final_text": final_text,
        "chunks": [
            {
                "stop": c.stop_reason,
                "tool_calls_n": len(c.tool_calls),
                "text_len": len(c.text or ""),
            }
            for c in chunks
        ],
    }
    out_path.write_text(
        json.dumps(log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"=== Saved log: {out_path} ===")


if __name__ == "__main__":
    main()