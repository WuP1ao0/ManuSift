"""Install-critical paths for third-party machines (no LLM / no network).

These tests drive **shipped** entry points and package-data resolution —
not re-implementations. They must pass after ``pip install -e .`` on a
clean clone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_package_data_json_files_nonempty() -> None:
    """Runtime detector/report JSON must resolve next to installed modules."""
    from manusift.detectors import tortured_phrases
    from manusift.report import finding_calibration

    tp = Path(tortured_phrases.__file__).with_name("tortured_phrases_data.json")
    pb = Path(finding_calibration.__file__).with_name(
        "publisher_baselines.json"
    )
    assert tp.is_file() and tp.stat().st_size > 100, tp
    assert pb.is_file() and pb.stat().st_size > 10, pb
    # Parseable JSON (not truncated packaging)
    json.loads(tp.read_text(encoding="utf-8"))
    json.loads(pb.read_text(encoding="utf-8"))


def test_cli_help_mentions_screen_twice() -> None:
    """Console / module entry must advertise batch screen (run twice)."""
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-m", "manusift", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            cwd=str(ROOT),
        )
        assert proc.returncode == 0, proc.stderr
        blob = (proc.stdout or "") + (proc.stderr or "")
        assert "screen" in blob.lower()
        assert "mcp" in blob.lower()


def test_suites_lists_known_names() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "manusift", "suites"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    blob = (proc.stdout or "").lower()
    assert "fast" in blob or "core" in blob or "deep" in blob


def test_mcp_list_tools_nonempty() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "manusift", "mcp", "--list-tools"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    blob = (proc.stdout or "") + (proc.stderr or "")
    assert len(blob.strip()) > 40
    # Kernel always exposes screen-related tools
    low = blob.lower()
    assert "screen" in low or "ingest" in low or "detector" in low


def _sample_pdf(tmp_path: Path) -> Path:
    fixture = ROOT / "evals" / "fixtures" / "clean_academic.pdf"
    if fixture.is_file() and fixture.stat().st_size > 0:
        return fixture
    import fitz

    dest = tmp_path / "generated_smoke.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "ManuSift pytest install smoke", fontsize=12)
    doc.save(dest)
    doc.close()
    return dest


def test_get_llm_client_mock_without_api_keys(monkeypatch) -> None:
    """No-key path must return MockLLM (stranger machine / no secrets).

    Developer trees often load ``.env`` via package-relative Settings;
    here we force the no-key branch so the factory path is exercised.
    """
    from manusift.llm import client as llm_client
    from manusift.llm.client import _reset_for_tests, get_llm_client
    from manusift.llm.client.mock import MockLLM

    class _NoKeys:
        default_llm_provider = "openai"
        has_anthropic = False
        has_openai = False

    monkeypatch.setattr(llm_client, "get_settings", lambda: _NoKeys())
    _reset_for_tests()
    client = get_llm_client()
    assert isinstance(client, MockLLM)


def test_offline_screen_writes_findings_and_report(tmp_path: Path) -> None:
    """Real ``manusift screen --no-llm`` primary product path."""
    pdf = _sample_pdf(tmp_path)
    ws = tmp_path / "ws"
    tid = "pytest_install_smoke"
    env = os.environ.copy()
    # Keep jobs under tmp_path even if env had MANUSIFT_WORKSPACE_DIR
    env.pop("MANUSIFT_WORKSPACE_DIR", None)
    # Simulate stranger machine: no LLM credentials
    for key in list(env):
        if "API_KEY" in key:
            env.pop(key, None)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "manusift",
            "screen",
            str(pdf),
            "--no-llm",
            "--suites",
            "fast",
            "--workspace",
            str(ws),
            "--trace-id",
            tid,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        cwd=str(ROOT),
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr

    findings = ws / tid / "output" / "findings.json"
    report = ws / tid / "output" / "report.html"
    pairs = ws / tid / "output" / "investigation_pairs.html"
    assert findings.is_file(), findings
    payload = json.loads(findings.read_text(encoding="utf-8"))
    assert isinstance(payload, (list, dict))
    assert report.is_file() and report.stat().st_size > 0, report
    assert pairs.is_file() and pairs.stat().st_size > 0, pairs
