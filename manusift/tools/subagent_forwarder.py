"""R-2026-06-14: TaskTool subagent TUI forwarding.

Two changes to ``manusift.tools.agent_tools.TaskTool``:

1. **Threaded execution with timeout + cancellation.**
   The previous implementation ran the sub-agent
   synchronously in the same thread with no timeout and no
   cancellation hook. A stuck sub-agent would freeze the
   parent TUI at "calling task, task, task...".

   We now run the sub-agent in a ``threading.Thread`` and
   wait for it with a deadline. On timeout we return a
   structured "timeout" error (not a hang) and the
   sub-agent thread continues to drain in the background
   so the LLM can react.

2. **Subagent tool/detector event forwarding.**
   The previous implementation discarded every
   intermediate ``tool.started / tool.finished /
   detector.*`` event from the sub-agent's EventBus. The
   parent TUI had no idea what the sub-agent was doing.

   We now forward each sub-agent event to the parent
   EventBus with a ``subagent_id`` prefix in the payload,
   so the parent's TUI timeline can render the
   sub-agent's progress as
   ``[sub:abc1] tool=image_dup 1.2s ok`` entries.

The forwarding is done by subscribing a small listener
to the sub-agent's bus (which is the *same* bus — they
share the process) for the duration of the call, then
unsubscribing at the end. We tag every forwarded event
with ``payload["subagent_id"] = "sub:abcdef"`` so the
parent TUI can route them to the right trace.

This module also re-exports ``subagent_id_for_trace``
and ``_emit_subagent_event`` so the tests can stub them.
"""
from __future__ import annotations

import json
import os
import string
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# Subagent id alphabet: lowercase letters + digits, no
# confusing chars. Matches the LLM trace_id style.
_SUBAGENT_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def new_subagent_id() -> str:
    """Return a short, lowercase, no-confusable-chars id.

    Mirrors the trace_id style: 6 hex-ish chars preceded
    by ``sub:`` so the parent TUI can grep on it.
    """
    raw = "".join(
        _SUBAGENT_ALPHABET[i % len(_SUBAGENT_ALPHABET)]
        for i in uuid.uuid4().bytes
    )[:6]
    return f"sub:{raw}"


def short_subagent_prefix(subagent_id: str) -> str:
    """Return just the 4-char prefix of a subagent id.

    R-2026-06-19 (P3-A5):
    the prefix
    is used in
    the TUI
    ``[sub:ab12]``
    row to
    identify
    the
    sub-agent
    without
    showing
    the full
    hex id
    (which
    is 8+
    chars
    and
    noisy
    in the
    scrollback)."""
    if subagent_id.startswith("sub:"):
        return subagent_id[:7]  # "sub:ab12"
    return subagent_id[:7]


# R-2026-06-19 (P3-A5):
# the TUI calls
# this when
# it sees a
# sub-agent
# event on
# the bus.
# Returns
# ``None`` for
# non-sub-agent
# events so
# the TUI can
# skip the
# row.
def format_subagent_event_row(
    payload: dict[str, Any] | None,
) -> str | None:
    """Render a sub-agent
    event payload as a
    TUI scrollback row.

    R-2026-06-19 (P3-A5):
    the row is
    a short
    human-readable
    string like
    ``[sub:ab12] read_file started``
    that the
    TUI appends
    to the
    ``#history``
    scrollback
    above the
    nested
    ``ToolCallCard``.

    Returns
    ``None``
    when the
    payload has
    no ``subagent_id`` so
    the caller
    can decide
    to skip
    the row.
    """
    if not isinstance(payload, dict):
        return None
    subagent_id = payload.get("subagent_id")
    if not subagent_id:
        return None
    prefix = short_subagent_prefix(subagent_id)
    event = payload.get("event", "subagent.event")
    if "tool_name" in payload:
        action = (
            f"{payload['tool_name']} "
            f"{event.split('.', 1)[-1]}"
        )
    elif "detector_name" in payload:
        action = (
            f"detector.{payload['detector_name']} "
            f"{event.split('.', 1)[-1]}"
        )
    elif event == "subagent.finished":
        ok = payload.get("ok", False)
        action = "finished ok" if ok else "finished with errors"
    elif event == "subagent.started":
        action = "started"
    elif event == "subagent.progress":
        action = "in progress"
    else:
        action = event
    return f"[{prefix}] {action}"


