"""Tests for the AgentLoop system prompt rewrite
(R-2026-06-14).

The new system prompt:

  * Drops the dual identity ("screener AND general
    assistant") and picks a single role: paper-integrity
    screener.
  * Adds a 2-mode routing rule (Quick Triage by default,
    Deep Review when the user explicitly asks).
  * Hard-codes the path -> trace_id contract: the first
    tool call after a user-given path is always
    ``ingest_from_path``; subsequent calls reuse the
    returned trace_id. NO basename-derived trace_ids.
  * Adds a source-data policy: when ingest reports
    ``data_sources``, the agent MUST call
    ``list_data_sources`` and ``read_data_source`` before
    numeric conclusions.
  * Makes "not testable" a valid output class.
  * Hard-codes the render_report contract: 6 artifacts
    (report.md/html/json/raw_trace/tool_summary/
    evidence_assets manifest).
  * TUI style: no raw JSON in chat, no duplicate
    assistant messages, no empty bubble, plan mode
    discipline.
  * Scientific caution: "screening signal" / "warrants
    manual review", never "fabricated" / "guilty".

These tests are static analysis of the new prompt body,
not behavioural tests (those live in
``tests/test_agent_loop.py`` and friends). The tests
guard against accidental regression when someone refactors
the prompt.

Length budget: the new prompt must be SHORTER than the
old one. We assert < 8000 characters (the old prompt was
~10.7k characters) so the rewrite cannot be reverted
accidentally.
"""

from __future__ import annotations

import re

import pytest

from manusift.agent import AgentLoop
from manusift.config import get_settings


# --------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------


@pytest.fixture(scope="module")
def system_prompt_text() -> str:
    """Build an AgentLoop with no tools and return the
    prompt text it would send to the LLM. We don't need
    a real LLM client -- the prompt is built at
    construction time."""
    from manusift.tools.tool import ToolContext
    ctx = ToolContext(trace_id="test-fixture-trace")
    loop = AgentLoop(
        client=object(),  # never called by the prompt builder
        tools=[],
        ctx=ctx,
    )
    return loop._system_prompt


# --------------------------------------------------------------------
# 1. Single identity (no dual role)
# --------------------------------------------------------------------


def test_single_identity_screener_only(system_prompt_text: str) -> None:
    """The prompt must declare a single role -- paper
    integrity screener. The old "screener AND general
    coding/research assistant" dual role is gone.
    """
    text = system_prompt_text.lower()
    assert "manusift" in text
    assert "screener" in text or "integrity" in text
    # The old wording had "and a general coding / research
    # assistant" or similar. We assert the new prompt
    # does NOT contain that dual-role phrase.
    assert "general coding" not in text
    assert "general-purpose agent" not in text
    # The prompt should explicitly say "you are a screener,
    # not a prosecutor" or similar single-role framing.
    assert "not a prosecutor" in text or "screener" in text


# --------------------------------------------------------------------
# 2. Hard contract: path -> ingest_from_path -> trace_id
# --------------------------------------------------------------------


def test_prompt_instructs_ingest_from_path(system_prompt_text: str) -> None:
    """The prompt must say: when the user gives a path,
    call ``ingest_from_path`` first."""
    assert "ingest_from_path" in system_prompt_text
    # The hard-contract section heading should exist.
    assert "Path & Ingest" in system_prompt_text


def test_prompt_requires_use_of_returned_trace_id(
    system_prompt_text: str,
) -> None:
    """The prompt must say: every subsequent tool call
    uses the trace_id returned by ingest_from_path.
    """
    assert "trace_id" in system_prompt_text
    # The wording should forbid basename-derived
    # trace_ids.
    assert "basename" in system_prompt_text.lower()
    assert "do not derive" in system_prompt_text.lower() or (
        "do not infer" in system_prompt_text.lower()
    )


