"""Tests for the R-2026-06-14 P0.3 event metadata envelope.

The contract:

  * The bus auto-fills ``seq`` (monotonic per-process)
    and ``timestamp_ms`` (wall-clock milliseconds) on
    every emitted event.
  * The caller supplies ``provenance``,
    ``emitter_identity``, and ``trace_id`` -- the bus
    does not invent them.
  * ``emit_envelope`` is a convenience that defaults
    ``emitter_identity`` to the caller's frame
    (``<module>.<function>``).
  * The original ``ts`` (monotonic seconds) is still
    populated, so interval math still works.

Pattern follows claw-code's g004
``docs/g004-events-reports-contract.md`` (4 metadata
fields on every event).
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

from manusift.events import (
    Event,
    EventBus,
    emit_envelope,
    get_bus,
    reset_bus,
)


# --------------------------------------------------------------------
# auto-fill on emit
# --------------------------------------------------------------------


def test_emit_autofills_seq_and_timestamp():
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit(Event("t1", {"x": 1}))
    bus.emit(Event("t2", {"x": 2}))
    bus.emit(Event("t3", {"x": 3}))
    seqs = [e.seq for e in captured]
    assert seqs == [1, 2, 3]
    for e in captured:
        # Wall-clock milliseconds -- must be > 0 and
        # within a sane range of ``time.time()``.
        assert e.timestamp_ms > 0
        now_ms = int(time.time() * 1000)
        # Allow a small slack for clock jitter.
        assert abs(e.timestamp_ms - now_ms) < 60_000


def test_emit_does_not_overwrite_explicit_seq():
    """A caller that already set ``seq`` keeps it
    (so test fixtures and replay tools can preserve
    a sequence number).
    """
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit(Event("t1", {}, seq=42))
    bus.emit(Event("t2", {}))
    # The first event keeps its caller-supplied
    # ``seq`` so replay tools can preserve the
    # original sequence number.
    assert captured[0].seq == 42
    # The second event gets the bus's monotonic
    # counter (it incremented to 1 when the
    # first event was emitted; the second emit
    # bumps it to 2).
    assert captured[1].seq == 2
    # And the two seq numbers are distinct.
    assert captured[0].seq != captured[1].seq


def test_emit_does_not_overwrite_explicit_timestamp_ms():
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit(Event("t1", {}, timestamp_ms=999_999))
    assert captured[0].timestamp_ms == 999_999


# --------------------------------------------------------------------
# caller-supplied fields
# --------------------------------------------------------------------


def test_event_carries_provenance_and_emitter():
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit(Event(
        "tool.started",
        {"tool": "bash"},
        provenance="agent._execute_tool_calls",
        emitter_identity="manusift.agent.AgentLoop",
        trace_id="t-42",
    ))
    e = captured[0]
    assert e.provenance == "agent._execute_tool_calls"
    assert e.emitter_identity == "manusift.agent.AgentLoop"
    assert e.trace_id == "t-42"
    # Bus still auto-fills seq / timestamp_ms.
    assert e.seq == 1
    assert e.timestamp_ms > 0


# --------------------------------------------------------------------
# emit_envelope helper
# --------------------------------------------------------------------


def test_emit_envelope_helper_autofills_emitter_identity():
    """``emit_envelope`` falls back to the
    caller's frame (``<module>.<function>``)
    when no ``emitter_identity`` is passed.
    """
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit_envelope(
        "x.test",
        {"k": 1},
        provenance="unit-test",
    )
    e = captured[0]
    assert e.provenance == "unit-test"
    assert e.emitter_identity is not None
    # The frame lookup should land in this
    # test module.
    assert "test_event_envelope" in e.emitter_identity


def test_emit_envelope_helper_uses_explicit_emitter():
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit_envelope(
        "x.test",
        emitter_identity="my.module.MyClass",
    )
    assert captured[0].emitter_identity == "my.module.MyClass"


def test_module_level_emit_envelope_convenience(monkeypatch):
    """``emit_envelope`` at module scope uses
    the global bus.
    """
    reset_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    get_bus().subscribe(_L())
    emit_envelope(
        "global.test",
        {"v": 1},
        provenance="module-level-test",
    )
    assert len(captured) == 1
    assert captured[0].type == "global.test"
    assert captured[0].provenance == "module-level-test"
    assert captured[0].seq >= 1


# --------------------------------------------------------------------
# backward compatibility
# --------------------------------------------------------------------


def test_event_default_construction_still_works():
    """Existing call sites that do ``Event(type, payload)``
    keep working. ``seq``/``timestamp_ms`` are filled
    on ``emit``.
    """
    e = Event("t", {"x": 1})
    assert e.seq == 0
    assert e.timestamp_ms == 0
    assert e.provenance is None
    assert e.emitter_identity is None
    assert e.trace_id is None
    # Bus fills on emit.
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    bus.emit(e)
    assert captured[0].seq >= 1
    assert captured[0].timestamp_ms > 0


def test_bus_preserves_ts_monotonic_for_backcompat():
    """The legacy ``ts`` field is still
    populated (monotonic seconds), so
    interval math keeps working.
    """
    bus = EventBus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    bus.subscribe(_L())
    t_before = time.monotonic()
    bus.emit(Event("t", {}))
    t_after = time.monotonic()
    e = captured[0]
    assert t_before <= e.ts <= t_after


# --------------------------------------------------------------------
# sequence is monotonic across emit() calls
# --------------------------------------------------------------------


def test_seq_strictly_monotonic_across_emits():
    bus = EventBus()
    seqs: list[int] = []

    class _L:
        def on_event(self, event: Event) -> None:
            seqs.append(event.seq)

    bus.subscribe(_L())
    for i in range(20):
        bus.emit(Event(f"t{i}", {}))
    assert seqs == sorted(set(seqs))
    assert seqs[-1] == 20