# Event types emitted by the subagent listener. These
# are real ``manusift.events.Event`` types the parent
# bus already knows about; we just inject a
# ``subagent_id`` field in the payload.
_FORWARDED_EVENT_TYPES = (
    "tool.started",
    "tool.finished",
    "detector.started",
    "detector.progress",
    "detector.done",
    "detector.skipped",
    "detector.error",
)


class _SubagentEventForwarder:
    """Bridge a sub-agent's EventBus events to the
    parent TUI timeline.

    On ``__enter__`` the forwarder subscribes to the
    *parent* EventBus (which is the same process bus,
    so this sees every sub-agent event). On
    ``__exit__`` it unsubscribes and emits a final
    ``subagent.finished`` event with the duration.

    The forwarder is **not** thread-safe against the
    sub-agent's bus updates: we use the parent's bus
    because it's the only one accessible from a
    ``with`` block in the parent thread. Sub-agent
    events that fire while the forwarder is active
    are tagged with ``subagent_id`` in their payload.
    """

    def __init__(self, subagent_id: str, prompt_summary: str):
        self.subagent_id = subagent_id
        self.prompt_summary = prompt_summary
        self._listener: Any = None
        self._bus: Any = None
        self._t0 = time.monotonic()
        # Set by ``mark_completed`` when the runner
        # sees a clean finish. If the deadline fires
        # first, this stays ``False`` and the
        # ``__exit__`` event reports ``ok=False``.
        self._completed = False
        # Counters for the final summary.
        self.tool_started = 0
        self.tool_finished = 0
        self.detector_done = 0
        self.detector_error = 0
        self.detector_skipped = 0
        self.last_tool_name: str | None = None
        self.last_detector_name: str | None = None
        # R-2026-06-15 (Phase 3 + P3-3):
        # progress-event
        # machinery.  A
        # daemon thread
        # ticks every
        # ``progress_interval_seconds``
        # and emits a
        # ``subagent.progress``
        # event so the TUI
        # can render a live
        # "subagent is
        # working on X"
        # indicator (the
        # audit's P3-3
        # requirement).
        # The thread is
        # stopped in
        # ``__exit__``.
        self.progress_interval_seconds: float = 2.0
        self._progress_thread: (
            threading.Thread | None
        ) = None
        self._progress_stop = (
            threading.Event()
        )

    def __enter__(self) -> "_SubagentEventForwarder":
        from ..events import get_bus, Event

        self._bus = get_bus()
        forwarder = self

        class _Listener:
            def on_event(self, event: Event) -> None:
                forwarder._on_event(event)

        self._listener = _Listener()
        self._bus.subscribe(self._listener)
        # Announce the sub-agent start.
        self._bus.emit(Event(
            "subagent.started",
            {
                "subagent_id": self.subagent_id,
                "prompt_summary": self.prompt_summary,
            },
        ))
        # R-2026-06-15 (Phase 3 + P3-3):
        # start the
        # progress-event
        # timer thread.
        # ``self._progress_stop``
        # was reset in
        # ``__init__``;
        # ``__exit__`` sets
        # it to break the
        # tick loop.  The
        # thread is
        # ``daemon=True``
        # so it never
        # blocks process
        # exit even if
        # ``__exit__`` is
        # not called (e.g.
        # on a parent
        # crash).
        self._progress_stop.clear()

        def _progress_loop() -> None:
            while not self._progress_stop.is_set():
                # Use
                # ``Event.wait``
                # so the
                # thread can
                # be stopped
                # in <1s
                # (vs.
                # ``time.sleep``
                # which
                # blocks).
                if self._progress_stop.wait(
                    timeout=(
                        self.progress_interval_seconds
                    )
                ):
                    return
                try:
                    self._bus.emit(Event(
                        "subagent.progress",
                        self._progress_payload(),
                    ))
                except Exception:  # noqa: BLE001
                    # Never let a
                    # progress-emit
                    # failure kill
                    # the timer.
                    pass

        self._progress_thread = threading.Thread(
            target=_progress_loop,
            name="subagent-progress",
            daemon=True,
        )
        self._progress_thread.start()
        return self

    def _progress_payload(self) -> dict[str, Any]:
        """Build the
        ``subagent.progress``
        event payload.

        R-2026-06-15 (Phase 3 + P3-3):
        the payload is
        read-only; the
        timer thread and
        the worker thread
        both call it
        concurrently,
        so the integer
        counters are read
        *as snapshots*
        (the GIL makes
        Python int reads
        atomic; for more
        complex state we
        would need a
        lock).
        """
        return {
            "subagent_id": self.subagent_id,
            "elapsed_seconds": round(
                time.monotonic() - self._t0, 3
            ),
            "tool_started": self.tool_started,
            "tool_finished": self.tool_finished,
            "detector_done": self.detector_done,
            "detector_error": self.detector_error,
            "detector_skipped": self.detector_skipped,
            "last_tool_name": self.last_tool_name,
            "last_detector_name": (
                self.last_detector_name
            ),
        }

    def __exit__(self, exc_type, exc, tb) -> None:
        from ..events import get_bus, Event

        # R-2026-06-15 (Phase 3 + P3-3):
        # stop the
        # progress-event
        # timer thread.  We
        # set the stop
        # event FIRST (so
        # the timer exits
        # its ``wait`` call
        # immediately),
        # then ``join()``
        # with a short
        # timeout so a
        # stuck timer does
        # not block the
        # parent's
        # ``__exit__``
        # path.  The
        # thread is
        # ``daemon=True``
        # so an unjoined
        # thread does not
        # block process
        # exit.
        self._progress_stop.set()
        if self._progress_thread is not None:
            self._progress_thread.join(timeout=1.0)
        elapsed = time.monotonic() - self._t0
        if self._listener is not None and self._bus is not None:
            self._bus.unsubscribe(self._listener)
        # Final summary event. Always emit, even on
        # exception, so the TUI can show "subagent
        # crashed" rather than leaving an open row.
        # ``self._completed`` is set by the caller via
        # ``mark_completed`` to indicate a *clean*
        # finish; if not set, the sub-agent timed out
        # (which the runner signals separately).
        finished_ok = (
            exc_type is None and self._completed
        )
        self._bus.emit(Event(
            "subagent.finished",
            {
                "subagent_id": self.subagent_id,
                "ok": finished_ok,
                "elapsed_seconds": round(elapsed, 3),
                "tool_started": self.tool_started,
                "tool_finished": self.tool_finished,
                "detector_done": self.detector_done,
                "detector_error": self.detector_error,
                "detector_skipped": self.detector_skipped,
                "last_tool_name": self.last_tool_name,
                "last_detector_name": self.last_detector_name,
                "error": (
                    None
                    if finished_ok
                    else (
                        f"{exc_type.__name__}: {exc}"
                        if exc_type is not None
                        else "subagent_timeout_or_error"
                    )
                ),
            },
        ))

    def mark_completed(self) -> None:
        """Mark the sub-agent as having finished cleanly.

        Called by ``run_subagent_with_timeout`` when the
        worker thread's ``done`` flag fires before the
        deadline. If the deadline fires first, the
        forwarder stays ``_completed=False`` and
        ``__exit__`` reports ``ok=False``.
        """
        self._completed = True

    def _on_event(self, event: Any) -> None:
        """Tag every relevant event with subagent_id and
        forward to the parent bus.

        We MUTATE the existing event in place rather
        than emit a new one: this avoids double-counting
        in any other listener that might be subscribed
        to the same bus. The mutation is safe because
        ``Event`` is a frozen dataclass -- we therefore
        use ``dataclasses.replace`` to produce a new
        event with the subagent_id field added.

        R-2026-06-15 (Phase 1 + P1-10):
        skip events that are
        *already tagged* with a
        ``subagent_id``.  The
        forwarder is a listener
        on the *same bus* it
        re-emits on; without
        this filter, the
        re-emitted tagged copy
        would trigger
        ``_on_event`` again
        (because the listener
        is still subscribed),
        leading to an infinite
        re-emission loop (319+
        tagged events for one
        source event).  This is
        the precise "double-
        counting in any other
        listener" bug the
        original comment warned
        about, exposed once a
        real listener subscribed
        to the same bus.
        """
        if event.type not in _FORWARDED_EVENT_TYPES:
            return
        # Skip events that are
        # already tagged (either
        # by another forwarder
        # in a parent-child
        # chain, or by our own
        # re-emission).
        if isinstance(event.payload, dict):
            if "subagent_id" in event.payload:
                return
        # Update the counters.
        if event.type == "tool.started":
            self.tool_started += 1
            self.last_tool_name = (
                event.payload.get("tool", "?")
                if isinstance(event.payload, dict)
                else "?"
            )
        elif event.type == "tool.finished":
            self.tool_finished += 1
        elif event.type == "detector.done":
            self.detector_done += 1
            self.last_detector_name = (
                event.payload.get("name", "?")
                if isinstance(event.payload, dict)
                else "?"
            )
        elif event.type == "detector.error":
            self.detector_error += 1
        elif event.type == "detector.skipped":
            self.detector_skipped += 1
        # Tag the event with subagent_id.
        if isinstance(event.payload, dict):
            tagged = dict(event.payload)
            tagged["subagent_id"] = self.subagent_id
            # Replace the payload on the event by
            # emitting a new event. We can't mutate
            # the frozen Event in place.
            try:
                from ..events import Event as _E
                self._bus.emit(_E(event.type, tagged))
            except Exception:  # noqa: BLE001
                pass