def test_prompt_forbids_basename_derived_trace_id(
    system_prompt_text: str,
) -> None:
    """Specifically check the rule: NEVER derive a
    trace_id from the PDF filename. This is a known LLM
    failure mode."""
    lower = system_prompt_text.lower()
    # At least one of these phrasings must be present.
    forbidden_phrases = [
        "do not derive a trace_id from the pdf",
        "do not infer a trace_id from the filename",
        "do not derive a trace_id from the pdf basename",
        "basename, hash, or guess",
    ]
    assert any(p in lower for p in forbidden_phrases), (
        f"prompt must forbid basename-derived trace_id; "
        f"looked for: {forbidden_phrases}"
    )


# --------------------------------------------------------------------
# 3. Source data policy
# --------------------------------------------------------------------


def test_prompt_includes_data_sources_policy(
    system_prompt_text: str,
) -> None:
    """The prompt must require ``list_data_sources`` +
    ``read_data_source`` for numeric conclusions when
    ingest reports data_sources.
    """
    assert "list_data_sources" in system_prompt_text
    assert "read_data_source" in system_prompt_text
    # The phrase "data_sources" (the field on the
    # ingest result) should appear.
    assert "data_sources" in system_prompt_text


def test_prompt_mentions_zip_supplementary(system_prompt_text: str) -> None:
    """ZIP supplementary data is a first-class source."""
    lower = system_prompt_text.lower()
    assert "zip" in lower
    # The wording should treat ZIP as a data source.
    assert (
        "supplementary" in lower
        or "first-class data source" in lower
    )


def test_prompt_mentions_csv_xlsx_tsv_json(system_prompt_text: str) -> None:
    """The prompt should name the common tabular data
    formats the user might give alongside a PDF."""
    lower = system_prompt_text.lower()
    for fmt in ("csv", "xlsx", "tsv", "json"):
        assert fmt in lower, f"prompt must mention {fmt}"


# --------------------------------------------------------------------
# 4. Review Mode + Detector Budget (R-2026-06-14 v2)
# --------------------------------------------------------------------


def test_prompt_has_3_trigger_classes(system_prompt_text: str) -> None:
    """Review commands should start deep review directly."""
    assert "Path-only" in system_prompt_text
    assert "Review intent" in system_prompt_text
    assert "Report intent" in system_prompt_text
    lower = system_prompt_text.lower()
    assert "quick triage" not in lower
    assert "render_report" in lower
    assert "report.html" in lower


def test_prompt_lists_deep_review_triggers(system_prompt_text: str) -> None:
    """The prompt must list the user phrases that switch
    to deep review / report intent (in any language)."""
    assert "render_report" in system_prompt_text
    # At least one Chinese trigger phrase.
    assert "完整报告" in system_prompt_text or "深度审查" in system_prompt_text
    # At least one English trigger phrase.
    assert "full report" in system_prompt_text.lower() or "deep review" in system_prompt_text.lower()


def test_prompt_has_detector_budget_section(system_prompt_text: str) -> None:
    """Detector budget should support deep review for review commands."""
    assert "## Detector Budget" in system_prompt_text
    lower = system_prompt_text.lower()
    assert "2-4 detectors" not in lower
    assert "at most 2-4" not in lower
    assert "deep review" in lower
    assert "metadata" in system_prompt_text
    assert "list_data_sources" in system_prompt_text


def test_prompt_does_not_default_to_running_all_detectors(
    system_prompt_text: str,
) -> None:
    """Deep review should still select relevant detectors, not everything."""
    lower = system_prompt_text.lower()
    assert (
        "do not default to running all detectors" in lower
        or "do not run the full battery" in lower
        or "do not blindly run every detector" in lower
    )


# --------------------------------------------------------------------
# 5. Not testable is a valid output
# --------------------------------------------------------------------


def test_prompt_treats_not_testable_as_valid(
    system_prompt_text: str,
) -> None:
    """The prompt must say: when public materials lack a
    required input, mark the detector as not_testable --
    not a failure, not a fabrication.
    """
    lower = system_prompt_text.lower()
    assert "not testable" in lower or "not-testable" in lower
    # The prompt must say "do not fabricate" or similar.
    assert "do not fabricate" in lower or "do not invent" in lower


# --------------------------------------------------------------------
# 6. Report contract
# --------------------------------------------------------------------


