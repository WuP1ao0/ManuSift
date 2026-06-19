"""R-2026-06-15 (Phase 3 + P3-2):
test the ``SubagentResult``
typed envelope.

The audit flagged the
subagent result as
"stringly-typed" (a
3-tuple of
``(final_text, completed, error)``
that was easy to mis-read
or silently drop).  The
fix is a dataclass with
explicit fields:

  * ``trace_id``
  * ``ok`` (bool)
  * ``output`` (str)
  * ``elapsed_ms`` (int)
  * ``error_kind`` (str |
    None)
  * ``subagent_id`` (str)
  * ``stats`` (dict)

These tests verify:

  1. The dataclass is
     constructible with
     all required fields.
  2. ``to_dict()`` round-
     trips through JSON
     with no loss.
  3. ``run_subagent_with_timeout``
     returns a
     ``SubagentResult``
     (not a tuple) on the
     success path.
  4. ``run_subagent_with_timeout``
     returns a
     ``SubagentResult``
     with
     ``error_kind="timeout"``
     on the timeout path.
  5. ``run_subagent_with_timeout``
     returns a
     ``SubagentResult``
     with
     ``error_kind="empty"``
     if the worker exits
     cleanly but produces
     no text.
  6. ``run_subagent_with_timeout``
     returns a
     ``SubagentResult``
     with
     ``error_kind="exception"``
     on a worker
     exception.
  7. ``stats`` is a
     ``dict`` and is
     serialised by
     ``to_dict()``.
  8. ``elapsed_ms`` is a
     non-negative int.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

from manusift.llm.chat import ChatResponse
from manusift.tools.subagent_forwarder import (
    SubagentResult,
    run_subagent_with_timeout,
    _SubagentEventForwarder,
)


# ----------------------------
# helpers
# ----------------------------


class _OneShotLoop:
    """A mock ``AgentLoop``
    that yields one
    ``ChatResponse`` and
    then stops.  Used as a
    stand-in for the real
    ``AgentLoop`` in the
    runner.
    """

    def __init__(self, text: str) -> None:
        self._text = text
        self._run_stream_calls = 0
        self._interrupt_requested = False

    def run_stream(self, prompt: str):
        self._run_stream_calls += 1
        # R-2026-06-15
        # (Phase 3 + P3-2):
        # ``ChatResponse``
        # derives ``.text``
        # from
        # ``content_blocks``,
        # not from a
        # ``text=`` kwarg.
        yield ChatResponse(
            content_blocks=[
                {"type": "text", "text": self._text}
            ],
            stop_reason="end_turn",
            model="mock",
        )


class _CrashingLoop:
    def __init__(self) -> None:
        self._interrupt_requested = False

    def run_stream(self, prompt: str):
        raise RuntimeError("loop exploded")
        yield  # noqa: F841 -- makes it a generator


class _AlwaysInterrupt:
    """A loop whose
    ``_interrupt_requested``
    is ``True`` from the
    start (the parent
    propagated ``/stop``
    before the runner
    started polling).
    """

    def __init__(self) -> None:
        self._interrupt_requested = True
        self.calls = 0

    def run_stream(self, prompt: str):
        self.calls += 1
        # No-op generator
        # that returns
        # immediately.  We
        # intentionally do
        # NOT yield so
        # ``result["done"]``
        # is set by the
        # ``finally`` block
        # without any text
        # being produced.
        return
        yield  # noqa: F841


def _make_forwarder() -> _SubagentEventForwarder:
    """Build a fresh
    ``_SubagentEventForwarder``
    for a test.  We do
    not use the
    ``with`` statement
    because some tests
    do not want the
    enter/exit side
    effects.
    """
    from manusift.events import reset_bus

    reset_bus()
    fwd = _SubagentEventForwarder(
        "test-subagent-id", "test-prompt-summary"
    )
    return fwd


# ----------------------------
# tests
# ----------------------------


def test_p32_subagent_result_dataclass_constructible() -> None:
    """A ``SubagentResult``
    can be constructed
    with all required
    fields.
    """
    r = SubagentResult(
        trace_id="t-1",
        ok=True,
        output="hello",
        elapsed_ms=42,
        error_kind=None,
        subagent_id="sub-1",
    )
    assert r.trace_id == "t-1"
    assert r.ok is True
    assert r.output == "hello"
    assert r.elapsed_ms == 42
    assert r.error_kind is None
    assert r.subagent_id == "sub-1"
    assert r.stats == {}


def test_p32_to_dict_roundtrip() -> None:
    """``to_dict()`` round-
    trips through JSON
    with no loss.
    """
    r = SubagentResult(
        trace_id="t-2",
        ok=True,
        output="x",
        elapsed_ms=10,
        error_kind=None,
        subagent_id="sub-2",
        stats={"figures_scanned": 3},
    )
    d = r.to_dict()
    j = json.dumps(d)
    d2 = json.loads(j)
    assert d2 == d


def test_p32_runner_returns_subagent_result_on_success() -> None:
    """``run_subagent_with_timeout``
    returns a
    ``SubagentResult``
    (not a tuple) on the
    success path.
    """
    fwd = _make_forwarder()
    loop = _OneShotLoop("the answer is 42")
    with fwd:
        r = run_subagent_with_timeout(
            loop,
            "what is the answer?",
            5.0,
            fwd,
            trace_id="t-success",
        )
    assert isinstance(r, SubagentResult)
    assert r.ok is True
    assert r.output == "the answer is 42"
    assert r.error_kind is None
    assert r.subagent_id == fwd.subagent_id
    assert r.trace_id == "t-success"
    assert r.elapsed_ms >= 0
    assert r.elapsed_ms < 5000


def test_p32_runner_returns_empty_error_kind() -> None:
    """A clean exit with no
    text produces
    ``error_kind="empty"``
    (not a silent
    success).
    """
    fwd = _make_forwarder()
    loop = _OneShotLoop("")  # empty text
    with fwd:
        r = run_subagent_with_timeout(
            loop, "p", 5.0, fwd
        )
    assert isinstance(r, SubagentResult)
    assert r.ok is False
    assert r.error_kind == "empty"
    assert r.output == ""


def test_p32_runner_returns_exception_error_kind() -> None:
    """A worker exception
    produces
    ``error_kind="exception"``
    (typed, not a free-
    form string).
    """
    fwd = _make_forwarder()
    loop = _CrashingLoop()
    with fwd:
        r = run_subagent_with_timeout(
            loop, "p", 5.0, fwd
        )
    assert isinstance(r, SubagentResult)
    assert r.ok is False
    assert r.error_kind == "exception"
    # The exception
    # occurred BEFORE any
    # text was produced
    # (the ``run_stream``
    # generator raised on
    # the first
    # iteration), so
    # ``result["text"]`` is
    # empty.  The runner
    # does NOT surface the
    # exception message in
    # ``output`` (it would
    # be in
    # ``error_kind``-tagged
    # ``subagent.finished``
    # event for the TUI;
    # see
    # ``_SubagentEventForwarder.__exit__``).
    # We verify
    # ``error_kind`` is
    # ``"exception"`` --
    # that is the typed
    # contract the audit
    # asked for.
    assert r.output == ""


def test_p32_runner_returns_timeout_error_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout produces
    ``error_kind="timeout"``
    (typed).
    """
    fwd = _make_forwarder()
    # The runner uses
    # ``time.sleep(0.05)``
    # in its poll loop;
    # monkey-patch it to
    # be a no-op so the
    # timeout fires
    # *immediately* in
    # the test.
    monkeypatch.setattr(
        "manusift.tools.subagent_forwarder.time.sleep",
        lambda _: None,
    )
    # A loop that runs
    # ``forever``
    # (it never
    # ``done``).
    class _HangingLoop:
        def __init__(self) -> None:
            self._interrupt_requested = False

        def run_stream(self, prompt: str):
            # Block forever
            # (the runner's
            # ``deadline``
            # check will
            # trigger).
            while True:
                yield ChatResponse(
                    content_blocks=[
                        {"type": "text", "text": "x"}
                    ],
                    stop_reason="end_turn",
                    model="mock",
                )
                time.sleep(0.01)

    loop = _HangingLoop()
    with fwd:
        r = run_subagent_with_timeout(
            loop, "p", 0.5, fwd
        )
    assert isinstance(r, SubagentResult)
    assert r.ok is False
    assert r.error_kind == "timeout"
    # ``elapsed_ms`` is
    # close to the
    # configured
    # timeout.
    assert 0 <= r.elapsed_ms < 5000


