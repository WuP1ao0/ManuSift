"""Agent loop with ManuSift ``AgentLoop`` surface.

Originally driven by PydanticAI's ``Agent`` + ``FunctionModel``. DeepSeek
thinking models require echoing ``thinking`` blocks and strict
``tool_use``/``tool_result`` pairing; round-tripping through Pydantic's
message model drops thinking and can mis-order multi-tool results
(→ 400 invalid_request_error).

This module keeps the public API and still uses:
  * ``tool_bridge`` / ``tools_to_openai_schemas`` for tool surface
  * ``system_prompt.build_system_prompt``
  * ``safety`` nets (cost / progress / tool caps)
  * stream fold for cumulative chat_stream snapshots

The ReAct driver itself is a **manual wire-format loop** (same shape as
legacy) so Anthropic-compatible providers receive valid multi-turn tool
histories including thinking blocks.
"""
from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..llm.chat import (
    ChatResponse,
    fold_stream_chunk,
    normalize_assistant_content_blocks,
)
from ..tools import ToolContext
from .safety import ProgressTracker, ToolCallGate
from .tool_bridge import build_pydantic_tools, tools_to_openai_schemas

log = logging.getLogger(__name__)


def _sanitize_messages_for_api(messages: list[dict[str, Any]]) -> None:
    """Fix history before each LLM call (DeepSeek/Anthropic wire rules).

    * assistant content: thinking → text → tool_use order
    * merge consecutive plain-string user messages (pre-canned notes)
    * close unpaired tool_use / tool_result pairs
    """
    # Merge consecutive user messages with string content.
    i = 0
    while i < len(messages) - 1:
        a, b = messages[i], messages[i + 1]
        if (
            a.get("role") == "user"
            and b.get("role") == "user"
            and isinstance(a.get("content"), str)
            and isinstance(b.get("content"), str)
        ):
            a["content"] = str(a["content"]) + "\n\n" + str(b["content"])
            del messages[i + 1]
            continue
        i += 1

    for m in messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if isinstance(content, list):
            m["content"] = normalize_assistant_content_blocks(
                [b for b in content if isinstance(b, dict)]
            )

    _close_unpaired_tool_uses(messages)


