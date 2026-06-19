"""Encoding hygiene checks for source and tests."""
from __future__ import annotations

from pathlib import Path


def test_text_files_do_not_contain_common_mojibake_tokens() -> None:
    """Common UTF-8-as-CP1252/GBK artefacts should not live
    in project text files.
    """
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "pyproject.toml",
        root / "README.md",
        *sorted((root / "manusift").rglob("*.py")),
        *sorted((root / "tests").rglob("*.py")),
    ]
    tokens = [
        chr(0x9225) + "?",
        chr(0x9408),
        chr(0x7019),
        chr(0x6942),
        chr(0xFFFD),
        chr(0x951F) + "?",
    ]
    offenders: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in tokens:
            if token in text:
                rel = path.relative_to(root)
                offenders.append(f"{rel}: {token!r}")
                break
    assert offenders == []