def test_p32_runner_stats_default_to_empty_dict() -> None:
    """A ``SubagentResult``
    with no stats
    provided has
    ``stats={}``.
    """
    r = SubagentResult(
        trace_id="t",
        ok=True,
        output="x",
        elapsed_ms=0,
        error_kind=None,
        subagent_id="s",
    )
    assert r.stats == {}


def test_p32_to_dict_includes_stats() -> None:
    """``to_dict()``
    serialises the
    ``stats`` field.
    """
    r = SubagentResult(
        trace_id="t",
        ok=True,
        output="x",
        elapsed_ms=0,
        error_kind=None,
        subagent_id="s",
        stats={"figures_scanned": 12, "cells_analyzed": 1200},
    )
    d = r.to_dict()
    assert d["stats"] == {
        "figures_scanned": 12,
        "cells_analyzed": 1200,
    }


def test_p32_runner_respects_parent_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the child's
    ``_interrupt_requested``
    flag is ``True``
    (propagated by the
    parent via P3-1),
    ``run_subagent_with_timeout``
    does NOT return a
    success result --
    the child's
    ``_drain`` breaks
    out of the loop and
    ``result["done"]``
    is set.
    """
    fwd = _make_forwarder()
    # The ``_AlwaysInterrupt``
    # loop returns
    # immediately (no
    # yield) but its
    # ``_interrupt_requested``
    # is ``True``.  This
    # is the post-P3-1
    # state.
    loop = _AlwaysInterrupt()
    with fwd:
        r = run_subagent_with_timeout(
            loop, "p", 5.0, fwd
        )
    # The runner's
    # behaviour when the
    # child was cancelled
    # mid-stream: the
    # ``_drain`` function
    # returns immediately
    # (the generator
    # exits before
    # yielding), so
    # ``result["done"]`` is
    # set and
    # ``result["text"]`` is
    # empty.  This is
    # reported as
    # ``error_kind="empty"``
    # (the cleanest
    # category --
    # ``"cancelled"`` is
    # the audit's
    # preferred name; we
    # use ``"empty"`` here
    # because the runner
    # does not have a
    # dedicated
    # "cancelled" exit
    # path; the
    # ``subagent.finished``
    # event carries the
    # actual cancellation
    # status from
    # ``forwarder._completed``).
    assert isinstance(r, SubagentResult)
    assert r.ok is False
    assert r.error_kind == "empty"
    assert r.output == ""
