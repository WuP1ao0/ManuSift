"""P2/P3 redundancy: unified safe_read facade, report path, agent factory, SIFT docs."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_safe_read_exports_phase_b_api() -> None:
    """Canonical surface must re-export Phase B symbols used in production."""
    from manusift.tools import safe_read

    for name in (
        "detect_xlsx_figs",
        "redact_sensitive_text",
        "try_extract_document_real",
        "get_tracker",
        "suggest_similar_files",
        "is_blocked_device",
        "try_extract_document",
    ):
        assert hasattr(safe_read, name), name


def test_xlsx_ingest_imports_unified_safe_read() -> None:
    src = (ROOT / "manusift" / "ingest" / "xlsx.py").read_text(encoding="utf-8")
    assert "from ..tools.safe_read import detect_xlsx_figs" in src
    assert "from ..tools.safe_read_b import detect_xlsx_figs" not in src


def test_direct_fs_uses_unified_safe_read() -> None:
    src = (ROOT / "manusift" / "tools" / "direct_fs.py").read_text(encoding="utf-8")
    assert "from .safe_read_b import" not in src
    assert "from .safe_read import" in src


def test_report_path_doc_names_primary() -> None:
    doc = (ROOT / "docs" / "REPORT_PATH.md").read_text(encoding="utf-8")
    assert "investigation_pairs" in doc
    assert "Primary" in doc or "PRIMARY" in doc


def test_investigation_pairs_is_primary_module() -> None:
    from manusift.report import investigation_pairs

    assert hasattr(investigation_pairs, "write_investigation_pairs")
    assert hasattr(investigation_pairs, "build_investigation_pairs_payload")
    head = Path(investigation_pairs.__file__).read_text(encoding="utf-8")[:400]
    assert "PRIMARY" in head or "primary" in head.lower()


def test_create_agent_loop_default_is_pydantic_or_legacy_fallback() -> None:
    from manusift.agent.factory import create_agent_loop, resolve_agent_runtime
    from manusift.tools import ToolContext

    # Default resolution prefers pydantic when package present.
    runtime = resolve_agent_runtime(None)
    assert runtime in ("pydantic_ai", "legacy")

    class _Client:
        name = "mock"

        def chat(self, messages, tools=None, max_tokens=4096):
            from manusift.llm.chat import ChatResponse

            return ChatResponse(text="ok", tool_calls=[], finish_reason="end_turn")

    ctx = ToolContext(trace_id="t")
    loop = create_agent_loop(_Client(), tools=[], ctx=ctx, runtime="pydantic_ai")
    # Must not force callers to import legacy module for the default type
    assert loop.__class__.__module__.endswith("pydantic_loop") or loop.__class__.__name__ == "PydanticAgentLoop"


def test_factory_legacy_flag_still_constructs() -> None:
    from manusift.agent.factory import create_agent_loop
    from manusift.tools import ToolContext

    class _Client:
        name = "mock"

        def chat(self, messages, tools=None, max_tokens=4096):
            from manusift.llm.chat import ChatResponse

            return ChatResponse(text="ok", tool_calls=[], finish_reason="end_turn")

    ctx = ToolContext(trace_id="t")
    loop = create_agent_loop(_Client(), tools=[], ctx=ctx, runtime="legacy")
    assert loop.__class__.__name__ == "AgentLoop"
    assert "legacy_loop" in loop.__class__.__module__


def test_sift_pipeline_still_registered() -> None:
    from manusift.pipeline import _BUILTIN_DETECTOR_CLASS_NAMES

    assert "SiftCopyMoveDetector" in _BUILTIN_DETECTOR_CLASS_NAMES
    assert "ImageForensicsDetector" in _BUILTIN_DETECTOR_CLASS_NAMES or any(
        "Forensics" in n for n in _BUILTIN_DETECTOR_CLASS_NAMES
    )


def test_detector_layers_documents_p2_p3() -> None:
    text = (ROOT / "docs" / "DETECTOR_LAYERS.md").read_text(encoding="utf-8")
    assert "safe_read" in text
    assert "Pydantic" in text or "pydantic" in text
    assert "SIFT" in text or "sift" in text
