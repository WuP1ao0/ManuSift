"""Structural check: public short description surfaces stay accurate."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_description_is_offline_integrity_blurb() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Real file must contain the shipped one-liner (not a reimplementation).
    assert 'description = "Screen scholarly PDFs and Source Data' in text
    assert "offline CLI and MCP" in text
    assert "No API key required" in text
    # Forbidden product claims
    assert "manusift-chat" not in text.lower()
    assert "chat TUI" not in text


def test_readme_lead_matches_product_bc() -> None:
    head = (ROOT / "README.md").read_text(encoding="utf-8")[:900]
    assert "integrity" in head.lower() or "red flags" in head.lower()
    assert "PDF" in head or "pdf" in head
    assert "MCP" in head or "mcp" in head
    assert "offline" in head.lower() or "no-llm" in head.lower() or "No API key" in head
    # Chat is not the product
    assert "manusift-chat" not in head
    assert "not part of the product" in head or "Removed" in head or "not part" in head.lower()


def test_github_oriented_blurb_length_is_short() -> None:
    """GitHub About practice: one sentence, not a README dump."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("description = "):
            # strip description = "..."
            blurb = line.split("=", 1)[1].strip().strip('"')
            assert 40 <= len(blurb) <= 200, len(blurb)
            return
    raise AssertionError("description line missing from pyproject.toml")
