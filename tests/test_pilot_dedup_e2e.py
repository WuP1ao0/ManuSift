"""E2E: real LLM does the integrity_report skill with dedup active.

The previous pilot
(integrity_report, before
this audit) called
``render_report`` 99
times in a row, all
identical. The
R-audit-2026-06-10 dedup
should cap that to:

  * the first call
    runs,
  * every subsequent
    identical call is
    rejected with an
    error message, and
  * the LLM has
    3 (capped) calls
    per non-exempt
    tool to gather
    evidence.

This script runs the
integrity_report skill
and prints:
  * the total tool calls
  * how many were
    duplicates (would
    have been rejected)
  * which tools were
    called how many
    times.
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
        print("no ANTHROPIC_API_KEY -- skipping")
        return

    from manusift.agent import AgentLoop
    from manusift.llm.client import AnthropicLLM
    from manusift.tools import iter_registered_tools
    from manusift.tools.tool import ToolContext

    tools = list(iter_registered_tools())
    llm = AnthropicLLM(s)
    ctx = ToolContext(
        trace_id=TRACE_ID, current_pdf=TRACE_ID
    )
    loop = AgentLoop(client=llm, tools=tools, ctx=ctx)

    # Run the
    # integrity_report
    # skill -- but trim
    # the body so the LLM
    # does not over-think.
    from manusift.skills import load_skill
    from pathlib import Path

    skill = load_skill(
        "integrity_report",
        skills_dir=Path("data/skills"),
    )
    # Use
    # only
    # the
    # first
    # 1500
    # chars
    # of
    # the
    # skill
    # body
    # to
    # keep
    # the
    # LLM
    # fast.
    user_prompt = (
        f"{skill.body[:1500]}\n\n"
        f"trace_id={TRACE_ID}\n"
        "Use the language matching the user (English). "
        "Call the most informative detectors first, then "
        "render_report once at the end."
    )

    print(f"=== running integrity_report skill ===")
    print(f"  max_steps: {loop._max_steps}")
    print(f"  tools: {len(tools)}")
    t0 = time.time()
    result = loop.run(user_prompt)
    elapsed = time.time() - t0
    print(f"\n=== Result ===")
    print(f"  elapsed: {elapsed:.1f}s")
    print(f"  final text length: {len(result.text)}")
    print(f"  total tool calls (incl deduped): "
          f"{len(loop._called_signatures)} distinct sigs, "
          f"{sum(loop._tool_call_counts.values())} total executed")
    print()
    print("Per-tool counts:")
    for name, count in sorted(
        loop._tool_call_counts.items(),
        key=lambda kv: -kv[1],
    ):
        cap_marker = (
            " [capped]"
            if count >= loop._MAX_SAME_TOOL_CALLS
            and name not in loop._TOOLS_EXEMPT_FROM_CAP
            else ""
        )
        print(f"  {name}: {count}{cap_marker}")


if __name__ == "__main__":
    main()