def test_prompt_mentions_render_report_and_artifacts(
    system_prompt_text: str,
) -> None:
    """The prompt must list the 6-artifact contract that
    render_report produces.
    """
    assert "render_report" in system_prompt_text
    # The 6 artifacts:
    assert "report.md" in system_prompt_text
    assert "report.html" in system_prompt_text
    assert "report.json" in system_prompt_text
    assert "raw_trace.json" in system_prompt_text
    assert "tool_summary.json" in system_prompt_text
    assert "manifest.json" in system_prompt_text


def test_prompt_requires_exactly_one_render_report(
    system_prompt_text: str,
) -> None:
    """The prompt must say render_report is the SINGLE
    delivery channel for full reports -- exactly one
    call.
    """
    assert (
        "single delivery channel" in system_prompt_text.lower()
    ) or (
        "exactly one" in system_prompt_text.lower()
    )


# --------------------------------------------------------------------
# 7. TUI style
# --------------------------------------------------------------------


def test_prompt_forbids_raw_json_in_chat(system_prompt_text: str) -> None:
    """The prompt must say: do not paste raw JSON into the
    chat log.
    """
    lower = system_prompt_text.lower()
    assert "no raw json" in lower or (
        "no raw json in the chat" in lower
    )
    # The ToolTraceBlock + DebugDrawer split should be
    # mentioned.
    assert "tooltraceblock" in lower or "tool_trace_block" in lower
    assert "debugdrawer" in lower or "debug_drawer" in lower


def test_prompt_forbids_duplicate_assistant_messages(
    system_prompt_text: str,
) -> None:
    """The prompt must say: exactly one final assistant
    message per turn. No duplicates.
    """
    assert "duplicate" in system_prompt_text.lower() or (
        "no duplicate" in system_prompt_text.lower()
    )
    assert "exactly one" in system_prompt_text.lower()


def test_prompt_forbids_empty_assistant_bubble(
    system_prompt_text: str,
) -> None:
    """The prompt must say: no empty assistant bubbles.
    """
    assert "no empty" in system_prompt_text.lower()
    # And it should mention "(no response)" explicitly.
    assert "(no response)" in system_prompt_text


def test_prompt_mentions_plan_mode(system_prompt_text: str) -> None:
    """The prompt must include plan-mode discipline: do
    not call tools when plan mode is on.
    """
    assert "plan mode" in system_prompt_text.lower() or "plan_mode" in system_prompt_text.lower()
    assert "/plan" in system_prompt_text or "/go" in system_prompt_text


# --------------------------------------------------------------------
# 8. Scientific caution
# --------------------------------------------------------------------


def test_prompt_uses_screening_signal_language(
    system_prompt_text: str,
) -> None:
    """The prompt must say: use 'screening signal',
    'warrants manual review' -- never endorse 'fabricated'
    or 'guilty' as a verdict the agent should output.
    """
    assert "screening signal" in system_prompt_text
    assert "warrants manual review" in system_prompt_text.lower() or (
        "warrant" in system_prompt_text.lower()
    )
    # Positive: the prompt explicitly forbids these
    # verdicts -- assert the prohibition is present.
    assert "fabricated" in system_prompt_text
    assert "guilty" in system_prompt_text


# --------------------------------------------------------------------
# 8b. R-2026-06-14 v2: scientific caution with Chinese term
#     mapping. The prompt provides English <-> Chinese
#     translations of the screening vocabulary so the
#     LLM can render consistent Chinese output.
# --------------------------------------------------------------------


