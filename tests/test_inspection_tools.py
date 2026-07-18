"""Tests for the inspection tools (T2).

T2 adds two read-only tools that
let the LLM agent in
``manusift-chat`` inspect past
detector findings:

  * ``read_finding`` -- look up
    a single finding by id.
  * ``list_findings`` -- list all
    findings for the current
    trace id, optionally
    filtered.

The tools live in
``manusift.tools.inspection``
and are registered as
``manusift.tools`` entry
points (built-in) so the agent
loop auto-discovers them.

The tests cover:

  1. Both tools follow the
     ``Tool`` Protocol.
  2. The input schema is valid
     JSON Schema (required keys,
     types, additionalProperties).
  3. ``read_finding`` returns
     the full finding as a JSON
     string when the id is
     present.
  4. ``read_finding`` returns a
     JSON error object when the
     id is missing.
  5. ``list_findings`` applies
     the detector + severity
     filters.
  6. Both tools are exposed by
     ``iter_registered_tools``.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest


# ---------- 1. Both tools follow the Tool Protocol ----------

def test_read_finding_is_a_tool() -> None:
    """``ReadFindingTool`` must
    implement every member of
    the ``Tool`` Protocol:
    ``name``, ``description()``,
    ``input_schema()``,
    ``execute(input, ctx)``."""
    from manusift.tools import Tool
    from manusift.tools.inspection import ReadFindingTool
    tool = ReadFindingTool()
    assert isinstance(tool, Tool)
    assert tool.name == "read_finding"
    assert isinstance(tool.description(), str)
    assert isinstance(tool.input_schema(), dict)
    # Execute returns a string.
    assert isinstance(
        tool.execute({"finding_id": "x"}, type("Ctx", (), {"trace_id": "t"})()),
        str,
    )


def test_list_findings_is_a_tool() -> None:
    from manusift.tools import Tool
    from manusift.tools.inspection import ListFindingsTool
    tool = ListFindingsTool()
    assert isinstance(tool, Tool)
    assert tool.name == "list_findings"
    assert isinstance(tool.description(), str)
    assert isinstance(tool.input_schema(), dict)


# ---------- 2. Input schema shape ----------

def test_read_finding_input_schema() -> None:
    """``read_finding`` requires a
    ``finding_id`` string."""
    from manusift.tools.inspection import ReadFindingTool
    schema = ReadFindingTool().input_schema()
    assert schema["type"] == "object"
    assert "finding_id" in schema["properties"]
    assert "finding_id" in schema["required"]
    assert schema["properties"]["finding_id"]["type"] == "string"
    # The schema must reject
    # additional properties so
    # the LLM cannot smuggle
    # arbitrary arguments.
    assert schema.get("additionalProperties") is False


def test_list_findings_input_schema() -> None:
    """``list_findings`` accepts
    optional ``detector`` and
    ``severity`` filters."""
    from manusift.tools.inspection import ListFindingsTool
    schema = ListFindingsTool().input_schema()
    assert "detector" in schema["properties"]
    assert "severity" in schema["properties"]
    # severity is an enum.
    sev = schema["properties"]["severity"]
    assert sev.get("enum") == ["low", "medium", "high"]


# ---------- 3. read_finding returns the finding ----------

def test_read_finding_returns_finding_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a findings file
    contains the requested id,
    ``read_finding`` returns the
    full finding as a JSON
    string."""
    # Set up a workspace with a
    # findings.json file.
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-test-1"
    jobs_dir = workspace / trace_id / "output"
    jobs_dir.mkdir(parents=True)
    finding = {
        "finding_id": "abc123def456",
        "detector": "metadata",
        "severity": "high",
        "description": "Author list contains duplicate names.",
        "evidence": "see page 2",
    }
    (jobs_dir / "findings.json").write_text(
        json.dumps([finding]), encoding="utf-8"
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ReadFindingTool
    ctx = ToolContext(trace_id=trace_id)
    out = ReadFindingTool().execute({"finding_id": "abc123def456"}, ctx)
    data = json.loads(out)
    assert data["finding_id"] == "abc123def456"
    assert data["detector"] == "metadata"
    assert data["severity"] == "high"


def test_read_finding_returns_error_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the id is not in the
    findings file, ``read_finding``
    returns a JSON error object
    so the LLM can react."""
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-test-2"
    jobs_dir = workspace / trace_id / "output"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "findings.json").write_text(
        json.dumps([{
            "finding_id": "x",
            "detector": "metadata",
            "severity": "low",
        }]),
        encoding="utf-8",
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ReadFindingTool
    ctx = ToolContext(trace_id=trace_id)
    out = ReadFindingTool().execute({"finding_id": "nope"}, ctx)
    data = json.loads(out)
    assert "error" in data


def test_read_finding_returns_error_when_no_findings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When there is no findings
    file for the trace id, the
    tool must return a JSON
    error rather than crash."""
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ReadFindingTool
    ctx = ToolContext(trace_id="t-missing")
    out = ReadFindingTool().execute({"finding_id": "any"}, ctx)
    data = json.loads(out)
    assert "error" in data


def test_read_finding_rejects_missing_arg() -> None:
    """The LLM might call the tool
    without a finding_id. The
    tool must return a JSON
    error, not raise."""
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ReadFindingTool
    ctx = ToolContext(trace_id="t")
    out = ReadFindingTool().execute({}, ctx)
    data = json.loads(out)
    assert "error" in data


# ---------- 4. list_findings filters ----------

def test_list_findings_returns_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no filters,
    ``list_findings`` returns
    every finding in a compact
    summary list."""
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-list-1"
    jobs_dir = workspace / trace_id / "output"
    jobs_dir.mkdir(parents=True)
    findings = [
        {
            "finding_id": "a",
            "detector": "metadata",
            "severity": "high",
            "description": "d1",
        },
        {
            "finding_id": "b",
            "detector": "image_forensics",
            "severity": "medium",
            "description": "d2",
        },
    ]
    (jobs_dir / "findings.json").write_text(
        json.dumps(findings), encoding="utf-8"
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ListFindingsTool
    ctx = ToolContext(trace_id=trace_id)
    out = ListFindingsTool().execute({}, ctx)
    data = json.loads(out)
    assert data["count"] == 2
    assert len(data["findings"]) == 2


def test_list_findings_filters_by_detector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``detector`` filter
    must restrict the result set
    to the specified detector."""
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-list-2"
    jobs_dir = workspace / trace_id / "output"
    jobs_dir.mkdir(parents=True)
    findings = [
        {
            "finding_id": "a",
            "detector": "metadata",
            "severity": "high",
        },
        {
            "finding_id": "b",
            "detector": "image_forensics",
            "severity": "medium",
        },
    ]
    (jobs_dir / "findings.json").write_text(
        json.dumps(findings), encoding="utf-8"
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ListFindingsTool
    ctx = ToolContext(trace_id=trace_id)
    out = ListFindingsTool().execute(
        {"detector": "metadata"}, ctx
    )
    data = json.loads(out)
    assert data["count"] == 1
    assert data["findings"][0]["finding_id"] == "a"


def test_list_findings_filters_by_severity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-list-3"
    jobs_dir = workspace / trace_id / "output"
    jobs_dir.mkdir(parents=True)
    findings = [
        {
            "finding_id": "a",
            "detector": "metadata",
            "severity": "high",
        },
        {
            "finding_id": "b",
            "detector": "image_forensics",
            "severity": "low",
        },
    ]
    (jobs_dir / "findings.json").write_text(
        json.dumps(findings), encoding="utf-8"
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ListFindingsTool
    ctx = ToolContext(trace_id=trace_id)
    out = ListFindingsTool().execute(
        {"severity": "high"}, ctx
    )
    data = json.loads(out)
    assert data["count"] == 1


def test_list_findings_truncates_long_descriptions() -> None:
    """The summary entry must
    truncate the description to
    ~120 chars so the LLM does
    not blow its context window
    on a 1000-finding paper."""
    from manusift.tools.inspection import _truncate
    assert _truncate("hello", 120) == "hello"
    long = "a" * 200
    out = _truncate(long, 120)
    assert len(out) <= 120
    assert out.endswith("…")


# ---------- 5. Registry exposes both tools ----------

def test_iter_registered_tools_yields_inspection_tools() -> None:
    """Both ``read_finding`` and
    ``list_findings`` must be
    exposed by the tool
    registry so the agent loop
    can surface them to the
    LLM."""
    from manusift.tools import iter_registered_tools
    names = {t.name for t in iter_registered_tools()}
    assert "read_finding" in names
    assert "list_findings" in names


# ---------- 6. Canonical per-job layout ----------

def test_read_finding_canonical_output_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every writer (web, TUI, MCP, ``ingest_from_path``) persists
    findings to ``<workspace>/<trace_id>/output/findings.json``
    (``JobPaths.findings_json``); the inspection tools read the
    same canonical path."""
    from manusift.config import get_settings
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    trace_id = "t-flat-1"
    out_dir = workspace / trace_id / "output"
    out_dir.mkdir(parents=True)
    finding = {
        "finding_id": "flat000abcd1",
        "detector": "image_dup",
        "severity": "medium",
        "description": "Near-duplicate image detected.",
        "evidence": "phash hamming 3",
    }
    (out_dir / "findings.json").write_text(
        json.dumps([finding]), encoding="utf-8"
    )
    from manusift.tools import ToolContext
    from manusift.tools.inspection import ListFindingsTool, ReadFindingTool
    ctx = ToolContext(trace_id=trace_id)
    out = ReadFindingTool().execute({"finding_id": "flat000abcd1"}, ctx)
    data = json.loads(out)
    assert data["finding_id"] == "flat000abcd1"
    listed = json.loads(ListFindingsTool().execute({}, ctx))
    assert listed["count"] == 1


def test_findings_path_points_at_output_dir(
    tmp_path: Path,
) -> None:
    """``_findings_path`` is a single fixed path under the job's
    ``output/`` dir -- no layout fallback."""
    from manusift.tools.inspection import _findings_path
    ws = tmp_path / "ws"
    assert _findings_path(ws, "t") == ws / "t" / "output" / "findings.json"
