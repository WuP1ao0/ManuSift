"""Structural check: public short description surfaces stay accurate."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_description_is_offline_integrity_blurb() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Real file must contain the shipped one-liner (not a reimplementation).
    assert 'description = "Screen scholarly PDFs and Source Data' in text
    assert "offline CLI plus a standalone pi-SDK agent" in text
    assert "No API key required" in text
    # Forbidden product claims
    assert "manusift-chat" not in text.lower()
    assert "chat TUI" not in text


def test_readme_lead_matches_product() -> None:
    head = (ROOT / "README.md").read_text(encoding="utf-8")[:1200]
    # Chinese-lead README; accept zh or en integrity wording.
    assert "诚信" in head or "integrity" in head.lower()
    assert "PDF" in head or "pdf" in head
    # pi is the interactive agent surface (MCP removed in the pi migration)
    assert "pi" in head.lower()
    assert "离线" in head or "offline" in head.lower() or "no-llm" in head.lower()
    # Chat is not the product
    assert "manusift-chat" not in head
    # English mirror exists and stays aligned on the basics.
    en = (ROOT / "README.en.md").read_text(encoding="utf-8")[:1500]
    assert "integrity" in en.lower()
    assert "pi" in en.lower()


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
