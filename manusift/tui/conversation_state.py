"""Compact conversation state on the ``ToolContext``
(R-audit 2026-06-14).

The chat-tui runs many turns against a single
``trace_id``. The user's short follow-ups (\"\u4e0b\u4e00\u6b65\",
\"\u7ee7\u7eed\", \"render the report\") depend on the LLM
knowing which ``trace_id`` and ``current_pdf`` the
previous turn was about.

The agent loop's ``messages`` list *does* carry the
prior conversation as ``prior_messages`` (see
``manusift.tui.history_filter``), but the LLM's
attention is finite and the conversation history
gets truncated to ~10 turns. If the user pauses for
20 turns and then says \"\u4e0b\u4e00\u6b65\", the prior
messages may already have aged out of the buffer.

This module fixes that by injecting a small
**conversation state** dict into the agent loop's
``ctx.metadata``. The metadata is passed to every
tool call (via the ``ToolContext``) and the system
prompt builder reads it to inject a one-line
"state reminder" at the top of the system prompt.

What we track
=============

  * ``active_trace_id`` \u2014 the most recent trace id,
    set when a tool returns a ``trace_id`` field.
  * ``current_pdf`` \u2014 the absolute path of the PDF
    currently being reviewed.
  * ``data_sources`` \u2014 a short summary of the
    companion data tables attached to the PDF.
  * ``last_assistant_offer`` \u2014 the last question
    the assistant put to the user (e.g. \"\u662f\u5426\u751f\u6210
    HTML \u62a5\u544a\uff1f\"). This is the key bit: a
    follow-up \"\u4e0b\u4e00\u6b65\" maps cleanly to
    \"yes, generate the report\".
  * ``last_assistant_offer_at`` \u2014 a monotonic
    counter (or timestamp) we can use to detect
    stale offers.
  * ``turn_index`` \u2014 the number of the current turn
    (for the LLM to keep its place in long sessions).

Why a new ToolContext and not mutate the existing one
=====================================================

``ToolContext`` is ``frozen=True`` (see
``manusift.tools.tool``). The state helpers therefore
return a *new* ToolContext with the merged metadata
dict. The Runner passes that into the agent loop, the
agent loop passes it to every tool, and tools that
care about conversation state can read
``ctx.metadata[\"conversation_state\"]``.
"""

from __future__ import annotations

from typing import Any

from ..tools.tool import ToolContext


_CONVERSATION_STATE_KEY = "conversation_state"


def empty_state() -> dict[str, Any]:
    """Return a fresh, empty conversation state dict.

    The fields are all ``None`` / ``0`` so callers can
    always do ``state.get(\"active_trace_id\")`` without
    catching KeyError.
    """
    return {
        "active_trace_id": None,
        "current_pdf": None,
        "data_sources": [],
        "last_assistant_offer": None,
        "last_assistant_offer_at": 0,
        "turn_index": 0,
    }


def merge_state(
    base: dict[str, Any] | None,
    *,
    active_trace_id: str | None = None,
    current_pdf: str | None = None,
    data_sources: list[str] | None = None,
    last_assistant_offer: str | None = None,
    increment_turn: bool = True,
) -> dict[str, Any]:
    """Build a new state dict by overlaying non-None
    fields on top of ``base`` (or an empty state).
    Returns a fresh dict so the caller can store it
    back into ``ctx.metadata`` without aliasing.
    """
    state = empty_state()
    if base:
        state.update(base)
    if active_trace_id is not None:
        state["active_trace_id"] = active_trace_id
    if current_pdf is not None:
        state["current_pdf"] = current_pdf
    if data_sources is not None:
        state["data_sources"] = list(data_sources)
    if last_assistant_offer is not None:
        state["last_assistant_offer"] = last_assistant_offer
        state["last_assistant_offer_at"] = (
            state.get("turn_index", 0) + 1
        )
    if increment_turn:
        state["turn_index"] = state.get("turn_index", 0) + 1
    return state


def with_state(
    ctx: ToolContext,
    state: dict[str, Any],
) -> ToolContext:
    """Return a *new* ``ToolContext`` with the given
    state dict stored under
    ``ctx.metadata[CONVERSATION_STATE_KEY]``. The
    original ``ctx`` is not mutated (it is frozen).
    """
    new_meta = dict(ctx.metadata or {})
    new_meta[_CONVERSATION_STATE_KEY] = state
    return ToolContext(
        trace_id=ctx.trace_id,
        current_pdf=ctx.current_pdf,
        metadata=new_meta,
    )


def get_state(ctx: ToolContext) -> dict[str, Any]:
    """Read the conversation state out of a
    ``ToolContext``. Returns an empty state if none
    has been set.
    """
    md = ctx.metadata or {}
    raw = md.get(_CONVERSATION_STATE_KEY)
    if not isinstance(raw, dict):
        return empty_state()
    return raw


def state_to_state_reminder(state: dict[str, Any]) -> str:
    """Render the conversation state as a one-line
    system-prompt fragment. Empty / unset fields are
    omitted. The reminder is added to the system
    prompt right before the user's first turn so the
    LLM remembers the active ``trace_id`` even when
    the prior-message buffer is truncated.
    """
    parts: list[str] = []
    trace_id = state.get("active_trace_id")
    pdf = state.get("current_pdf")
    sources = state.get("data_sources") or []
    offer = state.get("last_assistant_offer")
    if trace_id:
        parts.append(f"active trace_id: {trace_id}")
    if pdf:
        parts.append(f"current PDF: {pdf}")
    if sources:
        # Cap at 3 to keep the reminder short; the
        # full list is available via
        # list_data_sources.
        shown = ", ".join(sources[:3])
        if len(sources) > 3:
            shown += f" (+{len(sources) - 3} more)"
        parts.append(f"data sources: {shown}")
    if offer:
        parts.append(f"last open offer: {offer}")
    if not parts:
        return ""
    # Use a single line \u2014 the system prompt already has
    # a 5-section structure; this reminder should
    # be a one-liner that the LLM can scan.
    return (
        "\n\n## Conversation State Reminder\n"
        "  " + "; ".join(parts) + "\n"
    )
