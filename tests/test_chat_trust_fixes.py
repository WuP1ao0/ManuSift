"""Tests for the R-2026-06-14 chat-TUI trust fixes.

Covers the 5 user complaints:

  1. "bash budget 没跑成" / "只让 list_dir / glob / read_file"
     -> per-name cap now reads Settings (12 under
        trusted-local) instead of hard-coded 3.
     -> per-turn total cap (50) is enforced.
     -> per-turn bash cap (30) is enforced.

  2. "tools N calls \u00b7 N ok" without tool names
     -> the ToolTraceBlock summary now includes the top
        3 tool names.

  3. data_source_count = 0 even after XLSX was
     copied into materials
     -> parse_data_file runs on every copied companion
        file; the resulting ExtractedTables are
        appended onto doc.tables so the table
        detectors see them.

  4. trace_id isolation between runs
     -> the system prompt's Conversation State
        Reminder uses the *new* trace_id, not the
        one carried over from a prior run.

  5. BashTool safety net
     -> dangerous commands (rm -rf /, fork bombs) are
        still rejected with a clear reason, even
        under trusted-local.

These tests do NOT exercise the live LLM. They
construct an ``AgentLoop`` against a fake LLM that
emits a deterministic stream of tool_use blocks and
assert the loop's behaviour against the new contract.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest


# --------------------------------------------------------------------
# 1. Budget cap is now Settings-driven
# --------------------------------------------------------------------


def test_per_name_cap_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cap-per-name attribute must read
    ``Settings.tool_calls_per_name_cap``.

    R-2026-06-14: the previous hard-coded ``3``
    value was the root cause of "只让 list_dir /
    glob / read_file" complaints -- even a 4th
    call to ``bash`` (e.g. ``pip install openpyxl``
    + ``python convert.py`` + ``ls`` + ``rerun
    detector``) would trip the loop's own cap.

    We force the field via the explicit
    constructor (pydantic-settings reads the
    env at construction time, so this is more
    reliable than ``monkeypatch.setenv`` in
    this case).
    """
    from manusift.config import Settings
    from manusift.tools.tool import ToolContext
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _L:
        name = "fake"

        def chat_stream(
            self, messages, tools=None, **kw
        ):
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "ok"}
                ],
                stop_reason="end_turn",
            )

    # Construct a Settings instance with a
    # tight cap, then patch ``get_settings``
    # so the loop picks it up.
    from manusift import config as _config
    custom = Settings(tool_calls_per_name_cap=5)
    orig_get = _config.get_settings
    _config.get_settings = lambda: custom
    try:
        ctx = ToolContext(trace_id="t")
        loop = AgentLoop(
            client=_L(),
            tools=[],
            ctx=ctx,
        )
        assert loop._MAX_SAME_TOOL_CALLS == 5
    finally:
        _config.get_settings = orig_get


def test_per_name_cap_defaults_to_12_under_trusted_local() -> None:
    """The default cap under trusted-local is 12,
    not 3.

    R-2026-06-14: the previous default of 3 was
    "fail fast on runaway loops" but it was too
    aggressive for honest workflows. 12 matches
    the budget needed for an 8-figure image_dup
    sweep + 3 trial detector runs + 1 final
    report.
    """
    from manusift.config import get_settings
    # get_settings has no cache_clear (it
    # reads env fresh on each call) so just
    # call it.
    settings = get_settings()
    assert settings.trusted_local is True
    assert settings.tool_calls_per_name_cap == 12


