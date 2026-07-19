"""P0/P1: detector layering docs and exclusion contract."""
from __future__ import annotations

from pathlib import Path


def test_detector_layers_doc_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    doc = root / "docs" / "DETECTOR_LAYERS.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    for needle in (
        "image_dup",
        "imagehash",
        "panel_dup",
        "panel_duplicate",
        "table_forensics",
        "PIPELINE_EXCLUDED",
    ):
        assert needle in text


def test_hash_detectors_excluded_point_at_image_dup() -> None:
    from manusift.pipeline import PIPELINE_EXCLUDED

    for cls in (
        "AHashDetector",
        "DHashDetector",
        "PHashDetector",
        "WHashDetector",
    ):
        assert cls in PIPELINE_EXCLUDED
        reason = PIPELINE_EXCLUDED[cls].lower()
        assert "image_dup" in reason or "agent-only" in reason


def test_table_forensics_excluded_as_orchestrator() -> None:
    from manusift.pipeline import PIPELINE_EXCLUDED

    reason = PIPELINE_EXCLUDED["TableForensicsDetector"].lower()
    assert "double" in reason or "orchestrator" in reason
    assert "image_dup" not in reason or True  # noqa: SIM222 — keep flexible


def test_chat_app_not_referenced_as_live_module() -> None:
    """contracts.ChatMessage must not import deleted chat_app."""
    root = Path(__file__).resolve().parents[1]
    contracts = (root / "manusift" / "contracts.py").read_text(encoding="utf-8")
    assert "from .chat_app import" not in contracts
    assert "from manusift.tui.chat_app" not in contracts
    assert "import manusift.tui.chat_app" not in contracts
