"""Deep integrity screen for a PDF (+ companion source data).

Usage (repo root, venv)::

    python scripts/pilot_deep_screen.py \\
      --pdf path\\to\\paper.pdf \\
      --data-paths path\\to\\folder \\
      [--trace-id EXISTING] \\
      [--si-pdf path\\to\\SI.pdf]

If ``--trace-id`` is set and the job dir exists under workspace, skip
re-ingest and continue screening that job.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = ROOT / "data" / "pilot_jobs"

# Expanded but still under schema-size risk for DeepSeek (~30 tools).
DEEP_TOOLS = {
    # workspace / IO
    "ingest_from_path",
    "list_dir",
    "list_data_sources",
    "read_data_source",
    "list_findings",
    "read_finding",
    "read_file",
    "bash",
    # metadata / text / refs
    "metadata",
    "pdf_metadata",
    "text_patterns",
    "text_tortured_phrases",
    "ref_duplicate",
    "ref_format_anomaly",
    "paper_mill_authorship",
    "paper_mill_template",
    "compliance",
    "data_availability_concern",
    "supplementary",
    # images / panels
    "image_dup",
    "image_forensics",
    "image_noise_inconsistency",
    "image_sift_copymove",
    "image_ssim",
    "image_statistics",
    "imagehash_phash",
    "panel_dup",
    "panel_duplicate",
    "page_raster_dup",
    "ai_generated_figure",
    # stats / figures / tables
    "stat_grim",
    "stat_pvalue",
    "stat_percent",
    "figure_grim",
    "figure_stat_text",
    "figure_table_consistency",
    "table_benford",
    "table_duplicate_row",
    "table_outlier",
    "table_relationships",
    "table_round_bias",
    "table_near_duplicate_row",
    "table_cross_copy",
    "table_file_metadata",
    "table_forensics",
    "source_data_audit",
    "chart_data_extract",
    # report
    "render_report",
}

DEFAULT_PROMPT = """\
你是 ManuSift 深度诚信筛查代理。对这篇 Nature Nanotechnology 论文做**深度审查**（不是初筛）。

目标：尽量跑全与本稿相关的检测维度，交叉验证，最后出中文 HTML 报告。

必须覆盖（尽量并行/批量，避免空转重复同一工具）：
1) 元数据：metadata 与/或 pdf_metadata
2) 图像取证：image_dup + image_forensics；有可疑再补 image_noise_inconsistency / image_sift_copymove / panel_dup / panel_duplicate / page_raster_dup / ai_generated_figure
3) 源数据：list_data_sources；对关键表 source_data_audit 或 table_benford / table_duplicate_row / table_outlier / table_round_bias / table_relationships
4) 统计：stat_grim / figure_grim / figure_stat_text / figure_table_consistency（正文若有均值±SD/n）
5) 文本与引用：text_patterns 或 text_tortured_phrases；ref_duplicate
6) 合规/数据可得：compliance 或 data_availability_concern（可选）
7) render_report 生成中文 HTML，并在最终回复给出 report 的绝对路径

重点复核（上一轮初筛已提示）：
- Fig.S1a–S1f / Sfig.2 的 Benford 信号是否可由粒径/分箱数据解释
- Fig.4c / Fig.4e 小样本与表头重复
- 对 Fig.4 / Fig.6 及任何 image_dup 可疑对做 image_forensics

