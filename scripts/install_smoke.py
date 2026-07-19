#!/usr/bin/env python3
"""Third-party install smoke: package-data + CLI help + offline screen.

Run after ``pip install -e .`` (or wheel install)::

    python scripts/install_smoke.py
    python scripts/install_smoke.py --workspace /tmp/ms-smoke

Exit 0 only when all gates pass. No LLM keys or network required.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_sample_pdf(dest: Path) -> Path:
    """Return a readable PDF path (fixture or generated one-pager)."""
    fixture = _repo_root() / "evals" / "fixtures" / "clean_academic.pdf"
    if fixture.is_file() and fixture.stat().st_size > 0:
        return fixture

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            f"PyMuPDF required to generate sample PDF: {exc}"
        ) from exc

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (72, 72),
        "ManuSift install smoke sample\n\nAbstract: offline screen fixture.",
        fontsize=12,
    )
    doc.save(dest)
    doc.close()
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise SystemExit(f"failed to write sample PDF: {dest}")
    return dest


def check_package_data() -> list[str]:
    """Assert runtime JSON assets resolve next to installed modules."""
    lines: list[str] = []
    from manusift.detectors import tortured_phrases
    from manusift.report import finding_calibration

    tp = Path(tortured_phrases.__file__).with_name("tortured_phrases_data.json")
    pb = Path(finding_calibration.__file__).with_name(
        "publisher_baselines.json"
    )
    for p in (tp, pb):
        if not p.is_file() or p.stat().st_size <= 0:
            raise SystemExit(f"missing package data: {p}")
        lines.append(f"OK {p} ({p.stat().st_size} bytes)")

    static = Path(finding_calibration.__file__).resolve().parents[1] / "web" / "static"
    index = static / "index.html"
    if index.is_file() and index.stat().st_size > 0:
        lines.append(f"OK {index} ({index.stat().st_size} bytes)")
    else:
        lines.append(f"WARN web static missing at {index} (optional for CLI)")
    return lines


def check_cli_help() -> list[str]:
    """CLI --help must mention screen; suites must list names."""
    env = os.environ.copy()
    # Prefer module entry (works even if console scripts not on PATH).
    cmds = [
        [sys.executable, "-m", "manusift", "--help"],
        [sys.executable, "-m", "manusift", "suites"],
        [sys.executable, "-m", "manusift", "mcp", "--list-tools"],
    ]
    out_lines: list[str] = []
    for cmd in cmds:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise SystemExit(
                f"command failed ({proc.returncode}): {' '.join(cmd)}\n{blob}"
            )
        out_lines.append(f"$ {' '.join(cmd)}")
        out_lines.append(blob[:2000])
        if "help" in cmd or cmd[-1] == "--help":
            if "screen" not in blob.lower():
                raise SystemExit("CLI help missing 'screen' subcommand")
        if cmd[-1] == "suites":
            if "core" not in blob.lower() and "fast" not in blob.lower():
                raise SystemExit("suites output empty or unexpected")
        if "--list-tools" in cmd:
            # MCP list prints tool names / count
            if "screen" not in blob.lower() and "tool" not in blob.lower():
                # tolerate JSON list
                if len(blob.strip()) < 20:
                    raise SystemExit("MCP --list-tools returned empty output")
    return out_lines


def check_offline_screen(workspace: Path, pdf: Path) -> list[str]:
    """Real batch screen --no-llm; require findings + report artifacts."""
    workspace.mkdir(parents=True, exist_ok=True)
    tid = "install_smoke"
    cmd = [
        sys.executable,
        "-m",
        "manusift",
        "screen",
        str(pdf),
        "--no-llm",
        "--suites",
        "fast",
        "--workspace",
        str(workspace),
        "--trace-id",
        tid,
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    lines = [f"$ {' '.join(cmd)}", f"exit={proc.returncode}", blob[-4000:]]
    if proc.returncode != 0:
        raise SystemExit(f"screen failed:\n{blob}")

    try:
        summary = json.loads(proc.stdout.strip().splitlines()[-1]
                             if False else _extract_json_object(proc.stdout))
    except Exception:
        # Fall back to known workspace layout
        summary = {}

    job = workspace / tid
    findings = job / "output" / "findings.json"
    report = job / "output" / "report.html"
    pairs = job / "output" / "investigation_pairs.html"
    if summary.get("findings_json"):
        findings = Path(summary["findings_json"])
    if summary.get("report_html"):
        report = Path(summary["report_html"])
    if summary.get("investigation_pairs_html"):
        pairs = Path(summary["investigation_pairs_html"])

    if not findings.is_file():
        raise SystemExit(f"findings.json missing: {findings}")
    data = json.loads(findings.read_text(encoding="utf-8"))
    if not isinstance(data, (list, dict)):
        raise SystemExit("findings.json not list/object")
    report_ok = (report.is_file() and report.stat().st_size > 0) or (
        pairs.is_file() and pairs.stat().st_size > 0
    )
    if not report_ok:
        raise SystemExit(
            f"no non-empty report at {report} or {pairs}"
        )
    lines.append(f"findings={findings} size={findings.stat().st_size}")
    lines.append(f"report={report} exists={report.is_file()}")
    lines.append(f"pairs={pairs} exists={pairs.is_file()}")
    return lines


def _extract_json_object(text: str) -> dict:
    """Parse the trailing JSON object printed by ``manusift screen``."""
    text = text or ""
    start = text.rfind("{")
    if start < 0:
        return {}
    # Walk from last '{' — screen prints one top-level object at end.
    # Prefer brace matching from first '{' of the last block.
    # Heuristic: find last line that starts with '{'
    for i in range(len(text) - 1, -1, -1):
        if text[i] == "{" and (i == 0 or text[i - 1] in "\n\r"):
            chunk = text[i:]
            return json.loads(chunk)
    return json.loads(text[start:])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Job workspace root (default: temp dir)",
    )
    args = ap.parse_args(argv)

    print("== package data ==")
    for line in check_package_data():
        print(line)

    print("== CLI / MCP help ==")
    for line in check_cli_help():
        print(line)

    print("== offline screen ==")
    with tempfile.TemporaryDirectory(prefix="manusift_smoke_") as td:
        td_path = Path(td)
        pdf = _ensure_sample_pdf(td_path / "sample.pdf")
        print(f"sample_pdf={pdf}")
        ws = args.workspace or (td_path / "ws")
        for line in check_offline_screen(ws, pdf):
            print(line)

    print("ALL GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