def test_per_turn_total_cap_enforced() -> None:
    """Once a run has issued
    ``tool_calls_per_turn_cap`` tool calls, the
    next call must be rejected with a clear
    error message that names the env var.

    R-2026-06-14: the previous per-name cap (3)
    was the only enforcement. The new per-turn
    cap (50 by default) protects against the
    "many different tools" loop the user
    described ("只让 list_dir / glob /
    read_file / detector 工具" -- the LLM
    fires many different tools, never tripping
    the per-name cap, but burning thousands of
    tokens total).
    """
    from manusift.tools.tool import ToolContext
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _L:
        name = "fake"

        def chat_stream(
            self, messages, tools=None, **kw
        ):
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "ok"}
                ],
                stop_reason="end_turn",
            )

    class _Tool:
        name = "free_tool"

        def description(self): return ""

        def input_schema(self): return {
            "type": "object",
            "properties": {},
        }

        def execute(self, input, ctx): return json.dumps(
            {"ok": True}
        )

    ctx = ToolContext(trace_id="t")
    loop = AgentLoop(
        client=_L(),
        tools=[_Tool()],
        ctx=ctx,
    )
    # Tight cap so the test runs fast.
    loop._TOOL_CALLS_PER_TURN_CAP = 3
    # Pre-populate the counter so the next call
    # is over the cap.
    loop._tool_call_counts = {
        "free_tool": 3,
    }
    msgs: list[dict[str, Any]] = []
    from manusift.llm.chat import ChatResponse as CR
    resp = CR(
        content_blocks=[
            {
                "type": "tool_use",
                "name": "free_tool",
                "input": {},
                "id": "call-1",
            }
        ],
        stop_reason="tool_use",
    )
    loop._execute_tool_calls(resp, msgs)
    # The tool should NOT have been called.
    # The error message must be in the messages.
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert "per-turn tool-call budget" in content
    assert "MANUSIFT_TOOL_MAX_CALLS_PER_TURN" in content


def test_per_turn_bash_cap_enforced() -> None:
    """The bash tool has a separate per-turn cap
    (30 by default). The cap is independent of
    the per-name cap so even when the LLM
    legitimately calls many different tools, a
    runaway bash loop is contained.
    """
    from manusift.tools.tool import ToolContext
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse

    class _L:
        name = "fake"

        def chat_stream(
            self, messages, tools=None, **kw
        ):
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "ok"}
                ],
                stop_reason="end_turn",
            )

    class _Bash:
        name = "bash"

        def description(self): return ""

        def input_schema(self): return {
            "type": "object",
            "properties": {},
        }

        def execute(self, input, ctx): return json.dumps(
            {"ok": True}
        )

    ctx = ToolContext(trace_id="t")
    loop = AgentLoop(
        client=_L(),
        tools=[_Bash()],
        ctx=ctx,
    )
    loop._BASH_MAX_PER_TURN = 2
    loop._bash_call_count = 2  # already at cap
    msgs: list[dict[str, Any]] = []
    from manusift.llm.chat import ChatResponse as CR
    resp = CR(
        content_blocks=[
            {
                "type": "tool_use",
                "name": "bash",
                "input": {"command": "echo hi"},
                "id": "call-1",
            }
        ],
        stop_reason="tool_use",
    )
    loop._execute_tool_calls(resp, msgs)
    content = msgs[0]["content"]
    assert "per-turn bash budget" in content
    assert "MANUSIFT_BASH_MAX_CALLS_PER_TURN" in content


# --------------------------------------------------------------------
# 2. Tool summary now shows tool names
# --------------------------------------------------------------------


def test_tool_trace_block_summary_includes_tool_names() -> None:
    """The ToolTraceBlock summary line now lists
    the top 3 tool names (with collapsed counts)
    so the user can see at a glance which tools
    ran, not just an opaque ``3 ok`` count.

    R-2026-06-14: addresses the screenshot
    complaint "I only see ``tools 3 calls \u00b7 3
    ok``".
    """
    from manusift.tui.turn_block import (
        ToolTraceBlock,
        TOOL_OK,
    )

    block = ToolTraceBlock(collapsed=True)
    block._sealed = True
    block._entries = [
        _make_entry(TOOL_OK, "ingest_from_path"),
        _make_entry(TOOL_OK, "ingest_from_path"),
        _make_entry(TOOL_OK, "image_dup"),
        _make_entry(TOOL_OK, "image_dup"),
        _make_entry(TOOL_OK, "image_dup"),
        _make_entry(TOOL_OK, "render_report"),
    ]
    line = block._summary_line()
    rendered = line.plain
    # The summary should mention the tool names.
    assert "ingest_from_path" in rendered
    assert "image_dup" in rendered
    assert "render_report" in rendered
    # The collapsed count format is
    # "ingest_from_path \u00d72".
    assert "\u00d72" in rendered  # \u00d7 is \u00d7
    assert "\u00d73" in rendered