用中文写简短但结构化的结论：已检查项、高/中关注发现、可解释的假阳性、建议人工复核点。不要复读，不要无转。
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ManuSift deep screen pilot")
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--data-paths", nargs="*", default=None)
    p.add_argument("--si-pdf", type=Path, default=None, help="Optional SI PDF to note in prompt")
    p.add_argument("--trace-id", default=None, help="Reuse existing job if present")
    p.add_argument("--max-steps", type=int, default=28)
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = p.parse_args(argv)

    pdf = args.pdf if args.pdf.is_absolute() else (ROOT / args.pdf)
    if not pdf.is_file():
        print(json.dumps({"ok": False, "error": f"PDF missing: {pdf}"}, ensure_ascii=False))
        return 2

    PILOT_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["MANUSIFT_WORKSPACE_DIR"] = str(PILOT_DIR.resolve())
    os.environ.setdefault("MANUSIFT_AGENT_RUNTIME", "pydantic_ai")

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
    run_id = f"deep_{ts}"
    summary: dict = {
        "run_id": run_id,
        "mode": "deep",
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
        "workspace": str(PILOT_DIR.resolve()),
        "ok": False,
    }

    if type(client).__name__ == "MockLLM" or not client.is_available():
        summary["error"] = "LLM unavailable / Mock — check .env"
        _save(summary, run_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 3

    trace_id = args.trace_id
    job_dir = (PILOT_DIR / trace_id) if trace_id else None
    # Post-2026-07-18 layout: the uploaded PDF lives at
    # <job>/inputs/original.pdf (see manusift/workspace.py).
    if job_dir and job_dir.is_dir() and (job_dir / "inputs" / "original.pdf").is_file():
        summary["reuse_trace"] = True
        summary["ingest"] = {"ok": True, "trace_id": trace_id, "skipped": True}
        summary["ingest_seconds"] = 0.0
    else:
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
            resolved = []
            for raw in args.data_paths:
                dp = Path(raw)
                if not dp.is_absolute():
                    dp = ROOT / dp
                resolved.append(str(dp.resolve()))
            ingest_input["data_paths"] = resolved
            summary["data_paths"] = resolved
        ingest_raw = ingest.execute(ingest_input, ctx0)
        summary["ingest_seconds"] = round(time.time() - t0, 2)
        try:
            ingest_data = json.loads(ingest_raw)
        except Exception:
            ingest_data = {"raw": str(ingest_raw)[:800]}
        summary["ingest"] = _slim_ingest(ingest_data)
        trace_id = _extract_trace_id(ingest_data) or run_id
        summary["reuse_trace"] = False

    summary["trace_id"] = str(trace_id)

    all_tools = list(iter_registered_tools())
    tools = [t for t in all_tools if getattr(t, "name", "") in DEEP_TOOLS]
    if not tools:
        tools = all_tools
    summary["tool_count"] = len(tools)
    summary["tool_names"] = sorted(getattr(t, "name", "?") for t in tools)

    agent_ctx = ToolContext(
        trace_id=str(trace_id),
        current_pdf=str(pdf.resolve()),
        metadata={
            "session_id": run_id,
            "pilot": True,
            "deep_screen": True,
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
        max_cost_usd=0,
    )

    si_note = ""
    if args.si_pdf:
        si = args.si_pdf if args.si_pdf.is_absolute() else (ROOT / args.si_pdf)
        if si.is_file():
            si_note = (
                f"\n补充材料 SI PDF（如需可 list_dir/read 旁证，优先主 PDF+xlsx）："
                f"{si.resolve()}\n"
            )
            summary["si_pdf"] = str(si.resolve())

    user_msg = (
        f"PDF 路径: {pdf.resolve()}\n"
        f"trace_id: {trace_id}\n"
        f"深度筛查模式。workspace: {PILOT_DIR.resolve()}\n"
        f"{si_note}"
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
        summary["assistant_preview"] = text[:2000]
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
            and result.stopped_reason
            in ("end_turn", "stop", "max_steps", "no_progress")
        )
        if any(str(trace_id) in p for p in summary["report_paths"]):
            summary["ok"] = not errish
        if errish:
            summary["error"] = "assistant text looks like transport/API error"
    except Exception as exc:  # noqa: BLE001
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
    for pattern in (
        f"**/{trace_id}/**/report*.html",
        f"**/{trace_id}/report*.html",
        f"**/{trace_id}/**/report*.md",
        f"**/{trace_id}/report*.md",
    ):
        for p in workspace.glob(pattern):
            if p.is_file() and trace_id in str(p):
                found.append(str(p.resolve()))
    return sorted(set(found))[:12]


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
