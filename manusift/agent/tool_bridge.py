"""Bridge ManuSift ``Tool`` Protocol objects into PydanticAI tools.

Domain Kernel tools keep their own ``name`` / ``description`` /
``input_schema`` / ``execute(input, ctx)`` surface. This module only
adapts that surface so PydanticAI can schedule and execute them.

Nothing in detectors, ingest, report, or workspace is imported here
beyond ``ToolContext`` typing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..tools.tool import Tool, ToolContext


@dataclass
class AgentDeps:
    """Per-run dependencies injected into every PydanticAI tool call.

    ``tool_context`` is the frozen Domain Kernel context. Callbacks
    are optional so pure headless runs (MCP, batch) need no TUI.
    ``tool_gate`` enforces legacy-style signature dedup + per-name /
    per-turn / bash caps when provided.
    """

    tool_context: ToolContext
    on_tool_result: Callable[[str, str, bool, str], None] | None = None
    tool_gate: Any | None = None
    # Mutable bag for counters shared across tool calls in one run.
    meta: dict[str, Any] = field(default_factory=dict)


def _safe_name(name: str) -> str:
    """PydanticAI / OpenAI tool names must be [a-zA-Z0-9_-]."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("_") or "tool"
    return cleaned[:64]


def manusift_tool_to_pydantic(tool: Tool) -> Any:
    """Wrap one ManuSift tool as a ``pydantic_ai.Tool``.

    Uses ``Tool.from_schema`` so the existing JSON Schema from
    ``tool.input_schema()`` is preserved without re-deriving types.
    """
    from pydantic_ai import RunContext, Tool as PydTool

    tool_name = _safe_name(getattr(tool, "name", "tool"))
    try:
        description = tool.description() or tool_name
    except Exception:  # noqa: BLE001
        description = tool_name
    try:
        schema = tool.input_schema() or {
            "type": "object",
            "properties": {},
        }
    except Exception:  # noqa: BLE001
        schema = {"type": "object", "properties": {}}
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    # Ensure object root — some detectors return only properties.
    if schema.get("type") != "object":
        schema = {
            "type": "object",
            "properties": schema.get("properties", schema),
        }

    def _handler(ctx: RunContext[AgentDeps], **kwargs: Any) -> str:
        deps = ctx.deps
        tc_id = ""
        # Prefer the active tool-call id from RunContext when available.
        try:
            tc_id = str(getattr(ctx, "tool_call_id", "") or "")
        except Exception:  # noqa: BLE001
            tc_id = ""
        raw_input = dict(kwargs) if kwargs else {}
        gate = deps.tool_gate
        if gate is not None:
            denied = gate.check(tool_name, raw_input)
            if denied:
                result = denied
                is_error = True
                if deps.on_tool_result is not None:
                    try:
                        deps.on_tool_result(
                            tool_name, result, is_error, tc_id
                        )
                    except Exception:  # noqa: BLE001
                        pass
                return result
        try:
            result = tool.execute(raw_input, deps.tool_context)
        except Exception as exc:  # noqa: BLE001
            result = (
                f'{{"error": "tool_crashed", '
                f'"tool": "{tool_name}", '
                f'"detail": "{type(exc).__name__}: {exc}"}}'
            )
            is_error = True
        else:
            if not isinstance(result, str):
                import json as _json

                try:
                    result = _json.dumps(result, ensure_ascii=False, default=str)
                except Exception:  # noqa: BLE001
                    result = str(result)
            is_error = False
            # Heuristic: Domain Kernel tools often return JSON with ok=false.
            low = result[:200].lower()
            if '"ok": false' in low or '"ok":false' in low or '"error"' in low[:40]:
                is_error = True
            if gate is not None and not is_error:
                try:
                    gate.record(tool_name, raw_input)
                except Exception:  # noqa: BLE001
                    pass
        if deps.on_tool_result is not None:
            try:
                deps.on_tool_result(tool_name, result, is_error, tc_id)
            except Exception:  # noqa: BLE001
                pass
        return result

    # Bind a stable __name__ so PydanticAI debug output is readable.
    _handler.__name__ = f"ms_{tool_name}"
    _handler.__doc__ = description

    return PydTool.from_schema(
        _handler,
        name=tool_name,
        description=description,
        json_schema=schema,
        takes_ctx=True,
    )


def build_pydantic_tools(tools: list[Any]) -> list[Any]:
    """Convert a list of ManuSift tools to PydanticAI tools.

    Skips tools that fail to adapt so one broken adapter cannot
    take down the whole agent surface.
    """
    out: list[Any] = []
    seen: set[str] = set()
    for tool in tools:
        try:
            pyd = manusift_tool_to_pydantic(tool)
        except Exception:  # noqa: BLE001
            continue
        name = getattr(pyd, "name", None) or getattr(tool, "name", "")
        if name in seen:
            continue
        seen.add(name)
        out.append(pyd)
    return out


def tools_to_openai_schemas(tools: list[Any]) -> list[dict[str, Any]]:
    """Provider-agnostic tool schemas for ManuSift ``client.chat``.

    Shape matches what ``AgentLoop`` / Anthropic client already expect:
    ``{name, description, input_schema}``.
    """
    schemas: list[dict[str, Any]] = []
    for tool in tools:
        try:
            name = getattr(tool, "name", "") or "tool"
            desc = tool.description() if hasattr(tool, "description") else ""
            schema = (
                tool.input_schema()
                if hasattr(tool, "input_schema")
                else {"type": "object", "properties": {}}
            )
        except Exception:  # noqa: BLE001
            continue
        schemas.append(
            {
                "name": _safe_name(str(name)),
                "description": str(desc or name),
                "input_schema": schema
                if isinstance(schema, dict)
                else {"type": "object", "properties": {}},
            }
        )
    return schemas
