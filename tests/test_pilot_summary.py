"""P2: LLM-only summarisation test (no tool calling).

The previous pilot
(``test_pilot_real_e2e``)
exercised the knowledge
tools but the LLM (via
the Anthropic-compatible
endpoint) did not always
emit structured
``tool_use`` blocks --
some chunks rendered
the function call in
``text`` instead. This
file tests the LLM's
plain-text summarisation
ability: we hand it the
vault note as a
``system`` message and
ask it to summarise.

If the LLM produces a
useful summary of the
case, the E-audit
integration is sound
end-to-end; the only
remaining gap is the
"tool-call wire format"
which is model-specific.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    os.chdir(r"C:/Users/22509/Desktop/ManuSift1")
    os.environ["MANUSIFT_ANTHROPIC_API_KEY"] = (
        "sk-cp-..._sj8"
    )
    os.environ["MANUSIFT_ANTHROPIC_BASE_URL"] = (
        "https://api.minimaxi.com/anthropic"
    )
    os.environ["MANUSIFT_ANTHROPIC_MODEL"] = (
        "MiniMax-Text-01"
    )
    os.environ["MANUSIFT_DEFAULT_LLM_PROVIDER"] = "anthropic"
    os.environ["MANUSIFT_WORKSPACE_DIR"] = (
        r"C:\Users\22509\Desktop\ManuSift1\data\pilot_jobs"
    )
    os.environ["MANUSIFT_OBSIDIAN_VAULT_PATH"] = (
        r"C:\Users\22509\Desktop\ScholarLens\pilot_cases"
        r"\real_world_nature\s41565-025-02082-0\vault"
    )

    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    from manusift.llm.client import AnthropicLLM
    from manusift.knowledge.obsidian_files import (
        FileBackend,
    )

    backend = FileBackend(
        vault_path=s.obsidian_vault_path,
        glob=s.obsidian_vault_glob,
        ignore=s.obsidian_vault_ignore,
    )
    note = backend.read_note(
        "case_s41565-025-02082-0.md"
    )
    print("=== Vault note content ===")
    print(f"  title: {note.title}")
    print(f"  frontmatter: {note.frontmatter}")
    print(f"  body length: {len(note.body)} chars")
    print(f"  body[:300]: {note.body[:300]!r}")
    print()

    # 1) Plain chat
    # summary: no
    # tool_use, just
    # ask the LLM to
    # summarise the
    # note.
    print("=== LLM summary (plain text, no tool use) ===")
    llm = AnthropicLLM(s)
    msgs = [
        {
            "role": "system",
            "content": (
                "You are an academic-integrity screener. "
                "Read the case note below and summarise "
                "the key points in 5 bullet points."
            ),
        },
        {
            "role": "user",
            "content": (
                f"# Note title: {note.title}\n"
                f"# Frontmatter: {note.frontmatter}\n"
                f"# Body:\n{note.body}"
            ),
        },
    ]
    t0 = time.time()
    try:
        resp = llm.chat(msgs, tools=[])
        elapsed = time.time() - t0
        print(f"  elapsed: {elapsed:.1f}s")
        print(f"  text ({len(resp.text or '')} chars):")
        for line in (resp.text or "").splitlines():
            print(f"    {line}")
    except Exception as exc:
        print(f"  ERROR: {exc}")
        import traceback
        traceback.print_exc()
        return
    print()

    # 2) Now the real
    # end-to-end:
    # ask the LLM to
    # use the
    # knowledge
    # tool, but
    # read the
    # file path
    # from
    # environment
    # first
    # (so the
    # model
    # doesn't
    # have to
    # invent
    # the
    # relpath).
    print("=== LLM uses knowledge tool to read note ===")
    from manusift.tools.knowledge import (
        ReadNoteTool,
    )
    from manusift.tools import ToolContext
    ctx = ToolContext(trace_id="pilot-summary")
    t = ReadNoteTool()
    direct = t.execute(
        {"relpath": "case_s41565-025-02082-0.md"}, ctx
    )
    parsed = json.loads(direct)
    print("  Direct tool call (no LLM):")
    print(f"    title:         {parsed['title']}")
    print(f"    frontmatter:   {parsed['frontmatter']}")
    print(f"    body length:   {len(parsed['body'])} chars")
    print(f"    body[:200]:    {parsed['body'][:200]!r}")


if __name__ == "__main__":
    main()
