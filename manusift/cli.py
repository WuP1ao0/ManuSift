"""Tiny CLI entry point. Useful for debugging without the web layer."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _run_chat_tui() -> None:
    from .tui.chat_app import main as chat_main

    chat_main()


def app() -> int:
    """Compatibility entry point for stale ``manusift`` launchers."""
    _run_chat_tui()
    return 0


def main(argv: list[str] | None = None) -> int:
    from .config import get_settings
    from .contracts import JobState
    from .pipeline import run_pipeline
    from .trace import bind_trace_id, configure_logging, new_trace_id
    from .workspace import JobPaths

    configure_logging()
    parser = argparse.ArgumentParser(prog="manusift-analyze")
    parser.add_argument("pdf", type=Path, help="PDF to analyze")
    args = parser.parse_args(argv)

    settings = get_settings()
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)

    tid = new_trace_id()
    bind_trace_id(tid)
    paths = JobPaths.for_trace(tid, settings.workspace_dir)
    paths.ensure()
    paths.original.write_bytes(args.pdf.read_bytes())

    job = JobState(trace_id=tid, status="queued", source_filename=args.pdf.name)
    run_pipeline(paths.original, paths, job)
    print(f"trace_id: {tid}")
    print(f"report:   {paths.report_html}")
    print(f"status:   {job.status}  findings: {job.finding_count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