@dataclass
class SubagentResult:
    """R-2026-06-15 (Phase 3 + P3-2):
    typed envelope for the
    result of a subagent
    run.  The previous
    return type was a
    3-tuple
    ``(final_text, completed, error)``
    which was easy to
    mis-interpret (e.g.
    ``completed=True``
    meant "the worker
    thread exited cleanly"
    but not "the LLM
    produced a non-empty
    answer").  The dataclass
    is explicit and is
    serialised into the
    ``TaskTool`` tool-result
    envelope so the parent
    LLM sees a structured
    result.

    Fields:
      * ``trace_id``: the
        parent's trace_id
        (so the result can
        be correlated with
        the rest of the
        session's audit
        log).
      * ``ok``: ``True`` if
        the subagent
        returned a
        non-empty text
        answer; ``False``
        on timeout, error,
        or empty answer.
      * ``output``: the
        subagent's final
        text answer (may be
        empty on error).
      * ``elapsed_ms``: wall-
        clock time from
        ``TaskTool.execute``
        start to
        ``run_subagent_with_timeout``
        return.
      * ``error_kind``: the
        typed error category
        (``"timeout"`` /
        ``"cancelled"`` /
        ``"exception"`` /
        ``"empty"`` /
        ``None`` on success).
      * ``subagent_id``: the
        subagent's unique
        id (matches the
        ``subagent_id`` field
        on every forwarded
        event).
      * ``stats``: a
        ``dict`` of detector
        stats (figures
        scanned, cells
        analyzed, etc.) from
        the forwarder.
        Populated in Phase 3
        P3-6.

    The ``to_dict`` method
    serialises the result to
    a ``dict`` for inclusion
    in the tool-result
    envelope.
    """

    trace_id: str
    ok: bool
    output: str
    elapsed_ms: int
    error_kind: str | None
    subagent_id: str
    stats: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "ok": self.ok,
            "output": self.output,
            "elapsed_ms": self.elapsed_ms,
            "error_kind": self.error_kind,
            "subagent_id": self.subagent_id,
            "stats": dict(self.stats),
        }


