"""Filter the chat-tui's in-memory ``ChatMessage`` history
into a small, LLM-friendly ``prior_messages`` list
(R-audit 2026-06-14).

Why we need a filter
====================

The chat-tui keeps an in-memory transcript of every
turn, including rows the user never reads directly:
status messages, detector trace block dumps, slash-
command output, raw tool JSON, ``\u2192 result: ...``
fold-back rows. The TUI renders those in a side panel
(``ToolTraceBlock`` collapsed by default, ``DebugDrawer``
hidden by default), so the user has the data without
it being on the chat log proper.

If we naively replayed that full transcript into the
agent loop's message list, the LLM would see its own
detector raw output and start to re-narrate it. Even
worse, the *user's* short follow-ups (\"\u4e0b\u4e00\u6b65\",
\"render the report\", \"\u7ee7\u7eed\") get lost behind a
hundred lines of tool JSON. The 5-section output
structure from the v2 system prompt relies on the LLM
actually remembering what it asked the user last turn
\u2014 without history, the LLM behaves like it is a
brand-new conversation every time.

The fix
=======

This module is the single source of truth for which
``ChatMessage``s are worth shipping to the LLM. Rules:

  1. Keep ``role == "user"`` rows whose ``content`` is
     a non-empty string the user typed.
  2. Keep ``role == "assistant"`` rows whose ``content``
     is a non-empty string (the final text, not the
     accumulated streaming chunks; ``_append_message``
     in the TUI already collapses those).
  3. Drop everything else: ``"system"`` rows, ``"tool"``
     rows, rows that look like JSON tool payloads, and
     rows whose content starts with the
     ``ToolTraceBlock`` glyphs (``\u25cf`` / ``\u25cb`` /
     ``\u2192``).
  4. Drop the most recent user message \u2014 the caller
     passes the current ``user_text`` separately, and we
     never want the LLM to see the same message twice
     in a row.
  5. Cap at ``max_turns`` user/assistant pairs to keep
     the message list under ~2k tokens even for long
     sessions. ``0`` (or ``None``) means "no cap" --
     ship the entire filtered transcript. The
     default is 0 (unlimited) so the LLM gets the
     full multi-turn context by default; callers
     that want a tight budget can pass an explicit
     positive integer.

Output format
=============

A list of ``{"role": str, "content": str}`` dicts in
the order they appeared in the transcript, suitable
for concatenation with the agent loop's
``[system, *prior_messages, user_message]`` template.

We deliberately use the same shape the LLM SDKs expect
(``role`` + ``content``) rather than the richer
``ChatMessage`` dataclass \u2014 the agent loop should
not have to know about TUI internals.
"""

from __future__ import annotations

from typing import Any

# R-2026-06-14: the user asked to remove the
# implicit 10-pair cap. The default is now 0
# (no cap) so a long session with 20+ turns of
# "now what?" follow-ups does not lose the
# round-1 PDF path to the cap. Callers that
# want a tight budget for cost / latency
# reasons can still pass an explicit positive
# ``max_turns``.
DEFAULT_MAX_TURNS = 0

# Role names that survive the filter.
_USER_ROLES = frozenset({"user"})
_ASSISTANT_ROLES = frozenset({"assistant"})

# Prefixes that mark a message as TUI chrome rather
# than LLM-meaningful content. The TUI emits a few
# status lines with these glyphs; we drop them so the
# LLM does not re-narrate them.
_CHROME_PREFIXES: tuple[str, ...] = (
    "\u2192 ",  # "-> result: ..."
    "[\u25cb ",  # "[o status ...]"
    "[\u25cf ",  # "[* ...]"
    "[\u26a0 ",  # "[! ...]"
    "agent: ",  # status bar echo
    "agent finished ",
    "agent hit ",
    "agent crashed",
    "queued (",
)


def _is_chrome(text: str) -> bool:
    """Return True if ``text`` looks like TUI chrome
    rather than user / assistant content. We are
    deliberately strict: if in doubt, keep the message
    so the LLM at least sees it \u2014 dropping
    legitimate context is worse than dropping a few
    decoration lines.
    """
    s = text.lstrip()
    return s.startswith(_CHROME_PREFIXES)


