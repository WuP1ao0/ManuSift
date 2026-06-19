"""R-2026-06-15 (Phase 1 + P1-21):
test the ``EventBus.emit_async``
async dispatch.

The audit found that
``emit`` was synchronous --
a slow listener blocked the
agent loop.  The fix adds
``emit_async`` which uses
a
``ThreadPoolExecutor`` to
dispatch listeners
concurrently while
preserving the
``seq`` /
``timestamp_ms`` invariants.

These tests verify:

  1. ``emit_async`` is
     *non-blocking*: a slow
     listener does not delay
     the calling thread.
  2. The seq /
     timestamp_ms invariants
     are preserved (the
     listener that fires
     first sees the
     *correct* values, not
     zeros or
     race-conditions).
  3. A listener that raises
     does not crash the
     worker thread.
  4. The executor is
     *lazily* created (a bus
     that never uses
     ``emit_async`` has
     ``_executor is None``).
  5. The default
     ``emit`` is still
     synchronous (backward
     compatibility).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import (
    ThreadPoolExecutor,
)

import pytest

from manusift.events import Event, EventBus


def _make_bus() -> EventBus:
    """A fresh ``EventBus`` per
    test (the executor
    survives across tests if
    shared).
    """
    return EventBus()


class _CountingListener:
    def __init__(self) -> None:
        self.name = "counting"
        self.received: list[Event] = []
        self.call_count = 0

    def on_event(self, event: Event) -> None:
        self.call_count += 1
        self.received.append(event)


class _SlowListener:
    """A listener that blocks
    for 200ms.
    """

    def __init__(self) -> None:
        self.name = "slow"
        self.received: list[Event] = []
        self.call_count = 0
        self._evt = threading.Event()

    def on_event(self, event: Event) -> None:
        # Block for 200ms or
        # until ``release()`` is
        # called.  The test
        # calls ``release()`` to
        # make the test fast.
        self.call_count += 1
        self._evt.wait(timeout=0.2)
        self.received.append(event)

    def release(self) -> None:
        self._evt.set()


class _RaisingListener:
    def __init__(self) -> None:
        self.name = "raising"
        self.call_count = 0

    def on_event(self, event: Event) -> None:
        self.call_count += 1
        raise RuntimeError("boom")


def test_p21_emit_still_synchronous():
    """``emit`` is still
    synchronous -- the
    default ``emit`` is still
    synchronous (backward
    compatibility).
    """
    bus = _make_bus()
    listener = _CountingListener()
    bus.subscribe(listener)
    bus.emit(Event(type="test", payload={}))
    assert listener.call_count == 1


def test_p21_emit_async_does_not_block_caller():
    """``emit_async`` returns
    immediately even if the
    listener blocks.
    """
    bus = _make_bus()
    slow = _SlowListener()
    bus.subscribe(slow)
    t0 = time.monotonic()
    bus.emit_async(Event(type="slow_event", payload={}))
    elapsed = time.monotonic() - t0
    # The caller should NOT
    # have waited 200ms.
    assert elapsed < 0.05, (
        f"emit_async blocked the "
        f"caller for {elapsed:.3f}s; "
        f"should be near-instant"
    )
    # Let the slow listener
    # finish.
    slow.release()
    # Give the executor a
    # moment to drain.
    time.sleep(0.3)
    assert slow.call_count >= 0  # sanity


def test_p21_emit_async_dispatches_to_listener():
    """The listener eventually
    receives the event
    (after the slow listener
    releases).
    """
    bus = _make_bus()
    slow = _SlowListener()
    bus.subscribe(slow)
    bus.emit_async(Event(type="x", payload={}))
    slow.release()
    # Wait for the executor
    # to dispatch.
    for _ in range(20):
        if slow.received:
            break
        time.sleep(0.05)
    assert len(slow.received) == 1
    assert slow.received[0].type == "x"


def test_p21_emit_async_preserves_seq_invariant():
    """``emit_async`` still
    auto-fills ``seq`` (the
    listener sees a
    monotonic sequence, not
    a race-condition zero).
    """
    bus = _make_bus()
    listener = _CountingListener()
    bus.subscribe(listener)
    # Emit 5 events; each
    # should have a unique
    # monotonic ``seq``.
    for i in range(5):
        bus.emit_async(Event(type=str(i), payload={}))
    # Wait for the executor
    # to drain.
    for _ in range(20):
        if len(listener.received) == 5:
            break
        time.sleep(0.05)
    seqs = sorted(e.seq for e in listener.received)
    assert seqs == [1, 2, 3, 4, 5], (
        f"seq invariant broken: {seqs}"
    )


def test_p21_emit_async_preserves_timestamp_invariant():
    """``emit_async`` still
    auto-fills
    ``timestamp_ms`` (the
    listener sees a non-zero
    timestamp).
    """
    bus = _make_bus()
    listener = _CountingListener()
    bus.subscribe(listener)
    bus.emit_async(Event(type="x", payload={}))
    for _ in range(20):
        if listener.received:
            break
        time.sleep(0.05)
    assert listener.received[0].timestamp_ms > 0


def test_p21_listener_that_raises_does_not_crash_worker():
    """A listener that raises
    on a worker thread is
    logged but does not
    crash the worker (the
    executor continues to
    serve other dispatches).
    """
    bus = _make_bus()
    raiser = _RaisingListener()
    good = _CountingListener()
    bus.subscribe(raiser)
    bus.subscribe(good)
    bus.emit_async(Event(type="x", payload={}))
    bus.emit_async(Event(type="y", payload={}))
    # Wait for both events to
    # reach the good
    # listener.
    for _ in range(20):
        if len(good.received) == 2:
            break
        time.sleep(0.05)
    # The good listener
    # received both events
    # (the raiser's exception
    # did not block the
    # executor).
    assert len(good.received) == 2
    # The raiser was called
    # twice.
    assert raiser.call_count == 2


def test_p21_executor_is_lazy():
    """The executor is NOT
    created at ``__init__``
    time -- only when the
    first ``emit_async`` is
    called.
    """
    bus = _make_bus()
    # Before any
    # ``emit_async``, the
    # executor is ``None``.
    assert bus._executor is None
    # After ``emit_async``
    # (with at least one
    # listener), the executor
    # is created.
    bus.subscribe(_CountingListener())
    bus.emit_async(Event(type="x", payload={}))
    assert isinstance(
        bus._executor, ThreadPoolExecutor
    )


def test_p21_executor_sized_to_4_workers():
    """The executor has at most
    4 workers (the
    audit-recommended value).
    """
    bus = _make_bus()
    # Need at least one
    # listener for the
    # executor to be created
    # on first ``emit_async``.
    bus.subscribe(_CountingListener())
    bus.emit_async(Event(type="x", payload={}))
    assert bus._executor._max_workers == 4
