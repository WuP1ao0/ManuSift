"""Tests for the LLM-facing tool descriptions and system prompt
(加固 A + B + C).

The end-to-end audit found
three weak spots in the
chain from "user asks a
question" to "LLM picks
the right tool":

  A. The system prompt only
     listed tool names; the
     LLM had to read the
     full description of
     every tool to decide
     which to call. Now the
     prompt includes a
     one-line cheat sheet
     per tool.

  B. Three detector tools
     had very short
     docstrings (53-56
     chars). Now they are
     700+ chars each, with
     a proper
     "what / when / how
     / output" shape.

  C. ``list_findings``'s
     detector-filter list
     was hard-coded to 5
     names while the
     project actually ships
     31. Now it sources the
     names from
     ``iter_registered_detectors()``
     so the description
     stays in sync with
     the registry.

The tests below pin each
of the three behaviours.
"""
from __future__ import annotations

import pytest


# ---------- A. system prompt (workflow tools) ----------

# R-2026-06-14: workflow-defining tools that the system
# prompt must name explicitly. The full tool schema is
# auto-injected by the SDK (``tools=`` arg), but the
# prompt documents the user-facing workflow by
# referencing these tool names in its policy sections
# (Path & Ingest, Source Data, Report Contract).
WORKFLOW_TOOLS_NAMES = frozenset({
    "ingest_from_path",
    "list_dir",
    "list_data_sources",
    "read_data_source",
    "render_report",
})


def test_default_system_prompt_names_workflow_tools() -> None:
    """R-2026-06-14: the new system prompt does NOT list
    every registered tool in a cheat sheet (that bloats
    first-turn latency and duplicates the registry's
    auto-injected schema). It DOES name the five
    workflow-defining tools that anchor the
    user-perceived contract: ingest_from_path, list_dir,
    list_data_sources, read_data_source, render_report.
    Other tools (detectors, knowledge_base, etc.) are
    discovered through the SDK's ``tools=`` schema.
    """
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    loop = AgentLoop(
        client=MockLLM(),
        tools=list(iter_registered_tools()),
        ctx=ToolContext(trace_id="t1"),
    )
    sp = loop._system_prompt
    missing = sorted(
        name for name in WORKFLOW_TOOLS_NAMES if name not in sp
    )
    assert not missing, (
        f"workflow tools missing from system prompt: {missing}"
    )


def test_workflow_tools_have_purpose_in_prompt() -> None:
    """R-2026-06-14: each workflow-defining tool
    mentioned in the prompt must be accompanied by a
    purpose statement (the surrounding prose must give
    the LLM enough context to know WHY to call it).
    """
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    loop = AgentLoop(
        client=MockLLM(),
        tools=list(iter_registered_tools()),
        ctx=ToolContext(trace_id="t1"),
    )
    sp = loop._system_prompt
    for name in WORKFLOW_TOOLS_NAMES:
        idx = sp.find(name)
        assert idx >= 0, (
            f"workflow tool {name!r} missing from prompt"
        )
        window = sp[max(0, idx - 20) : idx + 80]
        assert len(window.strip()) >= 30, (
            f"workflow tool {name!r} mentioned but with "
            f"insufficient context: {window!r}"
        )


def test_render_report_is_html_first() -> None:
    """R-2026-06-14: the render_report workflow tool is
    the single delivery channel for full reports. The
    prompt must mention it AND frame the deliverable as
    HTML (the canonical artefact), not the older
    HTML/PDF wording.
    """
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    loop = AgentLoop(
        client=MockLLM(),
        tools=list(iter_registered_tools()),
        ctx=ToolContext(trace_id="t1"),
    )
    sp = loop._system_prompt
    assert "render_report" in sp
    assert "report.html" in sp
    assert "HTML/PDF" not in sp


def test_system_prompt_mentions_data_paths_for_source_data() -> None:
    """R-2026-06-14: when the user gives a PDF path PLUS
    companion source data, the LLM must pass
    ``data_paths`` to ``ingest_from_path`` so the data
    attaches to the same trace_id. The prompt must
    document this contract.
    """
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    loop = AgentLoop(
        client=MockLLM(),
        tools=list(iter_registered_tools()),
        ctx=ToolContext(trace_id="t1"),
    )
    sp = loop._system_prompt
    assert "data_paths" in sp
    lower = sp.lower()
    assert (
        "companion data" in lower
        or "source data" in lower
        or "supplementary" in lower
    )


def test_custom_system_prompt_unchanged() -> None:
    """A custom ``system_prompt`` overrides the default;
    the user's value is used verbatim."""
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    custom = "You are a custom assistant."
    loop = AgentLoop(
        client=MockLLM(),
        tools=list(iter_registered_tools()),
        ctx=ToolContext(trace_id="t1"),
        system_prompt=custom,
    )
    assert loop._system_prompt == custom


# ---------- B. detector descriptions are ≥ 100 chars ----------


