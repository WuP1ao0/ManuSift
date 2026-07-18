"""Audit: does the LLM actually pick the RIGHT tool for the user's question?

The previous audit
(R-audit-i18n, 2026-06-10)
wired all 31 detectors
into the tool list. The
LLM now sees 44 tools.
But the user is asking:
does the LLM know *when*
to call each one?

This script runs the LLM
through a battery of
9 representative prompts
and scores which tool(s)
the LLM chose to call.
The prompts are designed
to map onto specific
detectors; if the LLM
picks the wrong tool (or
no tool), the audit fails.

Pass criteria (per prompt):

  * The LLM picks the
    detector that maps to
    the user's question.
  * OR: the LLM picks
    ``list_findings`` as
    a meta-call when it
    cannot decide (which
    is acceptable for
    ambiguous prompts).
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


# A prompt + the tool(s)
# we EXPECT the LLM to
# call. ``expected`` is
# a set -- multiple
# tools may all be valid
# for a given prompt.
@dataclass
class _RoutingCase:
    prompt: str
    expected: set[str] = field(default_factory=set)
    # Optional
    # notes
    # for
    # the
    # audit
    # reader.
    note: str = ""


TEST_CASES = [
    _RoutingCase(
        prompt=(
            "Are there any duplicate images in this paper?"
        ),
        expected={"image_dup"},
        note="image duplication is the canonical image_dup job",
    ),
    _RoutingCase(
        prompt=(
            "Does the figure show signs of JPEG manipulation?"
        ),
        expected={"image_forensics"},
        note="ELA / copy-move = image_forensics",
    ),
    _RoutingCase(
        prompt=(
            "Do the numbers in this paper follow Benford's "
            "law? I want to check the source-data XLSX."
        ),
        expected={
            "table_benford",
            "list_data_sources",
            "read_data_source",
        },
        note=(
            "best case the LLM enumerates data sources "
            "first then runs Benford on each"
        ),
    ),
    _RoutingCase(
        prompt=(
            "Check if the authors' email addresses look "
            "legit (no gmail / yahoo / qq)."
        ),
        expected={"author_emails"},
        note="email-pattern check is author_emails",
    ),
    _RoutingCase(
        prompt=(
            "Are there any tortured phrases like "
            "'tribal knowledge' that suggest the paper "
            "was machine-paraphrased?"
        ),
        expected={"text_tortured_phrases"},
        note="tortured phrases = text_tortured_phrases",
    ),
    _RoutingCase(
        prompt=(
            "Check whether the GRIM test fails for the "
            "reported means in the table."
        ),
        expected={"stat_grim"},
        note="GRIM = stat_grim",
    ),
    _RoutingCase(
        prompt=(
            "Are any of the cited references fabricated? "
            "Crossref-validate the DOIs."
        ),
        expected={"citation_network", "ref_duplicate"},
        note="DOI / Crossref = citation_network",
    ),
    _RoutingCase(
        prompt=(
            "Find the duplicate rows inside the "
            "supplementary XLSX files."
        ),
        expected={
            "table_duplicate_row",
            "list_data_sources",
        },
        note=(
            "XLSX has to be enumerated first; the LLM "
            "should list_data_sources before table_duplicate_row"
        ),
    ),
    _RoutingCase(
        prompt=(
            "Does the data availability statement comply "
            "with Nature's policy?"
        ),
        expected={"compliance"},
        note="compliance-statement detector",
    ),
]


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    if not s.has_anthropic:
        print("no ANTHROPIC_API_KEY -- skipping live audit")
        return

    from manusift.tools import iter_registered_tools
    from manusift.llm.client import AnthropicLLM
    from manusift.agent import AgentLoop
    from manusift.tools.tool import ToolContext

    llm = AnthropicLLM(s)
    tools = list(iter_registered_tools())
    print(f"=== Tools available: {len(tools)} ===\n")

    # Single
    # shared
    # loop
    # so
    # the
    # system
    # prompt
    # is
    # built
    # once.
    ctx = ToolContext(
        trace_id="audit-test",
        current_pdf="audit-test",
    )
    loop = AgentLoop(
        client=llm, tools=tools, ctx=ctx
    )
    sp = loop._system_prompt

    results = []
    for i, tc in enumerate(TEST_CASES):
        print(
            f"=== Prompt {i+1}/{len(TEST_CASES)}: {tc.prompt[:60]}... ==="
        )
        print(f"  expected: {sorted(tc.expected)}")
        t0 = time.time()
        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": sp},
                    {
                        "role": "user",
                        "content": tc.prompt,
                    },
                ],
                tools=loop._tool_dicts(),
                max_tokens=1024,
            )
            elapsed = time.time() - t0
            called = [tc.get("name") for tc in resp.tool_calls]
            hit = set(called) & tc.expected
            miss = tc.expected - set(called)
            extra = set(called) - tc.expected
            status = "PASS" if hit else "FAIL"
            print(f"  called: {called}")
            print(
                f"  elapsed: {elapsed:.1f}s  [{status}]  "
                f"hit={sorted(hit)} miss={sorted(miss)} extra={sorted(extra)}"
            )
            results.append(
                {
                    "prompt": tc.prompt,
                    "expected": sorted(tc.expected),
                    "called": called,
                    "hit": sorted(hit),
                    "miss": sorted(miss),
                    "elapsed": elapsed,
                    "note": tc.note,
                    "status": status,
                }
            )
        except Exception as exc:
            elapsed = time.time() - t0
            print(f"  ERROR ({elapsed:.1f}s): {exc}")
            results.append(
                {
                    "prompt": tc.prompt,
                    "expected": sorted(tc.expected),
                    "called": [],
                    "error": str(exc),
                    "status": "ERROR",
                }
            )
        print()

    # Summary.
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_err = sum(1 for r in results if r["status"] == "ERROR")
    print(
        f"=== Summary: {n_pass} pass / {n_fail} fail / {n_err} error "
        f"(out of {len(results)}) ==="
    )

    out_path = str(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "screenshots"
        / "pilot_tool_routing_audit.json"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"=== Saved: {out_path} ===")


if __name__ == "__main__":
    main()
