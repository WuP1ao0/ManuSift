"""E2E: real LLM writes a narrative report end-to-end.

This script drives the
agent loop through a
deliberate
investigation:

  1. list_findings to
     see the inventory.
  2. read_finding on
     the top findings.
  3. search_vault +
     read_note to
     cross-reference
     the local
     knowledge base.
  4. write markdown.
  5. render_report to
     write the
     narrative HTML
     / PDF.

The LLM is the real
``AnthropicLLM`` with
``MiniMax-M3`` and the
user's key (read from
``.env``); the script
relies on the same env
setup the user already
has.

Run with::

  .venv/Scripts/python.exe
    tests/test_real_narrative_e2e.py

Saves the resulting
markdown + HTML to
``docs/screenshots/pilot_narrative.*``
so the user can read the
report.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "MANUSIFT_WORKSPACE_DIR",
    str(Path(__file__).resolve().parents[1] / "data" / "pilot_jobs"),
)
os.environ.setdefault(
    "MANUSIFT_OBSIDIAN_VAULT_PATH",
    str(
        Path(
            os.environ.get(
                "MANUSIFT_PILOT_VAULT",
                Path(__file__).resolve().parents[1]
                / "docs"
                / "s41565-025-02082-0",
            )
        )
        / "vault"
    ),
)


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    has_key = s.has_anthropic
    print(f"=== Settings ===")
    print(f"  workspace: {s.workspace_dir}")
    print(f"  has_anthropic: {has_key}")
    print(f"  obsidian vault: {s.obsidian_vault_path}")
    print()

    if not has_key:
        print("ERROR: no ANTHROPIC_API_KEY in .env.")
        return

    from manusift.tools import (
        iter_registered_tools,
        ToolContext,
    )
    from manusift.llm.client import AnthropicLLM
    tools = list(iter_registered_tools())
    print(f"=== {len(tools)} tools registered ===")
    for t in tools:
        print(f"  - {t.name}")
    print()

    # The trace
    # id of
    # the
    # most
    # recent
    # pilot
    # job.
    trace_id = "e6f244000eac"
    ctx = ToolContext(trace_id=trace_id, current_pdf=None)
    llm = AnthropicLLM(s)

    # The user
    # prompt --
    # in
    # real
    # production
    # this
    # would
    # be
    # a
    # slash
    # command
    # or
    # a
    # button
    # click.
    # For
    # the
    # pilot
    # we
    # write
    # it
    # directly.
    user_prompt = (
        "Use the /skill integrity_report workflow to "
        "produce a narrative integrity report for the "
        "currently bound PDF (trace_id="
        + trace_id
        + "). Step by step: call list_findings to get "
        "the inventory, read_finding for the top 3 high-"
        "severity findings, search_vault + read_note to "
        "cross-reference any matching local case notes, "
        "and finally call render_report with the full "
        "markdown. The markdown should follow the 7-section "
        "structure (Executive Summary, Paper Under "
        "Review, Diagnostic Surface, Key Findings, "
        "Knowledge-Base Cross-References, Recommended "
        "Next Steps, Disclaimer). Be cautious: this is a "
        "screening signal, not a determination."
    )

    from manusift.agent import AgentLoop
    loop = AgentLoop(client=llm, tools=tools, ctx=ctx)
    print(f"=== Agent loop running ({len(user_prompt)} chars prompt) ===")
    chunks = []
    tool_calls_made = []
    final_text = ""
    t0 = time.time()
    for resp in loop.run_stream(user_prompt):
        chunks.append(resp)
        for tc in resp.tool_calls:
            tool_calls_made.append({
                "name": tc.get("name"),
                "input": tc.get("input", {}),
            })
        final_text = resp.text
    elapsed = time.time() - t0
    print(f"  elapsed: {elapsed:.1f}s, chunks: {len(chunks)}, tool calls: {len(tool_calls_made)}")
    print()
    print(f"=== Tool calls ({len(tool_calls_made)}) ===")
    for i, tc in enumerate(tool_calls_made):
        inp = json.dumps(tc['input'], ensure_ascii=False)
        print(f"  [{i+1}] {tc['name']!r}  input={inp[:80]}")
    print()
    print(f"=== Final answer ({len(final_text)} chars) ===")
    print(final_text[:800])

    # Did the
    # LLM
    # call
    # render_report?
    render_calls = [
        tc for tc in tool_calls_made
        if tc["name"] == "render_report"
    ]
    if render_calls:
        print()
        print(f"=== render_report was called {len(render_calls)} time(s) ===")
        for i, tc in enumerate(render_calls):
            md = tc["input"].get("markdown", "")
            print(f"  call [{i+1}]: {len(md)} chars markdown")
            print(f"  first 300 chars: {md[:300]!r}")
    else:
        print()
        print("=== LLM did NOT call render_report ===")
        print("  This is fine -- the user can run /skill integrity_report")

    # Save the
    # final
    # text
    # to disk
    # for
    # inspection.
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pilot_narrative_log.json").write_text(
        json.dumps({
            "trace_id": trace_id,
            "elapsed": elapsed,
            "tool_calls": tool_calls_made,
            "chunks": len(chunks),
            "final_text": final_text,
            "render_report_called": len(render_calls),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"=== Saved log: {out_dir / 'pilot_narrative_log.json'} ===")

    # Did the
    # report
    # files
    # get
    # written?
    job_dir = Path(s.workspace_dir) / trace_id
    print(f"=== Job dir: {job_dir} ===")
    for f in sorted(job_dir.iterdir()):
        if f.is_file():
            print(f"  {f.name}: {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