def _looks_like_tool_payload(text: str) -> bool:
    """Return True if ``text`` is an obvious tool
    return payload. The detector tools serialise their
    findings as ``{"findings": [...]}`` or
    ``{"trace_id": ...}`` JSON, and the LLM does not
    benefit from seeing those dicts in the history
    (the tool trace block already shows them
    collapsed).
    """
    s = text.lstrip()
    if not s.startswith("{"):
        return False
    # A second-line opening brace is a strong signal
    # that this is a JSON tool payload, not a user
    # typed an opening brace by accident.
    return "\n{" in s or s.startswith("{\n")


def _is_meaningful_user(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _is_chrome(text):
        return False
    if _looks_like_tool_payload(text):
        return False
    return True


def _is_meaningful_assistant(text: str) -> bool:
    if not text or not text.strip():
        return False
    if _is_chrome(text):
        return False
    if _looks_like_tool_payload(text):
        return False
    return True


def filter_history_for_llm(
    history: list[Any],
    current_user_text: str,
    *,
    max_turns: int | None = DEFAULT_MAX_TURNS,
) -> list[dict[str, str]]:
    """Reduce the TUI's full chat history to a small
    list of ``{"role": ..., "content": ...}`` dicts
    the LLM can use to remember the conversation.

    Parameters
    ----------
    history
        The TUI's ``self._history`` list. Each element
        must expose ``.role`` and ``.content`` (the
        ``ChatMessage`` dataclass satisfies this).
    current_user_text
        The message the user just submitted. The
        filter EXCLUDES any prior message with
        identical content (de-dup) so the LLM does
        not see ``"\u4e0b\u4e0b\u4e00\u6b65"`` twice \u2014 the
        AgentLoop appends the current user text on
        its own.
    max_turns
        Maximum number of user/assistant PAIRS to
        keep. We always keep at most
        ``2 * max_turns + 1`` messages. Default 10
        pairs (= 20 messages) keeps the prefix under
        ~2k tokens for typical Chinese / English
        assistant replies.

    Returns
    -------
    A list of ``{"role": str, "content": str}``
    dicts, in the order they were spoken, ready to
    splice between the system prompt and the current
    user message in the agent loop's message list.
    """
    # R-2026-06-14: 0 and None both mean "no cap" --
    # ship the entire filtered transcript. A
    # negative value is a programming error and
    # is treated as "return empty" so a bug does
    # not silently truncate history.
    if max_turns is not None and max_turns < 0:
        return []
    out: list[dict[str, str]] = []
    for msg in history:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", "") or ""
        if role in _USER_ROLES:
            if not _is_meaningful_user(content):
                continue
        elif role in _ASSISTANT_ROLES:
            if not _is_meaningful_assistant(content):
                continue
        else:
            # "system", "tool", or anything unknown
            # \u2014 drop. The LLM does not need to see
            # TUI status rows, raw tool JSON, or
            # slash-command output.
            continue
        out.append(
            {"role": role, "content": content}
        )
    # De-dupe the just-typed user text. If the last
    # entry in the history is a user row with the
    # same text as ``current_user_text``, drop it
    # because the AgentLoop will append the current
    # user message on its own.
    if out and out[-1]["role"] == "user":
        if out[-1]["content"].strip() == current_user_text.strip():
            out.pop()
    # Cap at max_turns pairs, but keep the *latest*
    # turns (most recent context is the most useful
    # for the LLM). Walk backward from the end,
    # counting user messages, and stop once we have
    # exactly ``max_turns`` of them -- the slice
    # begins at the (max_turns - 1)-th user message
    # from the end.
    #
    # ``max_turns`` of 0 or None (the new default,
    # R-2026-06-14) means "no cap" -- return the
    # entire filtered transcript. The compact
    # state reminder on the system prompt
    # additionally guards against the case where
    # the LLM's context window truncates older
    # turns; the active trace_id, current_pdf,
    # data_sources, and last open offer are
    # always present in the system prompt
    # regardless of the prior_messages length.
    if not max_turns:
        return out
    user_count = 0
    cutoff = -1
    for i in range(len(out) - 1, -1, -1):
        if out[i]["role"] == "user":
            if user_count == max_turns - 1:
                # Everything from this index onwards
                # is the most recent ``max_turns``
                # user turns (and the assistant
                # turns interleaved with them).
                cutoff = i
                break
            user_count += 1
    if cutoff >= 0:
        out = out[cutoff:]
    return out
