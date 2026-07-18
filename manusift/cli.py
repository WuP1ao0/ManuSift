"""ManuSift product CLI — batch screen (B) + MCP launcher (C).

Product shape (2026-07):
  **B** Strong offline batch screening (no conversational agent)
  **C** MCP server for other agents to call Domain Kernel tools

Conversational chat TUI has been **removed**. Optional job browser:
``manusift-workspace`` / ``manusift-tui``.

Examples::

    manusift screen paper.pdf
    manusift screen paper.pdf --data-paths ./source_data
    manusift screen paper.pdf --suites fast          # light triage only
    manusift screen paper.pdf --no-llm --lang zh
    manusift mcp
    manusift mcp --list-tools

Default suite is **deep** (full pipeline). Use ``--suites core`` or
``fast`` only when you explicitly want a lighter pass.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# Suites: named detector allow-lists for batch screen
# ---------------------------------------------------------------------------

# Maps suite name -> detector *names* (detector.name), empty = full pipeline.
# ``deep`` is an alias of ``full`` (all pipeline detectors) — the product
# default after "直接深度审查" product decision.
SUITE_DETECTORS: dict[str, set[str] | None] = {
    "full": None,  # all pipeline detectors
    "deep": None,  # alias of full — default deep screen
    "core": {
        "metadata",
        "pdf_metadata",
        "image_dup",
        "image_forensics",
        "image_sift_copymove",
        "table_benford",
        "table_duplicate_row",
        "table_near_duplicate_row",
        "table_cross_copy",
        "table_outlier",
        "table_round_bias",
        "table_relationships",
        "table_file_metadata",
        "table_highlight_focus",
        "table_forensics",
        "stat_grim",
        "text_patterns",
        "ref_duplicate",
        "compliance",
        "supplementary",
    },
    "image": {
        "image_dup",
        "image_forensics",
        "image_noise_inconsistency",
        "image_sift_copymove",
        "panel_dup",
        "panel_duplicate",
        "page_raster_dup",
        "ai_generated_figure",
    },
    "table": {
        "table_benford",
        "table_duplicate_row",
        "table_near_duplicate_row",
        "table_cross_copy",
        "table_outlier",
        "table_round_bias",
        "table_relationships",
        "table_file_metadata",
        "table_highlight_focus",
        "table_forensics",
        "stat_grim",
        "stat_pvalue",
        "stat_percent",
        "figure_grim",
        "figure_stat_text",
        "figure_table_ocr",
        "figure_table_consistency",
        "source_data_consistency",
        "supplementary",
    },
    "fast": {
        "metadata",
        "pdf_metadata",
        "image_dup",
        "table_duplicate_row",
        "table_benford",
        "text_patterns",
        "ref_duplicate",
    },
}


def _copy_companions(materials_dir: Path, data_paths: Sequence[Path]) -> list[str]:
    """Copy companion files/dirs into job materials/. Returns copied paths."""
    materials_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for raw in data_paths:
        p = raw if raw.is_absolute() else (Path.cwd() / raw)
        p = p.resolve()
        if not p.exists():
            continue
        if p.is_file():
            dest = materials_dir / p.name
            if dest.resolve() != p:
                shutil.copy2(p, dest)
            copied.append(str(dest))
        elif p.is_dir():
            for f in p.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in {
                    ".xlsx",
                    ".xlsm",
                    ".csv",
                    ".tsv",
                    ".json",
                    ".zip",
                    ".pdf",
                }:
                    continue
                # Keep flat name; collide → suffix
                dest = materials_dir / f.name
                if dest.exists() and dest.stat().st_size == f.stat().st_size:
                    copied.append(str(dest))
                    continue
                if dest.exists():
                    stem, suf = f.stem, f.suffix
                    n = 2
                    while dest.exists():
                        dest = materials_dir / f"{stem}_{n}{suf}"
                        n += 1
                shutil.copy2(f, dest)
                copied.append(str(dest))
    return copied


def cmd_screen(args: argparse.Namespace) -> int:
    """B: batch integrity screen → findings.json + report.html."""
    from .config import get_settings
    from .contracts import JobState
    from .pipeline import run_pipeline
    from .trace import bind_trace_id, configure_logging, new_trace_id
    from .workspace import JobPaths

    configure_logging()
    pdf = args.pdf if args.pdf.is_absolute() else (Path.cwd() / args.pdf)
    pdf = pdf.resolve()
    if not pdf.is_file():
        print(json.dumps({"ok": False, "error": f"PDF not found: {pdf}"}, ensure_ascii=False))
        return 2

    # Settings is a frozen pydantic model — configure via env, then reload.
    if args.workspace:
        ws = Path(args.workspace)
        if not ws.is_absolute():
            ws = Path.cwd() / ws
        os.environ["MANUSIFT_WORKSPACE_DIR"] = str(ws.resolve())
    if args.no_llm:
        os.environ["MANUSIFT_LLM_MAX_CONCURRENCY"] = "0"

    # --deep forces full pipeline regardless of --suites
    suite = (getattr(args, "suites", None) or "deep").lower().strip()
    if getattr(args, "deep", False):
        suite = "deep"
    if suite not in SUITE_DETECTORS:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"unknown suite {suite!r}",
                    "suites": sorted(SUITE_DETECTORS),
                },
                ensure_ascii=False,
            )
        )
        return 2

    allow = SUITE_DETECTORS.get(suite)
    if allow is not None:
        # Build skip list = pipeline detectors not in suite (via env).
        if hasattr(get_settings, "cache_clear"):
            get_settings.cache_clear()
        from .pipeline import _pipeline_detector_classes

        all_names = {cls().name for cls in _pipeline_detector_classes()}
        skip = sorted(all_names - allow)
        os.environ["MANUSIFT_BENCHMARK_SKIP_DETECTORS"] = ",".join(skip)

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    settings = get_settings()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    tid = args.trace_id or new_trace_id()
    bind_trace_id(tid)
    paths = JobPaths.for_trace(tid, settings.workspace_dir)
    paths.ensure()
    paths.original.write_bytes(pdf.read_bytes())

    materials = paths.materials_dir
    data_paths = list(args.data_paths or [])
    # If user passed a directory as only companion, use it; also default
    # to PDF parent when --with-sidecar is set.
    if args.with_sidecar:
        data_paths.append(pdf.parent)
    copied = _copy_companions(materials, data_paths) if data_paths else []

    job = JobState(trace_id=tid, status="queued", source_filename=pdf.name)
    result = run_pipeline(paths.original, paths, job)

    report_path = paths.report_html
    # Prefer zh narrative if present (render path may write report.zh.html)
    for cand in (
        paths.output_dir / "report.zh.html",
        paths.output_dir / f"report.{args.lang}.html",
        paths.report_html,
    ):
        if cand.is_file():
            report_path = cand
            break

    summary = {
        "ok": job.status == "done" and paths.findings_json.is_file(),
        "product": "B+C",
        "mode": "screen",
        "trace_id": tid,
        "pdf": str(pdf),
        "suite": suite,
        "status": job.status,
        "finding_count": int(getattr(job, "finding_count", 0) or 0),
        "detectors_run": list(result.detectors_run),
        "duration_ms": result.duration_ms,
        "llm_calls": result.llm_calls,
        "companions_copied": len(copied),
        "findings_json": str(paths.findings_json.resolve()),
        "report_html": str(report_path.resolve()),
        "llm_report_html": str(paths.llm_report_html.resolve()),
        "llm_report_md": str(paths.llm_report_md.resolve()),
        "llm_report_json": str(paths.llm_report_json.resolve()),
        "llm_briefing_html": str(paths.llm_briefing_html.resolve()),
        "llm_briefing_md": str(paths.llm_briefing_md.resolve()),
        "investigation_pairs_html": str(
            paths.investigation_pairs_html.resolve()
        ),
        "investigation_pairs_md": str(
            paths.investigation_pairs_md.resolve()
        ),
        "investigation_pairs_json": str(
            paths.investigation_pairs_json.resolve()
        ),
        "investigation_plain_html": str(
            paths.investigation_plain_html.resolve()
        ),
        "investigation_plain_md": str(
            paths.investigation_plain_md.resolve()
        ),
        "job_dir": str(paths.root.resolve()),
    }
    if job.status == "failed":
        summary["ok"] = False

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") else 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """C: launch MCP server (Domain Kernel tools for other agents)."""
    from .mcp.server import main as mcp_main

    argv: list[str] = []
    if args.trace_id:
        argv.extend(["--trace-id", args.trace_id])
    if args.list_tools:
        argv.append("--list-tools")
    if args.tools:
        argv.extend(["--tools", args.tools])
    elif not args.all_tools:
        # Default B+C surface: curated kernel tools, not full 66-tool dump
        from .mcp.surface import MCP_DEFAULT_TOOLS

        argv.extend(["--tools", ",".join(MCP_DEFAULT_TOOLS)])
    mcp_main(argv)
    return 0


def cmd_suites(_: argparse.Namespace) -> int:
    print(
        json.dumps(
            {
                "suites": {
                    k: (sorted(v) if v is not None else "all_pipeline_detectors")
                    for k, v in SUITE_DETECTORS.items()
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="manusift",
        description=(
            "ManuSift paper-integrity screener — batch CLI (B) + MCP (C). "
            "Conversational agent UI is not part of the default product."
        ),
    )
    sub = p.add_subparsers(dest="command", required=False)

    # --- screen ---
    sp = sub.add_parser(
        "screen",
        help="Batch-screen a PDF (+ optional source data) → report + findings",
    )
    sp.add_argument("pdf", type=Path, help="Path to paper PDF")
    sp.add_argument(
        "--data-paths",
        nargs="*",
        type=Path,
        default=None,
        help="Companion files or directories (XLSX/CSV/…)",
    )
    sp.add_argument(
        "--with-sidecar",
        action="store_true",
        help="Also scan the PDF's parent directory for companion data",
    )
    sp.add_argument(
        "--suites",
        default="deep",
        choices=sorted(SUITE_DETECTORS),
        help=(
            "Detector suite (default: deep = full pipeline). "
            "Use core/fast for a lighter triage pass."
        ),
    )
    sp.add_argument(
        "--deep",
        action="store_true",
        help="Force deep screen (full pipeline; same as --suites deep/full)",
    )
    sp.add_argument("--trace-id", default=None, help="Reuse/force job id")
    sp.add_argument("--workspace", type=Path, default=None, help="Workspace root")
    sp.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM enrichment of findings",
    )
    sp.add_argument(
        "--lang",
        default="zh",
        help="Preferred report language code (zh/en) when available",
    )
    sp.set_defaults(func=cmd_screen)

    # --- mcp ---
    mp = sub.add_parser("mcp", help="Start MCP server for other agents (stdio)")
    mp.add_argument("--trace-id", default=None)
    mp.add_argument("--list-tools", action="store_true")
    mp.add_argument(
        "--tools",
        default=None,
        help="Comma-separated tool allow-list (default: curated B+C surface)",
    )
    mp.add_argument(
        "--all-tools",
        action="store_true",
        help="Expose every registered tool (legacy; large schema)",
    )
    mp.set_defaults(func=cmd_mcp)

    # --- suites ---
    lp = sub.add_parser("suites", help="List detector suites for screen")
    lp.set_defaults(func=cmd_suites)

    # --- analyze (compat alias) ---
    ap = sub.add_parser(
        "analyze",
        help="Alias for 'screen' (legacy manusift-analyze)",
    )
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--data-paths", nargs="*", type=Path, default=None)
    ap.add_argument("--with-sidecar", action="store_true")
    ap.add_argument(
        "--suites",
        default="deep",
        choices=sorted(SUITE_DETECTORS),
    )
    ap.add_argument(
        "--deep",
        action="store_true",
        help="Force deep screen (full pipeline)",
    )
    ap.add_argument("--trace-id", default=None)
    ap.add_argument("--workspace", type=Path, default=None)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--lang", default="zh")
    ap.set_defaults(func=cmd_screen)

    return p


def main(argv: list[str] | None = None) -> int:
    # Backward compat: `manusift-analyze paper.pdf` historically had no subcommand.
    # If first arg looks like a PDF path, treat as `screen`.
    raw = list(argv) if argv is not None else sys.argv[1:]
    if raw and not raw[0].startswith("-"):
        cmd = raw[0]
        if cmd.endswith(".pdf") or Path(cmd).suffix.lower() == ".pdf":
            raw = ["screen", *raw]
        elif cmd not in (
            "screen",
            "mcp",
            "suites",
            "analyze",
            "help",
        ) and Path(cmd).is_file() and Path(cmd).suffix.lower() == ".pdf":
            raw = ["screen", *raw]

    parser = build_parser()
    if not raw:
        parser.print_help()
        print(
            "\n# Product shape: B (screen) + C (mcp). "
            "Example: manusift screen paper.pdf --with-sidecar"
        )
        return 0

    args = parser.parse_args(raw)
    if not getattr(args, "command", None) and not hasattr(args, "func"):
        parser.print_help()
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


def app() -> int:
    """Legacy name used by some launchers."""
    return main()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
