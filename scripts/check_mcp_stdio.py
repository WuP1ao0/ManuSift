"""End-to-end MCP stdio session check (manual + CI).

Spawns ``python -m manusift.mcp`` over stdio via the official MCP SDK
client, performs initialize -> tools/list -> tools/call
(ingest_from_path + pdf_metadata on a real benchmark PDF), then
exercises the P3 product surface: the asynchronous chain
submit_screen -> get_job_status (progress monotonicity) ->
get_job_result and the synchronous screen_verdict, both on a tiny
generated PDF, plus the unknown-tool error path. Asserts the contract
other agents (Claude Code, Codex, ...) will rely on.

Run:  .venv\\Scripts\\python.exe scripts/check_mcp_stdio.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# The MCP SDK forwards child stderr to sys.stderr; on Windows the
# default GBK codepage crashes the forwarding task on UTF-8 logs.
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PDF = (
    ROOT / "benchmarks" / "fraud_web_v1" / "cases" / "clinical_medicine"
    / "web_bmj_01_acupuncture_low_back_or_pelvic_pain_duri" / "paper.pdf"
)

SCREEN_TOOLS = ("screen_verdict", "submit_screen", "get_job_status", "get_job_result")


def _make_tiny_pdf(path: Path) -> None:
    """One-page PDF: the pipeline runs in seconds, no heavy OCR."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((40, 40), "ManuSift MCP contract check.")
    doc.save(str(path))
    doc.close()


def _assert_verdict_payload(v: dict, *, trace_id: str | None = None) -> None:
    assert v.get("verdict") in ("clean", "suspect", "flagged"), v
    assert 0.0 <= float(v.get("score", -1)) <= 1.0, v
    assert isinstance(v.get("top_issues"), list), v
    counts = v.get("counts_by_severity") or {}
    for sev in ("high", "medium", "low", "info"):
        assert sev in counts, v
    assert v.get("report_path"), v
    if trace_id is not None:
        assert v.get("trace_id") == trace_id, v


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    tmp = Path(tempfile.mkdtemp(prefix="manusift-mcp-check-"))
    tiny_pdf = tmp / "tiny.pdf"
    _make_tiny_pdf(tiny_pdf)

    env = dict(os.environ)
    # Force UTF-8 in the child: on Windows the MCP SDK decodes the
    # child's stdio with the system codepage (GBK here) and chokes
    # on the UTF-8 arrows/CJK in our instructions/payloads.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # Screen jobs write into a throwaway workspace, never touch
    # data/jobs; the contract run stays offline and LLM-free.
    env["MANUSIFT_WORKSPACE_DIR"] = str(tmp / "jobs")
    env["MANUSIFT_LLM_MAX_CONCURRENCY"] = "0"
    env["MANUSIFT_CROSSREF_ENABLED"] = "0"
    # EasyOCR figure detectors are far too slow for a contract check.
    env["MANUSIFT_BENCHMARK_SKIP_DETECTORS"] = "figure_stat_text,figure_grim"
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "manusift.mcp"],
        cwd=str(ROOT),
        env=env,
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[mcp] {len(names)} tools:", names[:8], "...")
            assert "ingest_from_path" in names
            assert "pdf_metadata" in names
            for t in SCREEN_TOOLS:
                assert t in names, f"{t} missing from MCP surface"

            # ingest a real PDF
            r = await session.call_tool(
                "ingest_from_path", {"path": str(PDF)}
            )
            ingest_text = r.content[0].text
            print("[mcp] ingest ->", ingest_text[:200])
            ingest = json.loads(ingest_text)
            trace_id = ingest.get("trace_id") or ingest.get("job", {}).get("trace_id")
            assert trace_id, f"no trace_id in ingest result: {ingest_text[:300]}"

            # pdf_metadata on the ingested trace
            r2 = await session.call_tool(
                "pdf_metadata", {"trace_id": trace_id}
            )
            meta_text = r2.content[0].text
            print("[mcp] pdf_metadata ->", meta_text[:200])
            assert meta_text.strip(), "empty pdf_metadata result"

            # --- P3.2 async chain: submit -> poll -> result ---------
            r3 = await session.call_tool(
                "submit_screen", {"path": str(tiny_pdf)}
            )
            sub = json.loads(r3.content[0].text)
            print("[mcp] submit_screen ->", r3.content[0].text[:200])
            job_id = sub.get("job_id")
            assert job_id and sub.get("status") == "queued", sub

            progress_series: list[int] = []
            final: dict = {}
            deadline = time.time() + 300
            while time.time() < deadline:
                rs = await session.call_tool(
                    "get_job_status", {"job_id": job_id}
                )
                st = json.loads(rs.content[0].text)
                assert st.get("job_id") == job_id, st
                progress_series.append(int(st.get("progress_pct", 0)))
                if st.get("status") in ("done", "failed"):
                    final = st
                    break
                await asyncio.sleep(0.5)
            print(
                "[mcp] job progress:", progress_series,
                "final:", final.get("status"), final.get("stage"),
            )
            assert final.get("status") == "done", final
            # progress is monotonic non-decreasing across polls
            assert progress_series == sorted(progress_series), progress_series
            assert final.get("progress_pct") == 100

            rr = await session.call_tool(
                "get_job_result", {"job_id": job_id}
            )
            verdict = json.loads(rr.content[0].text)
            print("[mcp] get_job_result ->", rr.content[0].text[:200])
            _assert_verdict_payload(verdict, trace_id=job_id)

            # unknown job id -> typed error, not a crash
            ru = await session.call_tool(
                "get_job_status", {"job_id": "nosuchjob001"}
            )
            assert "unknown_job" in ru.content[0].text

            # --- P3.1 synchronous one-call verdict ------------------
            rv = await session.call_tool(
                "screen_verdict", {"path": str(tiny_pdf)}
            )
            sync_verdict = json.loads(rv.content[0].text)
            print("[mcp] screen_verdict ->", rv.content[0].text[:200])
            _assert_verdict_payload(sync_verdict)

            # unknown tool must return error payload, not crash
            r9 = await session.call_tool("no_such_tool", {})
            assert "unknown_tool" in r9.content[0].text
    print(
        "[mcp] OK: stdio session, tool list, ingest, pdf_metadata, "
        "async screen chain, sync screen_verdict, error paths"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
