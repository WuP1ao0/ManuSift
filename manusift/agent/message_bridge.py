"""Convert between ManuSift chat dicts and PydanticAI message parts.

ManuSift's LLM client speaks a normalized Anthropic-like dict format
(``role`` + ``content`` / content blocks). PydanticAI uses typed
``ModelRequest`` / ``ModelResponse`` trees. This module is the only
place that knows both shapes.
"""
from __future__ import annotations

from typing import Any

from ..llm.chat import ChatResponse


def chat_response_to_model_response(resp: ChatResponse) -> Any:
    """Map a ManuSift ``ChatResponse`` to a PydanticAI ``ModelResponse``."""
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

    parts: list[Any] = []
    for block in resp.content_blocks or []:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if text:
                parts.append(TextPart(content=str(text)))
        elif btype == "tool_use":
            args = block.get("input") or {}
            if not isinstance(args, dict):
                args = {"value": args}
            parts.append(
                ToolCallPart(
                    tool_name=str(block.get("name") or "tool"),
                    args=args,
                    tool_call_id=str(block.get("id") or ""),
                )
            )
    if not parts:
        # PydanticAI rejects empty ModelResponse parts / empty text
        # ("Please return text or call a tool"). Emit a minimal done marker.
        parts.append(TextPart(content="(done)"))
    else:
        # Empty-string-only text responses also trigger output retries.
        only_empty_text = all(
            type(p).__name__ == "TextPart"
            and not (getattr(p, "content", None) or "").strip()
            for p in parts
        )
        if only_empty_text:
            parts = [TextPart(content="(done)")]
    return ModelResponse(parts=parts)


def model_response_to_chat_response(resp: Any) -> ChatResponse:
    """Map a PydanticAI ``ModelResponse`` to ManuSift ``ChatResponse``."""
    blocks: list[dict[str, Any]] = []
    for part in getattr(resp, "parts", []) or []:
        kind = getattr(part, "part_kind", None) or type(part).__name__
        if kind == "text" or type(part).__name__ == "TextPart":
            blocks.append(
                {"type": "text", "text": str(getattr(part, "content", "") or "")}
            )
        elif kind == "tool-call" or type(part).__name__ == "ToolCallPart":
            args = getattr(part, "args", {}) or {}
            if isinstance(args, str):
                import json as _json

                try:
                    args = _json.loads(args)
                except Exception:  # noqa: BLE001
                    args = {"raw": args}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(getattr(part, "tool_call_id", "") or ""),
                    "name": str(getattr(part, "tool_name", "") or ""),
                    "input": args if isinstance(args, dict) else {"value": args},
                }
            )
    usage: dict[str, Any] = {}
    u = getattr(resp, "usage", None)
    if u is not None:
        try:
            usage = {
                "input_tokens": getattr(u, "input_tokens", 0) or 0,
                "output_tokens": getattr(u, "output_tokens", 0) or 0,
            }
        except Exception:  # noqa: BLE001
            usage = {}
    has_tools = any(b.get("type") == "tool_use" for b in blocks)
    return ChatResponse(
        content_blocks=blocks,
        stop_reason="tool_use" if has_tools else "end_turn",
        usage=usage,
        model=str(getattr(resp, "model_name", "") or ""),
    )


def pydantic_history_to_manusift(
    messages: list[Any],
) -> list[dict[str, Any]]:
    """Flatten a PydanticAI message list into ManuSift client messages.

    System prompts are emitted as ``role=system``; user prompts as
    ``role=user``; model responses as assistant content blocks;
    tool returns as Anthropic-style ``tool_result`` user content.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        kind = getattr(msg, "kind", None) or type(msg).__name__
        parts = list(getattr(msg, "parts", []) or [])
        if kind == "request" or type(msg).__name__ == "ModelRequest":
            # May mix system, user, and tool-return parts.
            system_chunks: list[str] = []
            user_chunks: list[str] = []
            tool_results: list[dict[str, Any]] = []
            for part in parts:
                pk = getattr(part, "part_kind", None) or type(part).__name__
                if pk in ("system-prompt", "SystemPromptPart"):
                    system_chunks.append(str(getattr(part, "content", "") or ""))
                elif pk in ("user-prompt", "UserPromptPart"):
                    content = getattr(part, "content", "")
                    if isinstance(content, str):
                        user_chunks.append(content)
                    else:
                        user_chunks.append(str(content))
                elif pk in ("tool-return", "ToolReturnPart"):
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": str(
                                getattr(part, "tool_call_id", "") or ""
                            ),
                            "content": str(getattr(part, "content", "") or ""),
                        }
                    )
                elif pk in ("retry-prompt", "RetryPromptPart"):
                    user_chunks.append(str(getattr(part, "content", "") or ""))
            for s in system_chunks:
                if s:
                    out.append({"role": "system", "content": s})
            if tool_results:
                out.append({"role": "user", "content": tool_results})
            if user_chunks:
                out.append({"role": "user", "content": "\n".join(user_chunks)})
        elif kind == "response" or type(msg).__name__ == "ModelResponse":
            blocks: list[dict[str, Any]] = []
            for part in parts:
                pk = getattr(part, "part_kind", None) or type(part).__name__
                if pk in ("text", "TextPart"):
                    blocks.append(
                        {
                            "type": "text",
                            "text": str(getattr(part, "content", "") or ""),
                        }
                    )
                elif pk in ("tool-call", "ToolCallPart"):
                    args = getattr(part, "args", {}) or {}
                    if isinstance(args, str):
                        import json as _json

                        try:
                            args = _json.loads(args)
                        except Exception:  # noqa: BLE001
                            args = {"raw": args}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(getattr(part, "tool_call_id", "") or ""),
                            "name": str(getattr(part, "tool_name", "") or ""),
                            "input": args
                            if isinstance(args, dict)
                            else {"value": args},
                        }
                    )
            if blocks:
                out.append({"role": "assistant", "content": blocks})
    return out


def prior_messages_to_pydantic(
    prior_messages: list[dict[str, Any]] | None,
) -> list[Any]:
    """Convert ManuSift prior chat turns into PydanticAI message objects.

    Only plain user/assistant text turns are replayed (same filter
    contract as the TUI history filter). Tool JSON blobs are skipped.
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    if not prior_messages:
        return []
    out: list[Any] = []
    for m in prior_messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "user" and isinstance(content, str) and content.strip():
            out.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant" and isinstance(content, str) and content.strip():
            out.append(ModelResponse(parts=[TextPart(content=content)]))
        elif role == "assistant" and isinstance(content, list):
            text_bits = [
                str(b.get("text", ""))
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "".join(text_bits).strip()
            if joined:
                out.append(ModelResponse(parts=[TextPart(content=joined)]))
    return out


def function_tools_to_schemas(info: Any) -> list[dict[str, Any]]:
    """Extract OpenAI/Anthropic tool schemas from ``AgentInfo``."""
    schemas: list[dict[str, Any]] = []
    for t in getattr(info, "function_tools", None) or []:
        schemas.append(
            {
                "name": getattr(t, "name", "tool"),
                "description": getattr(t, "description", "") or "",
                "input_schema": getattr(t, "parameters_json_schema", None)
                or {"type": "object", "properties": {}},
            }
        )
    return schemas
