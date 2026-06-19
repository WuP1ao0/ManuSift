"""Chat response type (Step J2).

Borrowed design from the leaked Claude Code v2.1.88 source
(``response.content`` is a list of typed blocks, not a
string). Both OpenAI and Anthropic return slightly different
shapes, so we normalize here. The AgentLoop (Step J3) only
ever sees ChatResponse and never the raw provider dicts.

The shape:
  * ``content_blocks`` — a list of typed dicts. Each block
    has at least a ``type`` field. Recognized types:
    - ``"text"``: plain text. Has ``text`` (str).
    - ``"tool_use"``: a request to call a tool. Has
      ``id`` (str), ``name`` (str), ``input`` (dict).
  * ``stop_reason`` — provider-specific string. The
    AgentLoop only acts on these values:
    - ``"end_turn"`` (Anthropic) / ``"stop"`` (OpenAI):
      the LLM is done, return the response.
    - ``"tool_use"`` (Anthropic) / ``"tool_calls"``
      (OpenAI): the LLM wants to call tools.
  * ``usage`` — token counts. We keep the provider's
    structure verbatim; callers that care can introspect.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatResponse:
    """Normalized chat response. See module docstring."""

    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    # P1-E — model name that produced this
    # response. Empty string for callers that
    # build ChatResponse by hand (the
    # test-suite does this). The P1-E cost
    # aggregator uses this to bill per-model
    # with the right price list. We keep it on
    # the response (rather than on the client)
    # because the agent loop does not always
    # know which client made a given call when
    # it composes multi-model pipelines.
    model: str = ""

    def merged(self, other: "ChatResponse") -> "ChatResponse":
        """P2.5 — merge another ChatResponse into
        this one as if the model had produced
        both as a single response. Used by the
        streaming clients to fold per-chunk
        deltas into an accumulated final
        response.

        Merge rules:
          * ``content_blocks`` is concatenated
            (text blocks are merged by string
            concatenation when the previous
            block was also a text block;
            tool_use blocks with the same id
            are merged in place — the last
            chunk wins).
          * ``stop_reason`` keeps the
            non-empty value (other wins on
            tie, which is the typical case
            because the API sends the stop
            reason on the last chunk).
          * ``usage`` keeps the non-empty
            value (the API only returns it
            on the last chunk; we keep self
            if other is empty so a streaming
            response without a usage record
            still has the partial).
          * ``model`` keeps the non-empty
            value (same rationale as usage).
        """
        merged_blocks = list(self.content_blocks)
        for block in other.content_blocks:
            if block.get("type") == "text":
                if (
                    merged_blocks
                    and merged_blocks[-1].get("type") == "text"
                ):
                    last = merged_blocks[-1]
                    merged_blocks[-1] = {
                        **last,
                        "text": last.get("text", "") + block.get("text", ""),
                    }
                else:
                    merged_blocks.append(dict(block))
            elif block.get("type") == "tool_use":
                bid = block.get("id")
                if bid is not None:
                    replaced = False
                    for i, existing in enumerate(merged_blocks):
                        if (
                            existing.get("type") == "tool_use"
                            and existing.get("id") == bid
                        ):
                            merged_blocks[i] = dict(block)
                            replaced = True
                            break
                    if not replaced:
                        merged_blocks.append(dict(block))
                else:
                    merged_blocks.append(dict(block))
            else:
                merged_blocks.append(dict(block))
        return ChatResponse(
            content_blocks=merged_blocks,
            stop_reason=other.stop_reason or self.stop_reason,
            usage=other.usage or self.usage,
            model=other.model or self.model,
        )


    @property
    def text(self) -> str:
        """Concatenate all ``text`` blocks into a single
        string. Convenience for callers that only care about
        the final text (no tool calls)."""
        return "".join(
            block.get("text", "")
            for block in self.content_blocks
            if block.get("type") == "text"
        )

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        """Return all ``tool_use`` blocks as a flat list.
        The AgentLoop iterates these and dispatches each to
        a Tool.execute() call."""
        return [
            block
            for block in self.content_blocks
            if block.get("type") == "tool_use"
        ]