def test_detector_tool_descriptions_are_substantive() -> None:
    """Every detector tool's
    ``description()`` is at
    least 100 chars. A
    short description
    makes the LLM less
    likely to choose the
    tool because it does
    not learn what the
    tool does from the
    short summary alone.
    """
    from manusift.tools import iter_registered_tools
    short: list[tuple[str, int]] = []
    for t in iter_registered_tools():
        d = t.description()
        if len(d) < 100:
            short.append((t.name, len(d)))
    assert not short, (
        f"these tools have < 100-char "
        f"descriptions: {short}"
    )


def test_image_forensics_description_is_substantive() -> None:
    """Regression: the
    ``image_forensics``
    tool used to have a
    56-char description.
    """
    from manusift.tools import iter_registered_tools
    tool = next(
        t for t in iter_registered_tools()
        if t.name == "image_forensics"
    )
    d = tool.description()
    assert len(d) >= 100
    # The description
    # should mention the
    # two key techniques
    # so the LLM knows
    # when to call it.
    assert "ELA" in d or "Error Level" in d
    assert "copy-move" in d.lower() or "copy move" in d.lower()


def test_text_patterns_description_is_substantive() -> None:
    """Regression: the
    ``text_patterns`` tool
    used to have a
    53-char description.
    """
    from manusift.tools import iter_registered_tools
    tool = next(
        t for t in iter_registered_tools()
        if t.name == "text_patterns"
    )
    d = tool.description()
    assert len(d) >= 100
    # The description
    # should mention
    # "dispatcher" so the
    # LLM knows the tool
    # is a facade for
    # several text-level
    # checks.
    assert "dispatcher" in d.lower() or "check" in d.lower()


def test_image_dup_description_is_substantive() -> None:
    """Regression: the
    ``image_dup`` tool used
    to have a 244-char
    description, now it
    is 700+.
    """
    from manusift.tools import iter_registered_tools
    tool = next(
        t for t in iter_registered_tools()
        if t.name == "image_dup"
    )
    d = tool.description()
    assert len(d) >= 300
    # Mentions the
    # Hamming + pHash
    # technique so the
    # LLM knows when to
    # call it.
    assert "hamming" in d.lower() or "phash" in d.lower()


# ---------- C. list_findings filter is dynamic ----------


def test_list_findings_descriptions_match_canonical_registry() -> None:
    """The
    ``list_findings`` tool
    description includes
    the canonical
    detector names from
    ``detector_names()``,
    not the old
    hard-coded list of 5.
    """
    from manusift.tools.inspection import (
        ListFindingsTool,
    )
    from manusift.detectors import detector_names
    tool = ListFindingsTool()
    d = tool.description()
    # The first 8
    # canonical names
    # appear in the
    # description.
    for n in detector_names()[:8]:
        assert f"'{n}'" in d, (
            f"canonical detector {n!r} missing "
            f"from list_findings description"
        )


def test_list_findings_input_schema_uses_canonical_names() -> None:
    """The
    ``input_schema()``
    field description for
    ``detector`` lists
    all 31 canonical
    detector names, not
    the old hard-coded 5.
    """
    from manusift.tools.inspection import (
        ListFindingsTool,
    )
    from manusift.detectors import detector_names
    tool = ListFindingsTool()
    schema = tool.input_schema()
    desc = schema["properties"]["detector"]["description"]
    for n in detector_names():
        assert n in desc, (
            f"detector {n!r} missing from "
            f"list_findings input_schema.detector"
        )


def test_list_findings_filter_does_not_use_strict_enum() -> None:
    """The
    ``input_schema()``
    ``detector`` field is
    a free ``string``,
    not a strict ``enum``.
    A strict enum would
    break older SDK
    schemas that limit
    enum cardinality; the
    LLM sees the full
    list in the
    description.
    """
    from manusift.tools.inspection import (
        ListFindingsTool,
    )
    tool = ListFindingsTool()
    schema = tool.input_schema()
    assert "enum" not in schema["properties"]["detector"]
    assert (
        schema["properties"]["detector"]["type"]
        == "string"
    )


# ---------- D. end-to-end: the cheat sheet + descriptions work together ----------


def test_every_workflow_tool_named_in_system_prompt() -> None:
    """R-2026-06-14: the workflow-defining tools must be
    named in the system prompt so the LLM has free
    discovery of the per-turn contract. Detectors and
    other non-workflow tools are discovered via the
    SDK's auto-injected ``tools=`` schema and are NOT
    required to be named in the prompt.
    """
    from manusift.tools import iter_registered_tools
    from manusift.tools import ToolContext
    from manusift.llm.client import MockLLM
    from manusift.agent import AgentLoop
    tools = list(iter_registered_tools())
    loop = AgentLoop(
        client=MockLLM(),
        tools=tools,
        ctx=ToolContext(trace_id="t1"),
    )
    sp = loop._system_prompt
    missing = [
        name for name in WORKFLOW_TOOLS_NAMES
        if name not in sp
    ]
    assert not missing, (
        f"workflow tools missing from system prompt: {missing}"
    )


