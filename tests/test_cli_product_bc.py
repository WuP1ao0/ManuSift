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


def test_cli_help_is_bc_not_chat() -> None:
    from manusift.cli import build_parser

    p = build_parser()
    help_text = p.format_help()
    assert "screen" in help_text
    assert "toolserver" in help_text
    assert "batch" in help_text.lower() or "pi" in help_text


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


def test_toolserver_list_tools_is_full_registry() -> None:
    import io
    from contextlib import redirect_stdout

    from manusift.toolserver import main
    from manusift.tools import iter_registered_tools

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
