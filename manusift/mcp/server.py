"""MCP server: expose ManuSift tools over stdio (Domain Kernel only).

The agent loop is intentionally *not* started here. Clients supply an
LLM; this process only executes local tools against a ``ToolContext``.

Usage::

    manusift-mcp
    # or
    python -m manusift.mcp

Claude Desktop / Cursor config (stdio)::

    {
      "command": "manusift-mcp",
      "args": [],
      "env": {"MANUSIFT_WORKSPACE_DIR": "..."}
    }
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid
from typing import Any

from ..tools import ToolContext, iter_registered_tools
from ..tools.registry import get_tool

log = logging.getLogger(__name__)


def _silence_stdout_leaks() -> None:
    """Keep library chatter off the JSON-RPC channel (stdout).

    PyMuPDF prints a one-time "Consider using pymupdf_layout..."
    promo via Python print() on first PDF use; other deps may print
    too. Two layers: (1) disable the known promo at startup, (2)
    redirect stdout to stderr around every tool execution in
    ``call_tool`` (the MCP transport holds the original
    ``sys.stdout.buffer`` captured at ``stdio_server()`` time, so
    the protocol channel is unaffected).
    """
    try:
        import pymupdf

        pymupdf.no_recommend_layout()
    except Exception:  # noqa: BLE001
        pass
    # Eager-import the heavy native chain on the main thread,
    # BEFORE asyncio/anyio worker threads exist: lazy native
    # imports (numpy/scipy C extensions via imagehash <-
    # manusift.ingest.pdf) deadlock at create_module once the
    # MCP loop is running on Windows (confirmed twice via
    # faulthandler dumps). Importing everything here -- while
    # the process is still single-threaded -- makes all later
    # in-loop imports plain sys.modules cache hits.
    for _mod in (
        "numpy",
        "scipy",
        "scipy.fft",
        "scipy.special",
        "imagehash",
        "cv2",
        "skimage",
        "torch",
        "easyocr",
    ):
        try:
            __import__(_mod)
        except Exception:  # noqa: BLE001
            pass
    if os.environ.get("MANUSIFT_MCP_DEBUG"):
        import faulthandler

        faulthandler.dump_traceback_later(15, repeat=True)


def _tool_schemas() -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for tool in iter_registered_tools():
        try:
            name = str(getattr(tool, "name", "") or "")
            if not name:
                continue
            desc = ""
            try:
                desc = str(tool.description() or "")
            except Exception:  # noqa: BLE001
                desc = name
            schema: dict[str, Any]
            try:
                raw = tool.input_schema()
                schema = raw if isinstance(raw, dict) else {
                    "type": "object",
                    "properties": {},
                }
            except Exception:  # noqa: BLE001
                schema = {"type": "object", "properties": {}}
            if schema.get("type") != "object":
                schema = {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                }
            schemas.append(
                {
                    "name": name,
                    "description": desc,
                    "inputSchema": schema,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "skip tool for MCP",
                extra={"err": str(exc)},
            )
    return schemas


def _default_ctx(trace_id: str | None = None) -> ToolContext:
    tid = trace_id or f"mcp-{uuid.uuid4().hex[:12]}"
    return ToolContext(trace_id=tid, metadata={"source": "mcp"})


def build_server(
    *,
    ctx: ToolContext | None = None,
    tool_names: list[str] | None = None,
) -> Any:
    """Build a low-level MCP ``Server`` exposing Domain Kernel tools."""
    from mcp import types
    from mcp.server import Server

    base_ctx = ctx or _default_ctx()
    allowed = set(tool_names) if tool_names else None

    all_schemas = _tool_schemas()
    if allowed is not None:
        all_schemas = [s for s in all_schemas if s["name"] in allowed]

    server = Server(
        "manusift",
        version="0.1.0",
        instructions=(
            "ManuSift Domain Kernel (product B+C: batch + MCP tools). "
            "No conversational agent. Fast path: screen_verdict(path) "
            "for a one-call triage verdict, or submit_screen(path) -> "
            "get_job_status(job_id) -> get_job_result(job_id) for "
            "large PDFs. Raw-detect workflow: "
            "1) ingest_from_path(path, data_paths?) → trace_id; "
            "2) list_data_sources / source_data_audit as needed; "
            "3) image_forensics + table_forensics (or finer detectors); "
            "4) render_report. Always pass trace_id on subsequent calls."
        ),
    )

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=s["name"],
                description=s.get("description") or s["name"],
                inputSchema=s.get("inputSchema")
                or {"type": "object", "properties": {}},
            )
            for s in all_schemas
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any] | None
    ) -> list[types.TextContent]:
        args = dict(arguments or {})
        # Allow callers to pin/override trace_id per call.
        trace_id = args.pop("trace_id", None) or base_ctx.trace_id
        run_ctx = ToolContext(
            trace_id=str(trace_id),
            current_pdf=base_ctx.current_pdf,
            metadata=dict(base_ctx.metadata) if base_ctx.metadata else {},
        )
        tool = get_tool(name)
        if tool is None:
            # Fallback: scan registry (get_tool may miss builtins).
            for t in iter_registered_tools():
                if getattr(t, "name", None) == name:
                    tool = t
                    break
        if tool is None:
            payload = {"error": "unknown_tool", "name": name}
            return [
                types.TextContent(
                    type="text", text=json.dumps(payload, ensure_ascii=False)
                )
            ]
        try:
            # Library prints (e.g. the PyMuPDF layout promo) must
            # never reach the JSON-RPC channel: redirect Python-level
            # stdout to stderr for the duration of the tool call.
            # The MCP transport writes protocol frames via the
            # original sys.stdout.buffer captured at startup, so it
            # is unaffected by this swap.
            #
            # ALSO: run execute in a worker thread, not the loop
            # thread -- lazy C-extension imports (numpy/scipy via
            # imagehash) deadlock at create_module when triggered
            # inside the ProactorEventLoop thread on Windows, and a
            # heavy parse would stall the whole server anyway.
            import os as _os
            if _os.environ.get("MANUSIFT_MCP_DEBUG"):
                print(f"[mcp-debug] execute start {name}", file=sys.stderr, flush=True)
            def _run() -> str:
                with contextlib.redirect_stdout(sys.stderr):
                    return tool.execute(args, run_ctx)
            result = await asyncio.to_thread(_run)
            if _os.environ.get("MANUSIFT_MCP_DEBUG"):
                print(f"[mcp-debug] execute done {name}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            result = json.dumps(
                {
                    "error": "tool_crashed",
                    "name": name,
                    "detail": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            )
        if not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False, default=str)
            except Exception:  # noqa: BLE001
                result = str(result)
        return [types.TextContent(type="text", text=result)]

    return server


async def _run_stdio(server: Any) -> None:
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="manusift-mcp",
        description="Expose ManuSift Domain Kernel tools over MCP (stdio).",
    )
    parser.add_argument(
        "--trace-id",
        default=None,
        help="Default trace_id / job workspace key for tool calls.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print registered tool names as JSON and exit (no MCP session).",
    )
    parser.add_argument(
        "--tools",
        default=None,
        help=(
            "Comma-separated allow-list of tool names. "
            "Default: curated B+C kernel surface (see manusift.mcp.surface)."
        ),
    )
    parser.add_argument(
        "--all-tools",
        action="store_true",
        help="Expose every registered tool (large schema; not default).",
    )
    args = parser.parse_args(argv)

    if args.list_tools:
        names = [s["name"] for s in _tool_schemas()]
        if args.tools:
            allow = {t.strip() for t in args.tools.split(",") if t.strip()}
            names = [n for n in names if n in allow]
        elif not args.all_tools:
            from .surface import MCP_DEFAULT_TOOLS

            allow = set(MCP_DEFAULT_TOOLS)
            names = [n for n in names if n in allow]
        print(json.dumps({"tools": names, "count": len(names)}, indent=2))
        return

    allow = None
    if args.tools:
        allow = [t.strip() for t in args.tools.split(",") if t.strip()]
    elif not args.all_tools:
        from .surface import MCP_DEFAULT_TOOLS

        allow = list(MCP_DEFAULT_TOOLS)
    _silence_stdout_leaks()
    ctx = _default_ctx(args.trace_id)
    server = build_server(ctx=ctx, tool_names=allow)
    asyncio.run(_run_stdio(server))


if __name__ == "__main__":
    main()
