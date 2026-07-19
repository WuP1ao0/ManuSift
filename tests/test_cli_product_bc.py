"""Product shape B+C: CLI screen + MCP surface."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_suite_names_defined() -> None:
    from manusift.cli import SUITE_DETECTORS

    assert "core" in SUITE_DETECTORS
    assert "table" in SUITE_DETECTORS
    assert "image" in SUITE_DETECTORS
    assert SUITE_DETECTORS["full"] is None


def test_mcp_curated_allowlist_still_defined() -> None:
    """Optional --curated surface (not the server default)."""
    from manusift.mcp.surface import MCP_DEFAULT_TOOLS

    assert "ingest_from_path" in MCP_DEFAULT_TOOLS
    assert "table_forensics" in MCP_DEFAULT_TOOLS
    assert "image_forensics" in MCP_DEFAULT_TOOLS
    assert "render_report" in MCP_DEFAULT_TOOLS
    assert MCP_DEFAULT_TOOLS[:4] == [
        "screen_verdict",
        "submit_screen",
        "get_job_status",
        "get_job_result",
    ]
    for name in (
        "source_data_consistency",
        "cross_paper_image",
        "stat_pvalue_pileup",
        "stat_corr_psd",
        "stat_sprite",
    ):
        assert name in MCP_DEFAULT_TOOLS, name
    # Curated list stays smaller than full registry
    assert "bash" not in MCP_DEFAULT_TOOLS
    assert 40 <= len(MCP_DEFAULT_TOOLS) < 60


def test_cli_help_is_bc_not_chat() -> None:
    from manusift.cli import build_parser

    p = build_parser()
    help_text = p.format_help()
    assert "screen" in help_text
    assert "mcp" in help_text
    assert "batch" in help_text.lower() or "MCP" in help_text


def test_cli_pdf_path_rewrites_to_screen(tmp_path: Path) -> None:
    """``manusift paper.pdf`` is treated as ``manusift screen paper.pdf``."""
    from manusift import cli as cli_mod

    # Don't actually run pipeline — intercept parse only via dry help path.
    # Calling main with missing file should exit 2 without hanging.
    pdf = tmp_path / "nope.pdf"
    code = cli_mod.main([str(pdf)])
    assert code == 2


def test_pipeline_includes_table_suite_classes() -> None:
    from manusift.pipeline import _BUILTIN_DETECTOR_CLASS_NAMES

    for name in (
        "BenfordDetector",
        "DuplicateRowDetector",
        "NearDuplicateRowDetector",
        "CrossTableCopyDetector",
        "TableFileMetadataDetector",
    ):
        assert name in _BUILTIN_DETECTOR_CLASS_NAMES


def test_mcp_list_tools_default_is_full_registry() -> None:
    from manusift.mcp.server import main
    from manusift.tools import iter_registered_tools
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--list-tools"])
    data = json.loads(buf.getvalue())
    full = {t.name for t in iter_registered_tools()}
    assert data["count"] == len(full)
    assert data["count"] >= 80
    assert "ingest_from_path" in data["tools"]
    assert "bash" in data["tools"]
    assert "source_data_consistency" in data["tools"]


def test_mcp_list_tools_curated_flag() -> None:
    from manusift.mcp.server import main
    from manusift.mcp.surface import MCP_DEFAULT_TOOLS
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["--list-tools", "--curated"])
    data = json.loads(buf.getvalue())
    assert data["count"] == len(MCP_DEFAULT_TOOLS)
    assert "bash" not in data["tools"]
    assert "ingest_from_path" in data["tools"]