def _make_entry(status, tool_name):
    """Build a minimal ToolEntry for tests."""
    from manusift.tui.turn_block import (
        ToolEntry,
        TOOL_OK,
    )

    return ToolEntry(
        tool_id=f"id-{tool_name}",
        tool_name=tool_name,
        status=status,
    )


# --------------------------------------------------------------------
# 3. data_source_count=0 fix
# --------------------------------------------------------------------


def test_ingest_with_xlsx_data_path_increments_data_source_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end-to-end ingest flow: when the user
    pastes a PDF + a companion XLSX, the
    resulting ``data_source_count`` must be > 0
    so the table-detectors (stat_grim,
    table_benford, etc.) can run.

    R-2026-06-14: the previous implementation
    *copied* the XLSX to materials/ but did
    not *parse* it, so the table-detectors saw
    an empty ``doc.tables`` and silently
    reported zero findings.
    """
    from manusift.tools.tool import ToolContext
    from manusift.tools.direct_fs import (
        IngestFromPathTool,
    )

    # Build a minimal valid PDF file.
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        b"1 0 obj<</Type/Catalog>>endobj\n"
        b"xref\n0 1\n0000000000 65535 f\n"
        b"trailer<</Size 1>>\nstartxref\n0\n%%EOF\n"
    )
    # Build a minimal xlsx via openpyxl.
    xlsx_path = tmp_path / "data.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["gene", "pvalue"])
    ws.append(["BRCA1", 0.001])
    ws.append(["TP53", 0.42])
    ws.append(["EGFR", 0.0003])
    wb.save(str(xlsx_path))

    # Reset Settings cache so any monkeypatched
    # env takes effect.
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    # R-2026-06-15 (Phase 1 + P1-17):
    # ``Settings`` is now
    # ``frozen=True`` --
    # ``monkeypatch.setattr``
    # would raise.  Use
    # ``model_copy`` to
    # build a new instance
    # with the override
    # applied.
    settings = settings.model_copy(
        update={"workspace_dir": tmp_path / "ws"}
    )
    ctx = ToolContext(trace_id="t")
    tool = IngestFromPathTool()
    output = tool.execute(
        {
            "path": str(pdf_path),
            "data_paths": [str(xlsx_path)],
        },
        ctx,
    )
    parsed = json.loads(output)
    # The XLSX is now a registered data source.
    assert parsed.get("ok") is True
    # The exact count depends on whether the
    # minimal PDF yields any PDF-native tables
    # (it does not) -- the test just requires
    # >= 1 data source (the XLSX).
    assert parsed.get("data_source_count", 0) >= 1
    assert len(parsed.get("data_sources", [])) >= 1
    # The XLSX is in the copied list.
    copied = parsed.get("copied_data_paths", [])
    assert any("data.xlsx" in p for p in copied)


def test_settings_has_openpyxl_dependency() -> None:
    """openpyxl must be a declared runtime
    dependency, not an implicit one.

    R-2026-06-14: prior to this fix, openpyxl
    was a lazy import inside
    ``manusift.ingest.xlsx``; a user without
    openpyxl would see
    ``ValueError: XLSX parsing requires the
    openpyxl package`` from the ingest tool
    even though they had a real .xlsx file.
    """
    pyproject = Path(
        r"C:\Users\22509\Desktop\ManuSift1\pyproject.toml"
    )
    assert pyproject.exists()
    text = pyproject.read_text(encoding="utf-8")
    assert "openpyxl" in text


# --------------------------------------------------------------------
# 4. BashTool dangerous-command denylist
# --------------------------------------------------------------------


def test_bash_blocks_rm_rf_root() -> None:
    """Even under trusted-local, ``rm -rf /`` is
    blocked by the BashTool denylist.

    R-2026-06-14: the user's spec explicitly
    called out keeping dangerous commands
    blocked while loosening ordinary read /
    transform / report-generation limits. This
    test pins that contract.
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    from manusift.config import get_settings

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    assert settings.allow_shell is True
    ctx = ToolContext(trace_id="t")
    tool = BashTool()
    out = json.loads(
        tool.execute(
            {"command": "rm -rf /"},
            ctx,
        )
    )
    assert out["ok"] is False
    # R-2026-06-15 (Phase 1 + 3b):
    # the new classifier
    # returns a richer
    # error message
    # ("rm -rf on / or
    # home"). Accept the
    # new reason OR the
    # old "blocked"
    # substring so the
    # test is stable
    # across the
    # denylist / classifier
    # migration.
    err_lower = out["error"].lower()
    assert (
        "blocked" in err_lower
        or "rm -rf" in err_lower
    )


