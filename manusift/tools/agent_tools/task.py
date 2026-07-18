"""Task tool (R-audit 2026-06-10).

Extracted from ``manusift.tools.agent_tools`` in
R-2026-06-15 (Phase 4 + P4-1)
god-file extraction.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..tool import Tool, ToolContext


class TaskTool:
    """Spawn a sub-agent with
    its own LLM context.

    R-2026-06-10: the LLM
    needs to delegate
    long-running sub-tasks
    (e.g. "scan all 76
    images in this paper
    for duplicates") to a
    sub-agent that runs in
    isolation.

    R-2026-06-14: the
    sub-agent now runs in
    a worker thread with a
    hard timeout and emits
    a ``subagent.started``
    / ``subagent.finished``
    event pair on the
    parent EventBus. Every
    tool/detector event the
    sub-agent fires is
    forwarded to the parent
    bus with a
    ``subagent_id`` payload
    field, so the parent
    TUI timeline can render
    the sub-agent's
    progress as
    ``[sub:abc1] tool=image_dup 1.2s ok``
    entries. A sub-agent
    that hangs no longer
    freezes the parent.
    """

    name = "task"

    def description(self) -> str:
        return (
            "Spawn a sub-agent with its own LLM context to "
            "handle a focused sub-task. The sub-agent has "
            "access to the same tools the parent has "
            "(including web_search, bash, file tools, "
            "detectors). Only the sub-agent's final "
            "assistant message is returned to the parent "
            "to keep the parent's context small. The "
            "sub-agent's tool calls and intermediate "
            "reasoning DO appear in the parent's TUI "
            "timeline as ``[sub:abc1] tool=...`` rows so "
            "you can audit what the sub-agent actually "
            "did. The sub-agent has a hard timeout "
            "(default 120s, env ``MANUSIFT_SUBAGENT_TIMEOUT_SECONDS``); "
            "if it does not return in time the parent "
            "gets a typed timeout error and continues. "
            "Use this for long, focused sub-tasks "
            "(e.g. 'scan all 76 images for duplicates', "
            "'research X on the web', 'compile a list of "
            "Y') rather than burning the parent's context."
            " R-2026-06-15 (Phase 0.8): a ``role`` of "
            "``\"leaf\"`` strips ``TaskTool`` (and "
            "anything else you opt out of in the future) "
            "from the sub-agent's tool list so it "
            "cannot recursively spawn sub-sub-agents. "
            "Default is ``\"leaf\"`` (the safe default). "
            "Set to ``\"orchestrator\"`` only when you "
            "intentionally want a sub-agent that can "
            "further delegate."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subagent_prompt": {
                    "type": "string",
                    "description": (
                        "The task description for the "
                        "sub-agent. Be specific about what "
                        "the sub-agent should produce and "
                        "what format the final answer should "
                        "be in."
                    ),
                },
                "isolated_context": {
                    "type": "boolean",
                    "description": (
                        "If true, the sub-agent starts with "
                        "a fresh conversation (no parent "
                        "history). Default True."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": (
                        "Hard timeout for the sub-agent in "
                        "seconds. Default 120s. Configurable "
                        "via MANUSIFT_SUBAGENT_TIMEOUT_SECONDS."
                    ),
                },
                # R-2026-06-15 (Phase 0.8):
                # ``role`` controls
                # whether the
                # sub-agent can
                # recursively spawn
                # sub-sub-agents.
                # ``\"leaf\"`` is
                # the safe default:
                # the sub-agent's
                # tool list is
                # filtered to
                # exclude ``TaskTool``
                # so a runaway
                # sub-agent cannot
                # spiral. Set to
                # ``\"orchestrator\"``
                # only when you
                # intentionally want
                # a sub-agent that
                # can delegate.
                "role": {
                    "type": "string",
                    "enum": ["leaf", "orchestrator"],
                    "description": (
                        "The sub-agent's role. "
                        "``\"leaf\"`` (default) "
                        "strips ``TaskTool`` "
                        "from the sub-agent's "
                        "tool list so it "
                        "cannot recursively "
                        "spawn sub-sub-agents. "
                        "``\"orchestrator\"`` "
                        "preserves the full "
                        "tool list. The "
                        "default is the safe "
                        "one; the LLM must "
                        "explicitly opt in to "
                        "orchestrator mode."
                    ),
                },
            },
            "required": ["subagent_prompt"],
        }

    def execute(
        self,
        input: dict[str, Any],
        ctx: ToolContext,
    ) -> str:
        from ...agent.factory import create_agent_loop
        from ...llm import get_llm_client
        from ...tools import iter_registered_tools
        from ...tools.tool import ToolContext as TC
        from ..subagent_forwarder import (
            _SubagentEventForwarder,
            new_subagent_id,
            run_subagent_with_timeout,
            _prompt_summary,
        )

        subagent_prompt = (
            input.get("subagent_prompt") or ""
        ).strip()
        if not subagent_prompt:
            return json.dumps(
                {
                    "ok": False,
                    "error_kind": "permission_denied",
                    "error": "subagent_prompt is required",
                }
            )
        # R-2026-06-15 (Phase 4 + P4-1):
        # the max-nesting
        # check was
        # previously AFTER
        # the LLM client
        # check, so a
        # depth-violating
        # call would
        # return
        # ``"dependency_missing"``
        # instead of
        # ``"max_nesting_exceeded"``
        # (because the test
        # env has no API
        # key).  Moved the
        # check here
        # so the depth
        # enforcement is
        # the FIRST thing
        # the tool
        # considers after
        # argument
        # validation.
        try:
            from ...config import get_settings
            settings = get_settings()
            max_nesting = int(
                getattr(
                    settings,
                    "subagent_max_nesting",
                    3,
                )
            )
        except Exception:  # noqa: BLE001
            max_nesting = 3
        current_depth = int(
            (ctx.metadata or {}).get(
                "_subagent_depth", 0
            )
        )
        if current_depth > max_nesting:
            return json.dumps(
                {
                    "ok": False,
                    "error_kind": (
                        "max_nesting_exceeded"
                    ),
                    "error": (
                        f"subagent nesting "
                        f"exceeds "
                        f"subagent_max_nesting="
                        f"{max_nesting} "
                        f"(current depth: "
                        f"{current_depth})"
                    ),
                    "current_depth": current_depth,
                    "max_nesting": max_nesting,
                }
            )
        try:
            client = get_llm_client()
        except Exception as exc:  # noqa: BLE001
            return json.dumps(
                {
                    "ok": False,
                    "error_kind": "dependency_missing",
                    "error": (
                        f"could not get LLM client: {exc}"
                    ),
                }
            )
        # Per-call timeout, falling back to env override
        # and finally 120s. ``input.get("timeout_seconds")``
        # may be 0; we clamp at 1 to keep a positive
        # deadline.
        try:
            from ...config import get_settings
            settings = get_settings()
            default_to = float(
                getattr(
                    settings, "subagent_timeout_seconds", 120
                )
            )
        except Exception:  # noqa: BLE001
            default_to = 120.0
        raw_to = input.get("timeout_seconds")
        if raw_to is None:
            timeout_seconds = default_to
        else:
            try:
                # Clamp to >= 0.1s so a
                # typo'd 0.001s does
                # not insta-fail the
                # sub-agent. ``0`` is
                # NOT treated as
                # "unlimited" because
                # an unlimited sub-agent
                # is a TUI hang waiting
                # to happen; use
                # ``-1`` to request
                # unlimited, which we
                # map to ``default_to``
                # for safety.
                requested = float(raw_to)
                if requested < 0:
                    timeout_seconds = default_to
                else:
                    timeout_seconds = max(
                        0.1, requested
                    )
            except (TypeError, ValueError):
                timeout_seconds = default_to

        tools = list(iter_registered_tools())
        # R-2026-06-15 (Phase 0.8):
        # ``role`` controls
        # whether the sub-agent
        # can recursively spawn
        # sub-sub-agents. A
        # ``"leaf"`` role strips
        # ``TaskTool`` from the
        # sub-agent's tool list
        # so a runaway sub-agent
        # cannot spiral. A
        # ``"orchestrator"`` role
        # preserves the full
        # tool list. Default is
        # ``"leaf"`` (the safe
        # default). The actual
        # filter logic is in
        # ``_filter_tools_by_role``
        # so the tests can pin
        # it without spinning up
        # a sub-agent.
        role = input.get("role") or "leaf"
        if role not in ("leaf", "orchestrator"):
            return json.dumps({
                "ok": False,
                "error_kind": "not_applicable",
                "error": (
                    f"unknown role {role!r}; "
                    f"expected 'leaf' or 'orchestrator'"
                ),
            })
        tools = _filter_tools_by_role(tools, role)
        # The
        # sub-agent
        # gets
        # the
        # same
        # tool
        # set
        # as
        # the
        # parent.
        # We
        # use
        # the
        # same
        # trace_id
        # but
        # append
        # a
        # unique
        # subagent_id
        # to
        # the
        # metadata
        # so
        # the
        # TUI
        # can
        # route
        # events
        # back
        # to
        # this
        # sub-agent
        # even
        # when
        # multiple
        # are
        # running
        # in
        # parallel
        # later.
        # R-2026-06-15 (Phase 3 + P3-4):
        # enforce a max
        # nesting depth.
        # ``ctx.metadata["_subagent_depth"]``
        # is set by the
        # *parent* loop's
        # ``_pre_canned_path``
        # machinery (or by
        # the recursive
        # ``TaskTool``
        # itself).  A depth
        # of ``0`` is the
        # top-level agent;
        # ``1`` is a
        # direct child; the
        # audit's recommended
        # cap is
        # ``Settings.subagent_max_nesting``
        # (default ``3``,
        # i.e. top -> child
        # -> grandchild ->
        # great-grandchild).
        # Beyond that we
        # reject the
        # ``TaskTool`` call
        # with a typed
        # ``"max_nesting_exceeded"``
        # error so the
        # orchestrator does
        # not infinitely
        # recurse.
        # R-2026-06-15 (Phase 4 + P4-1):
        # the depth check
        # is now at the
        # TOP of
        # ``execute()``
        # (right after the
        # ``subagent_prompt``
        # argument
        # check), so this
        # second copy is
        # redundant and
        # removed.
        subagent_id = new_subagent_id()
        sub_meta = dict(ctx.metadata or {})
        sub_meta["subagent_id"] = subagent_id
        # R-2026-06-15 (Phase 3 + P3-4):
        # propagate the
        # depth to the
        # child so a
        # grandchild knows
        # it is at depth 2.
        sub_meta["_subagent_depth"] = (
            current_depth + 1
        )
        sub_ctx = TC(
            trace_id=ctx.trace_id,
            current_pdf=ctx.current_pdf,
            metadata=sub_meta,
        )
        # R-2026-06-15 (Phase 3 + P3-1):
        # propagate the
        # parent's
        # interrupt signal
        # to the child loop.
        # When the user
        # types ``/stop`` in
        # the parent, the
        # parent's
        # ``_interrupt_requested``
        # flips; the
        # child loop's
        # constructor reads
        # this callable at
        # the *top of every
        # turn* and exits
        # with
        # ``stop_reason='cancelled'``
        # (instead of
        # waiting the full
        # ``timeout_seconds``
        # to give up).
        parent_interrupt_signal = (
            (ctx.metadata or {}).get(
                "_parent_interrupt_check"
            )
            if ctx.metadata
            else None
        )
        # Same runtime as the parent TUI (PydanticAI by
        # default; MANUSIFT_AGENT_RUNTIME=legacy to force
        # the hand-rolled loop). Domain Kernel tools are
        # unchanged; only the ReAct driver is selected.
        loop = create_agent_loop(
            client=client,
            tools=tools,
            ctx=sub_ctx,
            parent_interrupt_signal=(
                parent_interrupt_signal
            ),
        )
        # Forward the sub-agent's events to the parent
        # bus, tagged with subagent_id, for the
        # duration of the call. ``__exit__`` emits the
        # final ``subagent.finished`` event.
        summary = _prompt_summary(subagent_prompt)
        with _SubagentEventForwarder(
            subagent_id, summary
        ) as fwd:
            # R-2026-06-15 (Phase 3 + P3-2):
            # the runner now
            # returns a typed
            # ``SubagentResult``
            # (not a 3-tuple).
            sub_result = run_subagent_with_timeout(
                loop,
                subagent_prompt,
                timeout_seconds,
                fwd,
                trace_id=ctx.trace_id,
            )
        if not sub_result.ok:
            return json.dumps(
                {
                    "ok": False,
                    # R-2026-06-15
                    # (Phase 3 + P3-2):
                    # use the
                    # typed
                    # ``error_kind``
                    # from the
                    # ``SubagentResult``.
                    # ``"timeout"``
                    # maps to the
                    # existing
                    # ``"budget_exhausted"``
                    # so older
                    # consumers (e.g.
                    # the audit log
                    # parser) still
                    # see the same
                    # string.
                    "error_kind": (
                        "budget_exhausted"
                        if sub_result.error_kind
                        == "timeout"
                        else (
                            sub_result.error_kind
                            or "internal"
                        )
                    ),
                    "error": (
                        f"sub-agent failed "
                        f"(kind={sub_result.error_kind!r}) "
                        f"after {sub_result.elapsed_ms}ms"
                    ),
                    "subagent_id": sub_result.subagent_id,
                    "partial_text": sub_result.output,
                    "timeout_seconds": timeout_seconds,
                    "elapsed_ms": sub_result.elapsed_ms,
                }
            )
        return json.dumps(
            {
                "ok": True,
                "result": sub_result.output,
                "subagent_id": sub_result.subagent_id,
                "timeout_seconds": timeout_seconds,
                "elapsed_ms": sub_result.elapsed_ms,
            },
            ensure_ascii=False,
        )


# ============================================================
# 7. todo_write
# ============================================================




def _filter_tools_by_role(
    tools: list[Any],
    role: str | None,
) -> list[Any]:
    """R-2026-06-15 (Phase 0.8):
    Apply a per-role tool
    filter.

    The contract:

      * ``role="leaf"`` --
        default; strips
        ``TaskTool`` from
        the sub-agent's
        tool list so the
        sub-agent cannot
        recursively spawn
        sub-sub-agents.
      * ``role="orchestrator"`` --
        the sub-agent
        keeps the full
        tool list (it
        can delegate
        further).
      * ``role=None`` or
        missing -- the
        safe default
        (``"leaf"``).
      * Unknown role --
        returns an empty
        list (the caller is
        responsible for
        emitting the
        typed
        ``not_applicable``
        error).
    """
    if role is None or role == "":
        role = "leaf"
    if role == "orchestrator":
        return list(tools)
    if role == "leaf":
        return [
            t
            for t in tools
            if getattr(t, "name", "") != "task"
        ]
    # Unknown role:
    # return an empty list.
    return []