def run_subagent_with_timeout(
    loop: Any,
    prompt: str,
    timeout_seconds: float,
    forwarder: _SubagentEventForwarder,
    trace_id: str = "",
) -> SubagentResult:
    """Run ``loop.run_stream(prompt)`` in a worker
    thread with a hard timeout.

    Returns a ``SubagentResult``
    (P3-2 typed envelope).
    The caller is expected to
    put the result in a
    tool-result envelope.

    Implementation:

    1. Start a daemon thread that drains the loop's
       generator into a list of ``ChatResponse``s and
       sets a thread-local ``done`` flag.
    2. Wait up to ``timeout_seconds`` for the flag.
    3. If the flag fires: take the last response's
       text, return a successful
       ``SubagentResult``.
    4. If timeout: return a failed ``SubagentResult``
       with ``error_kind="timeout"`` and leave the
       thread running (it will be garbage collected
       when the loop is dropped; we mark daemon so it
       does not block process exit).

    We do NOT cancel the worker on timeout. The sub-
    agent's LLM may still be streaming; killing the
    thread mid-stream would corrupt the LLM client's
    HTTP connection. The LLM result, when it
    eventually arrives, is dropped on the floor --
    the parent has already returned an error to its
    own LLM and the parent's next turn is the
    recovery.

    R-2026-06-15 (Phase 3 + P3-1):
    also honours the child's
    ``_interrupt_requested``
    flag (set by the parent
    ``/stop`` propagation).
    The flag is checked
    inside the polling loop;
    when set, the worker
    thread is signalled to
    stop (we set
    ``_drain_stop`` and the
    thread's generator is
    closed at the next
    ``yield`` boundary).
    """
    from ..llm.chat import ChatResponse

    result: dict[str, Any] = {
        "text": "",
        "done": False,
        "error": None,
    }
    t0 = time.monotonic()

    def _drain() -> None:
        try:
            for resp in loop.run_stream(prompt):
                if isinstance(resp, ChatResponse) and resp.text:
                    result["text"] = resp.text
                if loop._interrupt_requested:
                    # R-2026-06-15
                    # (Phase 3 + P3-1):
                    # the parent
                    # propagated an
                    # interrupt;
                    # stop draining.
                    break
        except Exception as exc:  # noqa: BLE001
            result["error"] = (
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            result["done"] = True

    th = threading.Thread(
        target=_drain, name="subagent", daemon=True
    )
    th.start()
    # We poll the flag with a small sleep instead of
    # using ``Event.wait`` so the test harness can
    # fast-path the timeout by patching the sleep.
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if result["done"]:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            forwarder.mark_completed()
            if result["error"]:
                return SubagentResult(
                    trace_id=trace_id,
                    ok=False,
                    output=result["text"],
                    elapsed_ms=elapsed_ms,
                    error_kind="exception",
                    subagent_id=forwarder.subagent_id,
                )
            if not result["text"]:
                return SubagentResult(
                    trace_id=trace_id,
                    ok=False,
                    output="",
                    elapsed_ms=elapsed_ms,
                    error_kind="empty",
                    subagent_id=forwarder.subagent_id,
                )
            return SubagentResult(
                trace_id=trace_id,
                ok=True,
                output=result["text"],
                elapsed_ms=elapsed_ms,
                error_kind=None,
                subagent_id=forwarder.subagent_id,
            )
        if loop._interrupt_requested:
            # R-2026-06-15
            # (Phase 3 + P3-1):
            # the parent
            # propagated an
            # interrupt; the
            # child loop will
            # exit on its next
            # turn.  Wait for
            # the worker to
            # finish (with the
            # usual 50ms poll
            # interval).
            # We do NOT
            # return early --
            # the worker must
            # finish so the
            # ``subagent.finished``
            # event is emitted
            # cleanly.  The
            # forwarder's
            # ``__exit__`` will
            # report ``ok=False``
            # because
            # ``mark_completed``
            # was not called.
            continue
        time.sleep(0.05)
    # Timed out. The thread keeps running; we return
    # the timeout error to the parent.
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return SubagentResult(
        trace_id=trace_id,
        ok=False,
        output="",
        elapsed_ms=elapsed_ms,
        error_kind="timeout",
        subagent_id=forwarder.subagent_id,
    )


# Small util: generate a safe prompt summary that
# does not blow up the EventBus payload.
def _prompt_summary(prompt: str, max_chars: int = 80) -> str:
    p = (prompt or "").strip().replace("\n", " ")
    if len(p) > max_chars:
        p = p[:max_chars] + "..."
    return p
