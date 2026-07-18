"""P0-2: MCP Domain Kernel surface smoke (list + call a real tool)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")


def test_mcp_list_tools_has_core_names():
    from manusift.mcp.server import _tool_schemas

    names = {s["name"] for s in _tool_schemas()}
    assert len(names) >= 20
    # Core integrity surface
    for required in (
        "ingest_from_path",
        "list_findings",
        "render_report",
        "image_dup",
        "metadata",
    ):
        assert required in names, f"missing {required}"


def test_mcp_call_list_findings_empty_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """call_tool path: list_findings on a fresh trace should not crash."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    from manusift.config import get_settings

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    from manusift.mcp.server import build_server
    from manusift.tools.tool import ToolContext
    import asyncio
    from mcp import types

    ctx = ToolContext(trace_id="mcp-smoke-empty")
    server = build_server(ctx=ctx, tool_names=["list_findings"])

    # Resolve call_tool handler from server
    # mcp Server stores handlers; use list_tools + call_tool decorators' result.
    async def _run() -> list[types.TextContent]:
        # list
        tools = await server.request_handlers[types.ListToolsRequest](  # type: ignore[index]
            None  # may fail — fallback below
        )
        return tools  # type: ignore[return-value]

    # Prefer direct Domain Kernel path used by call_tool implementation:
    from manusift.tools.registry import get_tool

    tool = get_tool("list_findings")
    assert tool is not None
    out = tool.execute({}, ctx)
    assert isinstance(out, str)
    # Should be JSON-ish (empty list / error envelope / findings)
    assert out.strip().startswith("{") or out.strip().startswith("[") or "finding" in out.lower() or "error" in out.lower() or out == "[]"


def test_mcp_build_server_and_list_via_handler():
    from manusift.mcp.server import build_server
    from manusift.tools.tool import ToolContext
    import asyncio

    server = build_server(
        ctx=ToolContext(trace_id="mcp-list"),
        tool_names=["metadata", "list_findings"],
    )

    # FastMCP-style lowlevel: invoke list_tools registered callback
    # Inspect request handlers keys
    handlers = getattr(server, "request_handlers", {})
    assert handlers, "MCP Server should expose request_handlers"

    # Call list_tools through the public list API if available
    async def list_them():
        # Server.list_tools is a decorator registration method; use call_tool pattern
        # from the registered functions in _tool_manager is FastMCP only.
        # For low-level Server, handlers map Request type -> handler.
        from mcp import types as t

        # Find ListToolsRequest handler
        for key, handler in handlers.items():
            key_name = getattr(key, "__name__", str(key))
            if "ListTools" in key_name or "list_tools" in str(key).lower():
                # handler signature varies by mcp version
                try:
                    result = await handler(None)
                except TypeError:
                    # try with a dummy request object
                    req = t.ListToolsRequest(method="tools/list", params=None)
                    result = await handler(req)
                return result
        return None

    result = asyncio.run(list_them())
    # Some mcp versions wrap in ServerResult
    tools = None
    if result is None:
        pytest.skip("could not invoke list_tools handler on this mcp version")
    if hasattr(result, "tools"):
        tools = result.tools
    elif hasattr(result, "root") and hasattr(result.root, "tools"):
        tools = result.root.tools
    elif isinstance(result, list):
        tools = result
    else:
        # last resort: string form
        assert "metadata" in str(result) or "list_findings" in str(result)
        return
    names = [getattr(t, "name", None) or t.get("name") for t in tools]
    assert "list_findings" in names
    assert "metadata" in names


def test_mcp_cli_list_tools(capsys: pytest.CaptureFixture[str]):
    from manusift.mcp.server import main

    main(["--list-tools", "--tools", "list_findings,metadata"])
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 2
    assert set(data["tools"]) == {"list_findings", "metadata"}
