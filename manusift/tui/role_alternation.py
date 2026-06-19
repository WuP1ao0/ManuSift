"""Role-alternation validator
(R-2026-06-15, Phase 0.10).

Hermes rule (AGENTS.md,
``Conventions``): "The
conversation transcript
**MUST** alternate
``user`` and ``assistant``
roles. Two consecutive
``assistant`` messages
would mean the LLM is
'responding to itself';
two consecutive ``user``
messages would mean the
client is forwarding a
turn that the LLM never
saw. Both are bugs."

ManuSift's chat TUI builds
a ``prior_messages`` list
from ``self._history`` and
hands it to the agent. If
two consecutive messages
have the same role, the
LLM will either reject the
request (Anthropic) or
silently merge them
(OpenAI). Either way, the
agent will produce
gibberish or the user
will see "I already said
that" loops.

This module exposes a
pure ``assert_role_alternation(messages)``
function. It returns a
sanitized copy of the
list with the duplicates
dropped. Tests pin the
contract independently of
the chat TUI.
"""
from __future__ import annotations

from typing import Any, Iterable


def assert_role_alternation(
    messages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a sanitized copy
    of ``messages`` where
    consecutive same-role
    messages are deduped.

    The contract:

      * Two consecutive
        ``"user"`` messages
        are deduplicated to
        one (the later one
        wins). The user
        sent one message;
        the LLM saw it.
      * Two consecutive
        ``"assistant"``
        messages are
        deduplicated to one
        (the later one wins,
        since the LLM is
        the source of
        truth). A leading
        "I already said
        that" loop is
        prevented.
      * ``"system"``,
        ``"tool"``,
        ``"developer"``
        roles are passed
        through unchanged.
        They are part of
        the OpenAI-style
        message format
        and do not count
        toward the user
        / assistant
        alternation rule.
      * An empty input
        returns ``[]``.
      * The function does
        NOT mutate the
        caller.
    """
    out: list[dict[str, Any]] = []
    passthrough = {
        "system",
        "tool",
        "developer",
    }
    for m in messages:
        role = m.get("role")
        if role in passthrough:
            out.append(m)
            continue
        if role not in ("user", "assistant"):
            # Unknown role:
            # pass through
            # (defensive).
            out.append(m)
            continue
        # If the last
        # user/assistant
        # message has the
        # same role, drop
        # the previous one
        # and keep the
        # new one.
        if (
            out
            and out[-1].get("role") == role
        ):
            out[-1] = m
        else:
            out.append(m)
    return out
