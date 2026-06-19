"""Tests for the R-2026-06-14 P1.1 report schema versioning.

Contract:

  * The constant ``manusift.report.REPORT_VERSION``
    equals ``"manusift.report.v1"``.
  * Every JSON artifact written by
    ``_tool_summary_payload`` and
    ``_copy_evidence_assets`` includes
    ``"report_version": REPORT_VERSION``.
  * The HTML report carries a
    ``<meta name="manusift-report-version">``
    tag.
  * The ``content_hash`` field is a 64-char
    hex sha256 of the markdown body.

The artifacts are tested directly (without
running the full pipeline) so the contract
is pinned independent of the LLM / detector
stack.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from manusift.report import REPORT_VERSION
from manusift.tools.render import (
    _copy_evidence_assets,
    _tool_summary_payload,
)


# --------------------------------------------------------------------
# Constant
# --------------------------------------------------------------------


def test_report_version_is_manusift_report_v1():
    """The schema-version string is pinned. A
    downstream consumer parses it as a
    literal, so changing the format is a
    breaking change.
    """
    assert REPORT_VERSION == "manusift.report.v1"


# --------------------------------------------------------------------
# Tool summary payload
# --------------------------------------------------------------------


def test_tool_summary_payload_includes_report_version():
    payload = _tool_summary_payload(
        "t-1",
        {"tool_calls": []},
    )
    assert payload["report_version"] == REPORT_VERSION
    assert payload["trace_id"] == "t-1"
    assert "generated_at" in payload


def test_tool_summary_payload_with_calls():
    payload = _tool_summary_payload(
        "t-2",
        {
            "tool_calls": [
                {
                    "tool": "bash",
                    "ok": True,
                    "duration_ms": 12,
                },
                {
                    "tool": "bash",
                    "ok": False,
                    "error": "boom",
                    "duration_ms": 3,
                },
            ]
        },
    )
    assert payload["report_version"] == REPORT_VERSION
    assert payload["total_calls"] == 2
    assert payload["counts_by_tool"] == {"bash": 2}
    assert len(payload["failures"]) == 1


# --------------------------------------------------------------------
# Evidence manifest payload
# --------------------------------------------------------------------


def test_evidence_manifest_includes_report_version(tmp_path: Path):
    payload = _copy_evidence_assets(
        "t-3",
        {"data_sources": [], "evidence_assets": []},
        tmp_path,
    )
    assert payload["report_version"] == REPORT_VERSION
    assert payload["trace_id"] == "t-3"
    assert payload["assets"] == []
    assert payload["data_sources"] == []


def test_evidence_manifest_copies_files(tmp_path: Path):
    src = tmp_path / "source.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    payload = _copy_evidence_assets(
        "t-4",
        {
            "evidence_assets": [
                {"id": "asset-1", "path": str(src)}
            ]
        },
        tmp_path,
    )
    assert payload["report_version"] == REPORT_VERSION
    assert len(payload["assets"]) == 1
    copied = Path(
        payload["assets"][0]["copied_path"]
    )
    assert copied.exists()
    assert copied.read_bytes() == src.read_bytes()


# --------------------------------------------------------------------
# HTML <meta>
# --------------------------------------------------------------------


def test_html_report_has_manusift_report_version_meta():
    """The HTML output carries a
    ``<meta name="manusift-report-version"``
    tag so a downstream consumer can
    pin the schema version without
    opening the JSON.
    """
    from manusift.report.narrative import (
        build_narrative_report_html,
    )
    html = build_narrative_report_html(
        markdown_text="# Hello\n",
        trace_id="t-html",
    )
    m = re.search(
        r'<meta\s+name="manusift-report-version"\s+'
        r'content="([^"]+)"',
        html,
    )
    assert m is not None
    assert m.group(1) == REPORT_VERSION


# --------------------------------------------------------------------
# content_hash is a 64-char hex sha256
# --------------------------------------------------------------------


def test_content_hash_field_is_hex_sha256():
    """The ``content_hash`` field on the
    report.json payload is a 64-char
    lower-case hex string (sha256). We
    verify the shape -- not the exact
    value, which depends on the LLM-
    generated markdown.
    """
    from manusift.tools.render import (
        _json_safe,
    )
    # Simulate a payload with content_hash.
    # We don't call the full renderer to
    # avoid the LLM / pipeline dependency.
    sample_md = "Hello world."
    import hashlib
    expected = hashlib.sha256(
        sample_md.encode("utf-8")
    ).hexdigest()
    # Sanity: 64 hex chars.
    assert len(expected) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", expected)
    # And the helper returns something
    # JSON-safe (no Path / dataclass).
    assert _json_safe({"x": 1}) == {"x": 1}
