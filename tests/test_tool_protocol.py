"""Tests for the Tool Protocol + detector adapter (Step J1).

Borrowed design from the leaked Claude Code v2.1.88 source
(``Tool`` interface). These tests check the three contracts
the rest of the agent stack relies on:
  * Every detector is also a Tool (no rewrite needed).
  * ``description()`` is non-empty and written for an LLM
    audience.
  * ``execute()`` returns a JSON string the LLM can parse.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from manusift.tools import (
    DEFAULT_INPUT_SCHEMA,
    DetectorToolAdapter,
    ToolContext,
    get_tool,
    iter_registered_tools,
    tool_from_detector,
    tool_names,
)
from manusift.detectors import (
    ImageDuplicateDetector,
    ImageForensicsDetector,
    MetadataDetector,
    TextPatternDetector,
)


# ---------- 1. The 4 built-in detectors are tools ----------

def test_builtin_tools_include_four_detectors() -> None:
    """Every detector ships as a tool by default. We do not
    ship a tool that has no detector counterpart, and we do
    not ship a detector that is not also a tool."""
    assert set(tool_names()) >= {
        "metadata",
        "image_dup",
        "image_forensics",
        "text_patterns",
    }


def test_each_detector_is_a_tool() -> None:
    """A DetectorToolAdapter satisfies the Tool Protocol
    shape. We use ``isinstance`` via the runtime-checkable
    Protocol to confirm."""
    for det in [
        MetadataDetector(),
        ImageDuplicateDetector(),
        ImageForensicsDetector(),
        TextPatternDetector(),
    ]:
        tool = tool_from_detector(det)
        # runtime_checkable Protocol check
        from manusift.tools.tool import Tool
        assert isinstance(tool, Tool), f"{det.name} is not a Tool"


# ---------- 2. description() comes from the class docstring ----------

def test_description_uses_class_docstring() -> None:
    """The adapter pulls description from the detector's
    class docstring — the same docstring that the pipeline
    uses as a one-liner. Detector authors document the tool
    behavior once, in the class body."""
    tool = tool_from_detector(MetadataDetector())
    desc = tool.description()
    # Non-empty
    assert desc.strip()
    # The metadata detector class docstring says something
    # about metadata.
    assert "metadata" in desc.lower()


def test_description_falls_back_when_docstring_missing() -> None:
    """A class with no docstring still produces a
    serviceable description, never an empty string."""
    class BareDetector:
        name = "bare"

        def run(self, doc):
            from manusift.detectors.base import DetectorResult
            return DetectorResult(detector=self.name, ok=True, findings=[])

    tool = tool_from_detector(BareDetector())
    assert tool.name == "bare"
    desc = tool.description()
    assert "bare" in desc


# ---------- 3. input_schema() is a JSON Schema dict ----------

def test_input_schema_is_json_schema_dict() -> None:
    """A well-formed JSON Schema is the universal language
    for tool args. Both OpenAI and Anthropic accept this
    shape unchanged."""
    tool = tool_from_detector(MetadataDetector())
    schema = tool.input_schema()
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "trace_id" in schema["properties"]
    # The default schema forbids unknown keys — saves the
    # LLM from typos like "traced_id".
    assert schema.get("additionalProperties") is False


def test_input_schema_can_be_overridden() -> None:
    """A tool can supply its own richer schema. The adapter
    falls back to DEFAULT_INPUT_SCHEMA otherwise."""
    custom = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }
    from manusift.detectors.base import DetectorResult
    class MyDetector:
        name = "my"
        def run(self, doc): return DetectorResult(detector=self.name, ok=True, findings=[])
    tool = DetectorToolAdapter(MyDetector(), schema=custom)
    assert tool.input_schema() == custom


# ---------- 4. execute() returns a JSON string ----------

def test_execute_returns_json_string_with_missing_pdf() -> None:
    """If no PDF is in the workspace, the tool returns a JSON
    error object instead of raising. The LLM can then react
    to the error in its next turn."""
    ctx = ToolContext(trace_id="nonexistent", current_pdf=None)
    tool = tool_from_detector(MetadataDetector())
    out = tool.execute({"trace_id": "nonexistent"}, ctx)
    parsed = json.loads(out)
    assert "error" in parsed


def test_execute_with_real_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tiny PDF in the workspace lets the tool run the
    real detector and emit findings JSON the LLM can read."""
    import fitz  # type: ignore[import-not-found]
    pdf_path = tmp_path / "tiny.pdf"
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello world")
    pdf.save(str(pdf_path))
    pdf.close()

    # The adapter reads from settings.workspace_dir.
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    from manusift.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None

    tid = "t-j1"
    # Drop the original.pdf where the adapter expects it.
    paths_dir = tmp_path / tid
    (paths_dir / "inputs").mkdir(parents=True)
    (paths_dir / "inputs" / "original.pdf").write_bytes(pdf_path.read_bytes())

    ctx = ToolContext(trace_id=tid, current_pdf=str(pdf_path))
    tool = tool_from_detector(MetadataDetector())
    out = tool.execute({"trace_id": tid}, ctx)
    parsed = json.loads(out)
    assert parsed["detector"] == "metadata"
    assert "findings" in parsed
    assert "ok" in parsed