def _close_unpaired_tool_uses(messages: list[dict[str, Any]]) -> None:
    """Ensure every assistant tool_use has matching tool_result next.

    Mutates ``messages`` in place. Required by Anthropic/DeepSeek when
    history was corrupted or a prior turn aborted mid-tools.
    """
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") != "assistant":
            i += 1
            continue
        content = m.get("content")
        if not isinstance(content, list):
            i += 1
            continue
        need_ids = [
            str(b.get("id") or "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]
        need_ids = [x for x in need_ids if x]
        if not need_ids:
            i += 1
            continue
        # Collect tool_result ids from the immediately following user msg.
        have: set[str] = set()
        if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
            nxt = messages[i + 1].get("content")
            if isinstance(nxt, list):
                for b in nxt:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        tid = str(b.get("tool_use_id") or "")
                        if tid:
                            have.add(tid)
        missing = [tid for tid in need_ids if tid not in have]
        if not missing:
            i += 1
            continue
        synth = [
            {
                "type": "tool_result",
                "tool_use_id": tid,
                "content": json.dumps(
                    {
                        "error": "tool_result_missing",
                        "tool_use_id": tid,
                    },
                    ensure_ascii=False,
                ),
                "is_error": True,
            }
            for tid in missing
        ]
        if i + 1 < len(messages) and messages[i + 1].get("role") == "user":
            nxt = messages[i + 1].get("content")
            if isinstance(nxt, list):
                messages[i + 1]["content"] = list(nxt) + synth
            else:
                # Replace non-list user content with results only for pairing.
                messages.insert(
                    i + 1,
                    {"role": "user", "content": synth},
                )
        else:
            messages.insert(i + 1, {"role": "user", "content": synth})
        i += 2


@dataclass
class AgentLoopResult:
    """Same shape as the legacy ``AgentLoopResult``."""

    final_response: ChatResponse
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    stopped_reason: str = "end_turn"


class PydanticAgentLoop:
    """ReAct loop (wire-format) with AgentLoop-compatible API."""

    DEFAULT_MAX_STEPS = 0
    DEFAULT_MAX_COST_USD = 0  # kept for API compat; cost-cap removed
    NO_PROGRESS_TURN_LIMIT = 3

    def __init__(
        self,
        client: Any,
        tools: list[Any],
        ctx: ToolContext,
        *,
        system_prompt: str | None = None,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,  # ignored (compat)
        no_progress_turn_limit: int = NO_PROGRESS_TURN_LIMIT,
        on_step: Callable[[ChatResponse, list[dict[str, Any]]], None] | None = None,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        on_tool_result: Callable[[str, str, bool, str], None] | None = None,
        parent_interrupt_signal: Callable[[], bool] | None = None,
    ) -> None:
        self._client = client
        self._tools = list(tools)
        self._tools_by_name = {
            getattr(t, "name", ""): t for t in self._tools if getattr(t, "name", "")
        }
        self._ctx = ctx
        self._max_steps = max_steps
        self._max_cost_usd = 0  # cost-cap protection deleted
        self._no_progress_turn_limit = no_progress_turn_limit
        self._on_step = on_step
        self._audit_sink = audit_sink
        self._on_tool_result = on_tool_result
        self._parent_interrupt_signal = parent_interrupt_signal
        self._interrupt_requested = False
        self._streaming_messages: list[dict[str, Any]] = []
        self._streaming_turns = 0
        self._streaming_max_steps_reached = False
        self._streaming_cost_cap_reached = False  # always False
        self._streaming_no_progress_reached = False
        self._streaming_tool_ids: set[str] = set()
        self._run_cost_usd = 0.0  # optional audit accumulator only
        self._called_signatures: OrderedDict[Any, None] = OrderedDict()
        self._tool_call_counts: dict[str, int] = {}
        self._bash_call_count = 0
        self._tool_gate = ToolCallGate.from_settings()
        self._progress = ProgressTracker(limit=no_progress_turn_limit)
        _ = max_cost_usd  # deliberately ignored

        from .system_prompt import build_system_prompt

        self._system_prompt = build_system_prompt(
            tools,
            ctx=ctx,
            system_prompt=system_prompt,
        )
        # Still build pydantic tools for any future adapter; schemas
        # for the LLM come from tools_to_openai_schemas.
        try:
            self._pyd_tools = build_pydantic_tools(self._tools)
        except Exception:  # noqa: BLE001
            self._pyd_tools = []
        self._tool_schemas = tools_to_openai_schemas(self._tools)

    def interrupt(self) -> None:
        """Request cooperative cancel (checked between model turns)."""
        self._interrupt_requested = True

    def run(
        self,
        user_message: str,
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> AgentLoopResult:
        last_response: ChatResponse | None = None
        for resp in self.run_stream(
            user_message, prior_messages=prior_messages
        ):
            last_response = resp
        assert last_response is not None
        stopped = last_response.stop_reason or "end_turn"
        if self._streaming_max_steps_reached:
            stopped = "max_steps"
        elif self._streaming_no_progress_reached:
            stopped = "no_progress"
        elif self._interrupt_requested:
            stopped = "cancelled"
        return AgentLoopResult(
            final_response=last_response,
            messages=list(self._streaming_messages),
            turns=self._streaming_turns,
            stopped_reason=stopped,
        )

    def run_stream(
        self,
        user_message: str,
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> Iterator[ChatResponse]:
        """Manual ReAct loop; yields live ChatResponse snapshots."""
        self._interrupt_requested = False
        self._streaming_max_steps_reached = False
        self._streaming_cost_cap_reached = False
        self._streaming_no_progress_reached = False
        self._streaming_tool_ids = set()
        self._called_signatures = OrderedDict()
        self._tool_call_counts = {}
        self._bash_call_count = 0
        self._run_cost_usd = 0.0
        self._streaming_turns = 0
        self._tool_gate = ToolCallGate.from_settings()
        self._progress = ProgressTracker(limit=self._no_progress_turn_limit)
        force_final = False
        force_final_done = False
        # cost-cap removed — loop runs until tools done / max_steps / cancel

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        for pm in prior_messages or []:
            messages.append(dict(pm))
        messages.append({"role": "user", "content": user_message})
        self._streaming_messages = messages

        # Path pre-canned tool calls.
        try:
            from ..path_hooks import build_pre_canned_tool_calls

            pre = build_pre_canned_tool_calls(user_message) or []
        except Exception:  # noqa: BLE001
            pre = []
        if pre:
            # Execute path hooks, but do NOT inject synthetic assistant
            # tool_use into the LLM history. DeepSeek thinking mode
            # rejects tool_use turns that omit thinking/signature blocks
            # (400: thinking must be passed back). Surface results as
            # plain user notes instead.
            notes: list[str] = []
            for call in pre:
                name = call.get("name", "")
                args = call.get("input") or call.get("arguments") or {}
                tool_id = call.get("id") or f"pre_{name}"
                chat = ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": name,
                            "input": args,
                        }
                    ],
                    stop_reason="tool_use",
                )
                self._streaming_turns += 1
                yield chat
                result_text = self._execute_local_tool(name, args, tool_id)
                # Yield a synthetic tool-result-looking turn for the TUI.
                yield ChatResponse(
                    content_blocks=[
                        {
                            "type": "text",
                            "text": f"[pre:{name}] ok",
                        }
                    ],
                    stop_reason="end_turn",
                )
                notes.append(
                    f"- {name}({json.dumps(args, ensure_ascii=False)[:200]}) "
                    f"→ {result_text[:800]}"
                )
            if notes:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[system] Deterministic pre-tools already ran "
                            "(do not re-ingest the same path unless needed):\n"
                            + "\n".join(notes)
                        ),
                    }
                )

        max_turns = self._max_steps if self._max_steps and self._max_steps > 0 else 50
        last: ChatResponse | None = None

        for turn in range(1, max_turns + 1):
            if self._interrupt_requested:
                break
            if self._parent_interrupt_signal is not None:
                try:
                    if self._parent_interrupt_signal():
                        self._interrupt_requested = True
                        break
                except Exception:  # noqa: BLE001
                    pass
            self._streaming_turns = turn
            self._tool_gate.new_turn()
            _sanitize_messages_for_api(messages)

            tools_arg = None if force_final_done else self._tool_schemas
            if force_final and not force_final_done:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "No new tool progress for several turns. "
                            "Write a concise final summary now. Do NOT call tools."
                        ),
                    }
                )
                force_final_done = True
                tools_arg = None

            # Live mid-turn chunks are collected then re-yielded so the
            # outer generator stays single-threaded (no nested yield).
            live_chunks: list[ChatResponse] = []

            def _on_chunk(partial: ChatResponse) -> None:
                nonlocal last
                last = partial
                live_chunks.append(partial)

            resp = self._call_client(
                messages, tools_arg, on_chunk=_on_chunk
            )
            for partial in live_chunks:
                ordered_partial = ChatResponse(
                    content_blocks=normalize_assistant_content_blocks(
                        list(partial.content_blocks)
                        if partial.content_blocks
                        else []
                    ),
                    stop_reason=partial.stop_reason,
                    usage=dict(partial.usage or {}),
                    model=partial.model,
                )
                yield ordered_partial
            try:
                from ..cost import record_call

                record_call(resp)
            except Exception:  # noqa: BLE001
                pass

            progress_hit = self._progress.update(resp)
            if progress_hit == "no_progress":
                if force_final or force_final_done:
                    self._streaming_no_progress_reached = True
                else:
                    force_final = True
                    self._progress.reset_streak()

            if self._on_step is not None:
                try:
                    self._on_step(resp, messages)
                except Exception:  # noqa: BLE001
                    pass
            if self._audit_sink is not None:
                try:
                    self._audit_sink(
                        {
                            "turn": turn,
                            "stop_reason": resp.stop_reason,
                            "tool_calls": [
                                b.get("name")
                                for b in resp.content_blocks
                                if b.get("type") == "tool_use"
                            ],
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass

            # Normalize order before yield/history so stream folds cannot
            # leave tool_use before thinking (DeepSeek 400).
            ordered_blocks = normalize_assistant_content_blocks(
                list(resp.content_blocks) if resp.content_blocks else []
            )
            if not ordered_blocks and (resp.text or ""):
                ordered_blocks = [{"type": "text", "text": resp.text or ""}]
            resp = ChatResponse(
                content_blocks=ordered_blocks,
                stop_reason=resp.stop_reason,
                usage=dict(resp.usage or {}),
                model=resp.model,
            )
            last = resp
            yield resp

            # Persist assistant with FULL blocks (thinking + tool_use).
            messages.append(
                {
                    "role": "assistant",
                    "content": list(ordered_blocks)
                    if ordered_blocks
                    else [{"type": "text", "text": resp.text or ""}],
                }
            )

            tool_calls = [
                b
                for b in ordered_blocks
                if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            if not tool_calls or force_final_done:
                if not tool_calls:
                    break
                break

            # Execute every tool_use; one user message with all tool_results.
            result_blocks: list[dict[str, Any]] = []
            for tc in tool_calls:
                tid = str(tc.get("id") or "")
                name = str(tc.get("name") or "")
                args = tc.get("input") if isinstance(tc.get("input"), dict) else {}
                out = self._execute_local_tool(name, args or {}, tid)
                result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": out,
                    }
                )
            messages.append({"role": "user", "content": result_blocks})
            self._streaming_messages = messages
        else:
            self._streaming_max_steps_reached = True

        self._streaming_messages = messages
        if self._interrupt_requested and last is not None:
            yield ChatResponse(
                content_blocks=list(last.content_blocks),
                stop_reason="cancelled",
                usage=dict(last.usage),
                model=last.model,
            )
        elif last is None:
            yield ChatResponse(
                content_blocks=[{"type": "text", "text": "(no response)"}],
                stop_reason="end_turn",
            )

    def _call_client(
        self,
        messages: list[dict[str, Any]],
        tools_schema: list[dict[str, Any]] | None,
        on_chunk: Callable[[ChatResponse], None] | None = None,
    ) -> ChatResponse:
        """Call the ManuSift LLM client.

        Prefer non-stream ``chat()`` when tools are present: DeepSeek
        thinking-mode streams need careful thinking/signature assembly,
        and a failed stream previously returned an error bubble instead
        of a valid multi-turn history. Streaming is still used for
        text-only turns (live typing).
        """
        import os

        tools_arg = tools_schema or None
        # Prefer stream (TUI typing + test mocks). AnthropicLLM.chat_stream
        # now preserves thinking/signature and falls back to chat() on error.
        # MANUSIFT_LLM_FORCE_CHAT=1 forces non-stream chat only.
        force_chat = os.environ.get("MANUSIFT_LLM_FORCE_CHAT", "0") == "1"
        use_stream = (
            not force_chat
            and callable(getattr(self._client, "chat_stream", None))
        )
        if use_stream:
            accumulated: ChatResponse | None = None
            longest = ""
            chat_stream = self._client.chat_stream
            for chunk in chat_stream(messages, tools=tools_arg):
                try:
                    accumulated, longest = fold_stream_chunk(
                        accumulated, chunk, longest_text=longest
                    )
                except Exception:  # noqa: BLE001
                    accumulated = chunk
                    longest = chunk.text or longest
                if on_chunk is not None and accumulated is not None:
                    try:
                        on_chunk(accumulated)
                    except Exception:  # noqa: BLE001
                        pass
            if accumulated is not None:
                return accumulated
        resp = self._client.chat(messages, tools=tools_arg)
        if on_chunk is not None:
            try:
                on_chunk(resp)
            except Exception:  # noqa: BLE001
                pass
        return resp

    def _execute_local_tool(
        self,
        name: str,
        args: dict[str, Any],
        tool_id: str,
    ) -> str:
        gate = self._tool_gate
        denied = gate.check(name, args or {})
        if denied:
            result = denied
            is_error = True
            if self._on_tool_result is not None:
                try:
                    self._on_tool_result(name, result, is_error, tool_id)
                except Exception:  # noqa: BLE001
                    pass
            return result
        tool = self._tools_by_name.get(name)
        if tool is None:
            result = json.dumps(
                {"error": "unknown tool", "name": name}, ensure_ascii=False
            )
            is_error = True
        else:
            try:
                result = tool.execute(args or {}, self._ctx)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False, default=str)
                is_error = False
                gate.record(name, args or {})
                # Propagate data_sources from ingest / list_data_sources
                # into ctx so source_data_audit & friends see them
                # (mirrors legacy_loop behaviour).
                self._maybe_propagate_data_sources(name, result)
            except Exception as exc:  # noqa: BLE001
                result = json.dumps(
                    {"error": f"{type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                )
                is_error = True
        if self._on_tool_result is not None:
            try:
                self._on_tool_result(name, result, is_error, tool_id)
            except Exception:  # noqa: BLE001
                pass
        return result

    def _maybe_propagate_data_sources(
        self, tool_name: str, result_json: str
    ) -> None:
        """Write tool-result data_sources into ToolContext.metadata."""
        if tool_name not in ("ingest_from_path", "list_data_sources"):
            return
        try:
            parsed = json.loads(result_json)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(parsed, dict):
            return
        ds = parsed.get("data_sources")
        if not isinstance(ds, list) or not ds:
            # list_data_sources historically only returned ``tables``.
            tables = parsed.get("tables")
            if isinstance(tables, list) and tables:
                ds = tables
        if not isinstance(ds, list) or not ds:
            return
        try:
            self._ctx = self._ctx.with_metadata(data_sources=ds)
        except Exception:  # noqa: BLE001
            # Some ToolContext variants may not support with_metadata.
            try:
                meta = dict(self._ctx.metadata or {})
                meta["data_sources"] = ds
                object.__setattr__(self._ctx, "metadata", meta)
            except Exception:  # noqa: BLE001
                pass