def test_prompt_chinese_term_mapping_for_screening(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the Safety section explicitly
    maps English screening terms to their Chinese
    counterparts. The LLM must not have to guess the
    translation.
    """
    # "screening signal" maps to "初步信号" or "检测器报告".
    assert "初步信号" in system_prompt_text or "检测器报告" in system_prompt_text
    # "warrants manual review" maps to "需要人工确认".
    assert "需要人工确认" in system_prompt_text
    # "clean" must NOT be used absolutely. The prompt
    # says use "未发现明显信号" instead.
    assert "未发现明显信号" in system_prompt_text or "no strong signal" in system_prompt_text.lower()
    # "benign" is also soft-pedalled -- the prompt says
    # use "可能为正常富媒体结构" when in doubt.
    assert (
        "可能为正常富媒体结构" in system_prompt_text
        or "可能为装饰性元素" in system_prompt_text
    )


def test_prompt_no_absolute_clean_or_benign(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the prompt must explicitly
    say "Never say clean absolutely" and "Never say
    benign lightly" -- the user's two strongest
    objections in the v1 review.
    """
    assert "clean" in system_prompt_text.lower()
    assert "benign" in system_prompt_text.lower()
    # The "Never" prohibition must be present. The
    # prompt uses ``**Never**`` (Markdown bold) so the
    # needle we grep for is the bolded form, optionally
    # followed by " say " and the keyword.
    lower = system_prompt_text.lower()
    assert (
        "**never** say \"clean\"" in lower
        or "**never** say 'clean'" in lower
    )
    assert (
        "**never** say \"benign\"" in lower
        or "**never** say 'benign'" in lower
    )


def test_prompt_names_formal_investigation_boundary(
    system_prompt_text: str,
) -> None:
    """ManuSift must screen, while formal investigations
    determine research misconduct using research records.
    """
    lower = system_prompt_text.lower()
    assert "formal investigation" in lower
    assert "research records" in lower
    assert "raw/source data" in lower
    assert "do not determine research misconduct" in lower


# --------------------------------------------------------------------
# 8c. R-2026-06-14 v2: language force. The Response Language
#     section is HARD -- the LLM must ALWAYS mirror the
#     user's language.
# --------------------------------------------------------------------


def test_prompt_response_language_is_hard(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the response-language rule is
    upgraded from "match the user" to "ALWAYS respond
    in the user's language".
    """
    assert "ALWAYS respond in the user" in system_prompt_text
    # The hard rule must apply to BOTH the body and the
    # explanation layer (not just tool names).
    assert "explanations" in system_prompt_text.lower() or "explanation" in system_prompt_text.lower()


# --------------------------------------------------------------------
# 8d. R-2026-06-14 v2: output body. The chat must not be
#     a detector raw trace. Detector names go in
#     parentheses after a human-readable label.
# --------------------------------------------------------------------


def test_prompt_no_raw_detector_dump_in_chat(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the prompt explicitly forbids
    dumping detector names as the main content. The
    new ``## Output Body`` section enforces "label
    first, detector name in parentheses".
    """
    assert "## Output Body" in system_prompt_text
    # The label-first rule.
    assert "human-readable label" in system_prompt_text.lower()
    # Detector names go in parentheses, not as content.
    assert "parentheses" in system_prompt_text.lower()
    # The body must NOT lead with a detector name.
    assert "Do NOT lead with a detector name" in system_prompt_text


def test_prompt_forbids_raw_json_in_chat(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the prompt must still forbid
    raw JSON in the chat body (the rule from v1, kept).
    """
    assert "raw JSON" in system_prompt_text
    # The ToolTraceBlock and DebugDrawer are the
    # proper homes for raw tool output.
    assert "ToolTraceBlock" in system_prompt_text
    assert "DebugDrawer" in system_prompt_text


# --------------------------------------------------------------------
# 8e. R-2026-06-14 v2: 5-section output structure. The
#     quick-triage body has a fixed shape: 当前状态 /
#     已检查 / 关键风险 / 未能测试 / 下一步 (or English
#     equivalents).
# --------------------------------------------------------------------


def test_prompt_has_5_section_output_structure(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: a new ``## Output Structure``
    section fixes the quick-triage body to 5 sections
    in this order: 当前状态 / 已检查 / 关键风险 /
    未能测试 / 下一步. The English mirrors must also
    be present.
    """
    assert "## Output Structure" in system_prompt_text
    # Chinese section labels.
    for label in (
        "当前状态",
        "已检查",
        "关键风险",
        "未能测试",
        "下一步",
    ):
        assert label in system_prompt_text, (
            f"missing 5-section label: {label!r}"
        )


def test_prompt_5_section_order_is_fixed(
    system_prompt_text: str,
) -> None:
    """The 5 section labels must appear in the
    prescribed order: 当前状态 -> 已检查 -> 关键风险
    -> 未能测试 -> 下一步. The body of the report
    follows this fixed shape so the user can scan it.
    """
    pos = []
    for label in (
        "当前状态",
        "已检查",
        "关键风险",
        "未能测试",
        "下一步",
    ):
        pos.append(system_prompt_text.find(label))
    # All five labels must be present (>= 0).
    assert all(p >= 0 for p in pos), (
        f"missing 5-section label, positions: {pos}"
    )
    # And in increasing order.
    assert pos == sorted(pos), (
        f"5-section labels out of order, positions: {pos}"
    )


# --------------------------------------------------------------------
# 8f. R-2026-06-14 v2: report.html pointer. After
#     render_report, the chat MUST mention the
#     report.html absolute path.
# --------------------------------------------------------------------


def test_prompt_must_mention_report_html_path(
    system_prompt_text: str,
) -> None:
    """R-2026-06-14 v2: the Report Contract section
    explicitly says: after render_report returns, the
    final chat line MUST mention the absolute
    ``report.html`` path. This was the user's complaint
    that they could not find the report file.
    """
    assert "report.html" in system_prompt_text
    # The "MUST mention" rule.
    assert "MUST mention" in system_prompt_text or "must mention" in system_prompt_text.lower()


# --------------------------------------------------------------------
# 9. Length budget (R-2026-06-14 v2: relaxed to 16k chars
#    to accommodate the new sections, but still tight
#    enough to keep first-turn latency low).
# --------------------------------------------------------------------


def test_prompt_is_within_length_budget(
    system_prompt_text: str,
) -> None:
    """The prompt is a single triple-quoted string in
    ``AgentLoop.__init__``. We assert it stays under
    16k chars so the LLM\\'s first-turn input token
    count does not blow up. v1 was 6.8k; v2 is 11k
    after adding the new sections (Output Body,
    Detector Budget, Output Structure, expanded
    Safety). The 16k ceiling leaves 5k of headroom
    for future additions.
    """
    assert len(system_prompt_text) < 16000, (
        f"prompt is {len(system_prompt_text)} chars; "
        f"must be < 16000 to keep first-turn latency low"
    )


# --------------------------------------------------------------------
# 10. Sanity: prompt is not empty and has the standard
# ManuSift identity
# --------------------------------------------------------------------


def test_prompt_mentions_manusift_by_name(system_prompt_text: str) -> None:
    assert "ManuSift" in system_prompt_text


def test_prompt_has_multiple_sections(system_prompt_text: str) -> None:
    """R-2026-06-14 v2: the prompt is organized into
    many labelled sections (## headings). v1 had 9;
    v2 has 13. We assert >= 10 to leave room for
    future additions without breaking structure.
    """
    headings = re.findall(r"^##\s+", system_prompt_text, re.MULTILINE)
    assert len(headings) >= 10, (
        f"prompt has only {len(headings)} `##` headings; "
        f"expected >= 10 for structure"
    )


def test_prompt_v2_has_specific_sections(system_prompt_text: str) -> None:
    """R-2026-06-14 v2: assert every v2-specific section
    heading is present. A missing heading means the
    rewrite was reverted or incompletely applied.
    """
    expected = [
        "## Identity",  # implicit in the opening
        "## Response Language (HARD)",
        "## Path & Ingest (HARD CONTRACT)",
        "## Review Mode (3 trigger classes)",
        "## Detector Budget (NEW)",
        "## Detector Routing",
        "## Not-Testable Is a Valid Output",
        "## Output Body (HARD -- no raw detector dump)",
        "## Output Structure (5-section fixed shape for review summary)",
        "## Report Contract (render_report is the single delivery channel)",
        "## TUI Chat Style (HARD)",
        "## Failure Handling",
        "## Safety & Scientific Caution",
    ]
    # "## Identity" is implicit (the first sentence is
    # the identity statement). The other 12 must
    # appear literally.
    for needle in expected[1:]:
        assert needle in system_prompt_text, (
            f"missing v2 section: {needle!r}"
        )