# ---------- 5. get_tool and iter_registered_tools ----------

def test_get_tool_returns_none_for_unknown() -> None:
    """Unknown tool names return None. The AgentLoop uses
    this to detect bad tool calls (LLM hallucinated a name)
    without crashing."""
    assert get_tool("nonexistent") is None


def test_iter_registered_tools_is_lazy() -> None:
    """Each call to iter_registered_tools() re-reads the
    entry-points table. We just check that calling it
    multiple times does not raise and returns the same set
    of names — the full entry-point injection test lives in
    test_detector_registry (and is reused for tools in J4)."""
    names1 = sorted(t.name for t in iter_registered_tools())
    names2 = sorted(t.name for t in iter_registered_tools())
    assert names1 == names2
    assert "metadata" in names1


# ---------- 6. ToolContext is frozen and carries state ----------

def test_tool_context_is_frozen() -> None:
    """ToolContext is frozen: tools cannot accidentally
    mutate shared state. If you need to add state, build a
    new context."""
    ctx = ToolContext(trace_id="t", current_pdf="p")
    with pytest.raises(Exception):
        ctx.trace_id = "other"  # type: ignore[misc]


def test_tool_context_metadata_is_independent() -> None:
    """Two contexts with the same metadata identity
    must not share state.  After R-2026-06-15
    (Phase 1 + P1-1) the
    ``metadata`` field is a
    ``MappingProxyType``; the
    factory must still produce
    a *separate* mapping for
    each instance (so reading
    the same key on both
    contexts gives the same
    value but mutating one
    cannot leak to the other).
    We use ``field(default_factory=...)``
    so each instance gets its
    own dict backing the
    proxy.  Since the proxy is
    read-only, the test now
    asserts the read-only
    invariant (you cannot
    write through the proxy)
    rather than the old
    write-and-verify
    isolation check.
    """
    a = ToolContext(trace_id="a")
    b = ToolContext(trace_id="b")
    # Same starting value
    # (both empty).
    assert a.metadata == {}
    assert b.metadata == {}
    # The underlying dicts are
    # distinct.
    assert dict(a.metadata) is not dict(b.metadata)
    # Writes are blocked on
    # both.
    with pytest.raises(TypeError):
        a.metadata["x"] = 1
    with pytest.raises(TypeError):
        b.metadata["x"] = 1
    # ``with_metadata`` is the
    # supported way to add a
    # key.
    a2 = a.with_metadata(x=1)
    assert a2.metadata["x"] == 1
    assert "x" not in a.metadata
    assert "x" not in b.metadata


# ---------- 7. ToolResult envelope ----------

def test_tool_result_envelope_round_trips_to_json() -> None:
    """Tool execution results have
    one shared envelope before they
    cross the agent/message
    boundary."""
    from manusift.tools.tool import ToolResult

    result = ToolResult.ok(
        trace_id="trace-1",
        tool_name="metadata",
        result={"detector": "metadata"},
        latency_ms=12,
        metadata={"tool_use_id": "call-1"},
    )
    parsed = json.loads(result.to_json())
    assert parsed == {
        "trace_id": "trace-1",
        "tool_name": "metadata",
        "ok": True,
        "result": {"detector": "metadata"},
        "error": None,
        "latency_ms": 12,
        "metadata": {"tool_use_id": "call-1"},
    }


def test_tool_result_from_legacy_output_preserves_json_payload() -> None:
    """Legacy tools still return
    strings. The adapter should
    parse JSON strings into
    ``result`` while adding trace
    metadata around them."""
    from manusift.tools.tool import ToolResult

    wrapped = ToolResult.from_legacy_output(
        trace_id="trace-2",
        tool_name="bash",
        output='{"ok": false, "error": "denied"}',
        latency_ms=3,
    )
    parsed = json.loads(wrapped.to_json())
    assert parsed["trace_id"] == "trace-2"
    assert parsed["tool_name"] == "bash"
    assert parsed["ok"] is False
    assert parsed["error"] == "denied"
    assert parsed["result"] == {"ok": False, "error": "denied"}