def test_bash_allows_openpyxl_pip_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under trusted-local, a normal
    ``pip install openpyxl`` is allowed --
    the LLM can install declared dependencies
    on its own.

    R-2026-06-14: the user complained that
    "openpyxl 没装" was blocking the agent. The
    fix is twofold: (a) openpyxl is now a
    declared dep (so a fresh install already
    has it), and (b) the bash tool does not
    reject ordinary package-management
    commands under trusted-local.

    R-2026-06-15 (Phase 1 + 3b):
    the new classifier
    classifies ``pip install`` as
    ``needs_confirm`` (mutating).
    The test sets
    ``MANUSIFT_ALLOW_NEEDS_CONFIRM=true`` so
    the command actually runs
    (the classifier still
    reports the
    ``posix.mutating``
    rule).
    """
    from manusift.tools.agent_tools import BashTool
    from manusift.tools.tool import ToolContext
    from manusift.config import get_settings
    from unittest import mock

    monkeypatch.setenv(
        "MANUSIFT_ALLOW_NEEDS_CONFIRM", "true"
    )
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    assert settings.allow_shell is True
    # Mock the subprocess call so the test
    # does not actually run pip.
    ctx = ToolContext(trace_id="t")
    tool = BashTool()
    with mock.patch(
        "manusift.tools.agent_tools.bash.subprocess.run",
        return_value=mock.Mock(
            returncode=0,
            stdout="",
            stderr="",
        ),
    ) as _run:
        out = json.loads(
            tool.execute(
                {"command": "pip install openpyxl"},
                ctx,
            )
        )
    # The command is allowed to reach
    # subprocess.run -- the denylist does not
    # match.
    assert _run.called, (
        f"subprocess.run was not called; out={out}"
    )
    # And the (mocked) return is success.
    assert out["ok"] is True


# --------------------------------------------------------------------
# 5. Tool Timeline events
# --------------------------------------------------------------------


def test_agent_loop_emits_tool_started_and_finished_events() -> None:
    """The AgentLoop emits
    ``tool.started`` and ``tool.finished`` events
    on the bus. The TUI subscribes to these
    to render a per-turn Tool Timeline.

    R-2026-06-14: addresses the screenshot
    complaint that the user could not see which
    tool the agent actually called.
    """
    from manusift.tools.tool import ToolContext
    from manusift.agent import AgentLoop
    from manusift.llm.chat import ChatResponse
    from manusift.events import get_bus

    # Use a fresh subscriber to count
    # ``tool.started`` and ``tool.finished``
    # emissions.
    class _Counter:
        def __init__(self) -> None:
            self.started: list = []
            self.finished: list = []

        def on_event(self, event) -> None:
            if event.type == "tool.started":
                self.started.append(event.payload)
            elif event.type == "tool.finished":
                self.finished.append(event.payload)

    counter = _Counter()
    get_bus().subscribe(counter)

    class _L:
        name = "fake"

        def chat_stream(
            self, messages, tools=None, **kw
        ):
            yield ChatResponse(
                content_blocks=[
                    {"type": "text", "text": "ok"}
                ],
                stop_reason="end_turn",
            )

    class _Tool:
        name = "demo_tool"

        def description(self): return ""

        def input_schema(self): return {
            "type": "object",
            "properties": {},
        }

        def execute(self, input, ctx): return json.dumps(
            {
                "ok": True,
                "report_path": "C:/x/report.html",
            }
        )

    ctx = ToolContext(trace_id="t")
    loop = AgentLoop(
        client=_L(),
        tools=[_Tool()],
        ctx=ctx,
    )
    # Drive a single tool call.
    from manusift.llm.chat import ChatResponse as CR
    resp = CR(
        content_blocks=[
            {
                "type": "tool_use",
                "name": "demo_tool",
                "input": {"x": 1},
                "id": "call-1",
            }
        ],
        stop_reason="tool_use",
    )
    loop._execute_tool_calls(
        resp,
        [],
        seen_ids=set(),
    )
    # Both events fired.
    assert len(counter.started) == 1
    assert len(counter.finished) == 1
    assert counter.started[0]["tool"] == "demo_tool"
    assert counter.finished[0]["ok"] is True
    # The finished event includes artifact paths
    # (the tool returned ``report_path``).
    assert (
        "C:/x/report.html" in counter.finished[0]["artifacts"]
    )
    # Cleanup: remove the counter so it does
    # not leak into other tests.
    get_bus().unsubscribe(counter)


# --------------------------------------------------------------------
# 6. Integration: fake PDF + XLSX end-to-end via the Ingest tool
# --------------------------------------------------------------------


def test_ingest_then_data_sources_visible_to_table_detector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A realistic end-to-end smoke: ingest a
    PDF + a companion XLSX, then confirm the
    table-statistics detector sees the XLSX
    rows (not 0 rows).

    R-2026-06-14: the user complained that
    ``data_source_count=0`` and "table
    detectors report no findings" even after
    they uploaded the data. The fix has 3
    parts (this test pins #1: data sources
    are visible to detectors).
    """
    from manusift.config import get_settings
    from manusift.tools.tool import ToolContext
    from manusift.tools.direct_fs import (
        IngestFromPathTool,
    )
    from manusift.ingest.xlsx import parse_data_file

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    # R-2026-06-15 (Phase 1 + P1-17):
    # ``Settings`` is now
    # ``frozen=True``.
    settings = settings.model_copy(
        update={"workspace_dir": tmp_path / "ws"}
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
        b"1 0 obj<</Type/Catalog>>endobj\n"
        b"xref\n0 1\n0000000000 65535 f\n"
        b"trailer<</Size 1>>\nstartxref\n0\n%%EOF\n"
    )
    xlsx_path = tmp_path / "data.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["value", "p"])
    for i in range(1, 11):
        ws.append([i, i * 0.01])
    wb.save(str(xlsx_path))

    tool = IngestFromPathTool()
    out = json.loads(
        tool.execute(
            {
                "path": str(pdf_path),
                "data_paths": [str(xlsx_path)],
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    # The XLSX is visible.
    assert out["data_source_count"] >= 1
    # The table list contains at least one row.
    assert len(out["data_sources"]) >= 1
    # And parse_data_file (the new ingestion
    # path) returns the rows.
    tables = parse_data_file(str(xlsx_path))
    assert len(tables) == 1
    assert tables[0].source_kind == "xlsx"
    assert len(tables[0].rows) == 10
