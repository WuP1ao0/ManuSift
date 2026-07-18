"""MCP stdio end-to-end regression test.

Spawns the real server (``python -m manusift.mcp``) via the official
MCP SDK client and checks the contract external agents rely on:
initialize -> tools/list -> tools/call on a real PDF, the P3 product
surface (submit_screen -> get_job_status -> get_job_result and the
synchronous screen_verdict on a tiny generated PDF), plus the
unknown-tool error path.

Kept separate from scripts/check_mcp_stdio.py so CI catches breakage;
marked slow-ish (subprocess + ingest of a real PDF, a few seconds).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# See scripts/check_mcp_stdio.py (GBK stderr forwarding crash).
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pytest

ROOT = Path(__file__).resolve().parent.parent
PDF = (
    ROOT / "benchmarks" / "fraud_web_v1" / "cases" / "clinical_medicine"
    / "web_bmj_01_acupuncture_low_back_or_pelvic_pain_duri" / "paper.pdf"
)

pytestmark = pytest.mark.skipif(
    not PDF.exists(), reason="benchmark PDF not present"
)


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    # See scripts/check_mcp_stdio.py: force UTF-8 stdio on Windows.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _stdio_params(env: dict[str, str]):
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "python.exe"),
        args=["-m", "manusift.mcp"],
        cwd=str(ROOT),
        env=env,
        encoding="utf-8",
        encoding_error_handler="replace",
    )


def _make_tiny_pdf(path: Path) -> None:
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((40, 40), "ManuSift MCP contract check.")
    doc.save(str(path))
    doc.close()


def test_mcp_stdio_end_to_end() -> None:
    async def _run() -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(_stdio_params(_child_env())) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [t.name for t in tools.tools]
                assert "ingest_from_path" in names
                assert "pdf_metadata" in names
                # curated surface: ~40 tools, not the full 73 dump
                assert len(names) < 60

                r = await session.call_tool(
                    "ingest_from_path", {"path": str(PDF)}
                )
                ingest = json.loads(r.content[0].text)
                trace_id = ingest.get("trace_id") or ingest.get(
                    "job", {}
                ).get("trace_id")
                assert trace_id, f"no trace_id in ingest: {r.content[0].text[:300]}"

                r2 = await session.call_tool(
                    "pdf_metadata", {"trace_id": trace_id}
                )
                assert r2.content[0].text.strip()

                r3 = await session.call_tool("no_such_tool", {})
                assert "unknown_tool" in r3.content[0].text

    asyncio.run(_run())


def test_mcp_stdio_screen_chain(tmp_path: Path) -> None:
    """P3 product surface over stdio: async submit -> poll -> result,
    synchronous screen_verdict, and the async error paths.

    Runs the real pipeline on a tiny generated PDF in a throwaway
    workspace, offline (no LLM, no Crossref, no EasyOCR detectors).
    """

    async def _run() -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        tiny_pdf = tmp_path / "tiny.pdf"
        _make_tiny_pdf(tiny_pdf)

        env = _child_env()
        env["MANUSIFT_WORKSPACE_DIR"] = str(tmp_path / "jobs")
        env["MANUSIFT_LLM_MAX_CONCURRENCY"] = "0"
        env["MANUSIFT_CROSSREF_ENABLED"] = "0"
        # EasyOCR figure detectors are far too slow for a test.
        env["MANUSIFT_BENCHMARK_SKIP_DETECTORS"] = (
            "figure_stat_text,figure_grim"
        )

        async with stdio_client(_stdio_params(env)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = [t.name for t in (await session.list_tools()).tools]
                for t in (
                    "screen_verdict",
                    "submit_screen",
                    "get_job_status",
                    "get_job_result",
                ):
                    assert t in names, f"{t} missing from MCP surface"

                # --- async chain: submit -> poll -> result ---------
                sub = json.loads(
                    (
                        await session.call_tool(
                            "submit_screen", {"path": str(tiny_pdf)}
                        )
                    ).content[0].text
                )
                job_id = sub.get("job_id")
                assert job_id and sub.get("status") == "queued", sub

                progress_series: list[int] = []
                final: dict = {}
                deadline = time.time() + 300
                while time.time() < deadline:
                    st = json.loads(
                        (
                            await session.call_tool(
                                "get_job_status", {"job_id": job_id}
                            )
                        ).content[0].text
                    )
                    assert st.get("job_id") == job_id, st
                    progress_series.append(int(st.get("progress_pct", 0)))
                    if st.get("status") in ("done", "failed"):
                        final = st
                        break
                    await asyncio.sleep(0.5)
                assert final.get("status") == "done", final
                # progress is monotonic non-decreasing across polls
                assert progress_series == sorted(progress_series), (
                    progress_series
                )
                assert final.get("progress_pct") == 100

                verdict = json.loads(
                    (
                        await session.call_tool(
                            "get_job_result", {"job_id": job_id}
                        )
                    ).content[0].text
                )
                _assert_verdict(verdict, trace_id=job_id)

                # unknown job id -> typed error, not a crash
                ru = await session.call_tool(
                    "get_job_status", {"job_id": "nosuchjob001"}
                )
                assert "unknown_job" in ru.content[0].text

                # --- synchronous one-call verdict -------------------
                sync_verdict = json.loads(
                    (
                        await session.call_tool(
                            "screen_verdict", {"path": str(tiny_pdf)}
                        )
                    ).content[0].text
                )
                _assert_verdict(sync_verdict)

    asyncio.run(_run())


def _assert_verdict(v: dict, *, trace_id: str | None = None) -> None:
    assert v.get("verdict") in ("clean", "suspect", "flagged"), v
    assert 0.0 <= float(v.get("score", -1)) <= 1.0, v
    assert isinstance(v.get("top_issues"), list), v
    counts = v.get("counts_by_severity") or {}
    for sev in ("high", "medium", "low", "info"):
        assert sev in counts, v
    assert v.get("report_path"), v
    if trace_id is not None:
        assert v.get("trace_id") == trace_id, v
