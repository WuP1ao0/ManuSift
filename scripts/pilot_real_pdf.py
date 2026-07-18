"""Real-PDF pilot: ingest + Pydantic agent review under cost/step caps.

Usage (from repo root, venv active)::

    python scripts/pilot_real_pdf.py
    python scripts/pilot_real_pdf.py --pdf path\\to\\paper.pdf

Writes ``data/pilot_jobs/pilot_<ts>.json`` and prints a summary.
Does not print API keys.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = ROOT / "data" / "pilot_jobs"
DEFAULT_PDF = (
    ROOT
    / "real_eval_fraud_cases"
    / "cases"
    / "case_001_plos_plasmonic_nanobubbles"
    / "paper.pdf"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ManuSift real-PDF pilot")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--max-steps", type=int, default=16)
    parser.add_argument(
        "--max-cost",
        type=float,
        default=0.0,
        help="Ignored (cost-cap removed). Kept for CLI compat.",
    )
    parser.add_argument(
        "--toolset",
        choices=("core", "full"),
        default="core",
        help=(
            "core=screening tools only (avoids DeepSeek 400 on 66-tool schemas); "
            "full=all registered tools"
        ),
    )
    parser.add_argument(
        "--prompt",
        default=(
            "请对这篇论文做一次诚信初筛（深度审查）。"
            "先确认已 ingest，再运行最相关的检测器（至少包括 metadata / image_dup 或 image_forensics 等与图相关的检查），"
            "最后用 render_report 生成 HTML 报告，并在回复里给出 report.html 的绝对路径。"
            "用中文写简短结论，不要复读，不要空转重复同一工具。"
        ),
    )
    parser.add_argument(
        "--data-paths",
        nargs="*",
        default=None,
        help=(
            "Optional companion source-data files/dirs for ingest "
            "(XLSX/CSV). If omitted and the PDF directory contains "
            "them, auto-discovery still applies."
        ),
    )
    args = parser.parse_args(argv)

    pdf = args.pdf if args.pdf.is_absolute() else (ROOT / args.pdf)
    if not pdf.is_file():
        print(json.dumps({"ok": False, "error": f"PDF missing: {pdf}"}, ensure_ascii=False))
        return 2

    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["MANUSIFT_WORKSPACE_DIR"] = str(PILOT_DIR.resolve())
    os.environ.setdefault("MANUSIFT_AGENT_RUNTIME", "pydantic_ai")
    # Cost-cap protection removed — do not set MANUSIFT_AGENT_MAX_COST_USD.

    from manusift.config import get_settings
    from manusift.llm.client import _reset_for_tests, get_llm_client
    from manusift.agent.factory import create_agent_loop, resolve_agent_runtime
    from manusift.tools import ToolContext, iter_registered_tools
    from manusift.tools.registry import get_tool

    _reset_for_tests()
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    settings = get_settings()
    client = get_llm_client()
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"pilot_{ts}"
    summary: dict = {
        "run_id": run_id,
        "pdf": str(pdf.resolve()),
        "pdf_kb": pdf.stat().st_size // 1024,
        "runtime": resolve_agent_runtime(),
        "provider": settings.default_llm_provider,
        "model": (
            settings.anthropic_model
            if settings.has_anthropic
            else settings.openai_model
        ),
        "base_url": (
            settings.anthropic_base_url
            if settings.has_anthropic
            else settings.openai_base_url
        ),
        "client": type(client).__name__,
        "max_steps": args.max_steps,
        "max_cost_usd": args.max_cost,
        "workspace": str(PILOT_DIR.resolve()),
        "ok": False,
    }

    if type(client).__name__ == "MockLLM" or not client.is_available():
        summary["error"] = "LLM unavailable / Mock — check .env"
        _save(summary, run_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 3

    # --- ingest ---
    ingest = get_tool("ingest_from_path")
    if ingest is None:
        for t in iter_registered_tools():
            if getattr(t, "name", None) == "ingest_from_path":
                ingest = t
                break
    if ingest is None:
        summary["error"] = "ingest_from_path missing"
        _save(summary, run_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 4

    ctx0 = ToolContext(trace_id=run_id)
    t0 = time.time()
    ingest_input: dict = {"path": str(pdf.resolve())}
    if args.data_paths:
        resolved_ds = []
        for p in args.data_paths:
            dp = Path(p)
            if not dp.is_absolute():
                dp = ROOT / dp
            resolved_ds.append(str(dp.resolve()))
        ingest_input["data_paths"] = resolved_ds
        summary["data_paths"] = resolved_ds
    ingest_raw = ingest.execute(ingest_input, ctx0)
    summary["ingest_seconds"] = round(time.time() - t0, 2)
    try:
        ingest_data = json.loads(ingest_raw)
    except Exception:
        ingest_data = {"raw": ingest_raw[:800]}
    summary["ingest"] = _slim_ingest(ingest_data)
    trace_id = _extract_trace_id(ingest_data) or run_id
    summary["trace_id"] = trace_id

    # --- agent ---
    all_tools = list(iter_registered_tools())
    CORE_NAMES = {
        "ingest_from_path",
        "list_dir",
        "list_data_sources",
        "read_data_source",
        "list_findings",
        "read_finding",
        "metadata",
        "image_dup",
        "image_forensics",
        "panel_dup",
        "page_raster_dup",
        "panel_duplicate",
        "table_benford",
        "table_duplicate_row",
        "table_outlier",
        "table_round_bias",
        "table_relationships",
        "table_near_duplicate_row",
        "table_cross_copy",
        "table_file_metadata",
        "table_forensics",
        "text_patterns",
        "render_report",
        "ai_generated_figure",
        "ref_duplicate",
        "stat_grim",
        "figure_grim",
        "source_data_audit",
        "bash",
        "read_file",
    }
    if args.toolset == "core":
        tools = [t for t in all_tools if getattr(t, "name", "") in CORE_NAMES]
        if not tools:
            tools = all_tools
    else:
        tools = all_tools
    summary["toolset"] = args.toolset
    summary["tool_count"] = len(tools)
    summary["tool_names"] = sorted(getattr(t, "name", "?") for t in tools)

    agent_ctx = ToolContext(
        trace_id=str(trace_id),
        current_pdf=str(pdf.resolve()),
        metadata={
            "session_id": run_id,
            "pilot": True,
            "conversation_state": {
                "active_trace_id": str(trace_id),
                "current_pdf": str(pdf.resolve()),
            },
        },
    )
    loop = create_agent_loop(
        client,
        tools,
        agent_ctx,
        runtime="pydantic_ai",
        max_steps=args.max_steps,
        max_cost_usd=args.max_cost,
    )

    user_msg = (
        f"PDF 路径: {pdf.resolve()}\n"
        f"trace_id: {trace_id}\n"
        f"{args.prompt}"
    )
    t1 = time.time()
    try:
        result = loop.run(user_msg)
        summary["agent_seconds"] = round(time.time() - t1, 2)
        summary["stopped_reason"] = result.stopped_reason
        summary["turns"] = result.turns
        summary["run_cost_usd"] = getattr(loop, "_run_cost_usd", None)
        text = (result.final_response.text or "").strip()
        summary["assistant_preview"] = text[:1200]
        summary["assistant_len"] = len(text)
        errish = any(
            m in text
            for m in (
                "invalid_request_error",
                "ImportError",
                "anthropic 400",
                "chat_stream failed",
                "✖",
            )
        )
        summary["report_paths"] = _find_reports(PILOT_DIR, str(trace_id))
        summary["findings_hint"] = _findings_hint(PILOT_DIR, str(trace_id))
        summary["ok"] = (
            (not errish)
            and bool(text)
            and "论文论文" not in text
            and result.stopped_reason
            in ("end_turn", "stop", "cost_cap", "max_steps", "no_progress")
        )
        # Strong success: new report under this trace_id
        if any(str(trace_id) in p for p in summary["report_paths"]):
            summary["ok"] = not errish
        if errish:
            summary["error"] = "assistant text looks like transport/API error"
    except Exception as exc:
        summary["agent_seconds"] = round(time.time() - t1, 2)
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["ok"] = False

    path = _save(summary, run_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n# wrote {path}")
    return 0 if summary.get("ok") else 1


def _slim_ingest(data: dict) -> dict:
    out = {}
    for k in ("ok", "trace_id", "path", "error", "error_kind", "data_sources"):
        if k in data:
            out[k] = data[k]
    if not out and isinstance(data.get("result"), dict):
        return _slim_ingest(data["result"])
    return out or {"keys": list(data.keys())[:12]}


def _extract_trace_id(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    for k in ("trace_id", "job_id"):
        if data.get(k):
            return str(data[k])
    r = data.get("result")
    if isinstance(r, dict):
        return _extract_trace_id(r)
    return None


def _find_reports(workspace: Path, trace_id: str) -> list[str]:
    found: list[str] = []
    # Only this job's reports (avoid older pilot false positives).
    for pattern in (
        f"**/{trace_id}/**/report.html",
        f"**/{trace_id}/report.html",
        f"**/{trace_id}/**/report.md",
    ):
        for p in workspace.glob(pattern):
            if p.is_file() and trace_id in str(p):
                found.append(str(p.resolve()))
    return sorted(set(found))[:8]


def _findings_hint(workspace: Path, trace_id: str) -> dict:
    for p in workspace.glob(f"**/{trace_id}/**/findings.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {"path": str(p), "count": len(data)}
            if isinstance(data, dict) and "findings" in data:
                return {
                    "path": str(p),
                    "count": len(data.get("findings") or []),
                }
            return {"path": str(p), "type": type(data).__name__}
        except Exception as exc:  # noqa: BLE001
            return {"path": str(p), "error": str(exc)}
    return {}


def _save(summary: dict, run_id: str) -> Path:
    path = PILOT_DIR / f"{run_id}.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


if __name__ == "__main__":
    raise SystemExit(main())
