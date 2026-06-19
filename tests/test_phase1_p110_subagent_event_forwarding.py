"""R-2026-06-15 (Phase 1 + P1-10):
verify the ``_SubagentEventForwarder``
contract.

The audit flagged the TUI
"sub-agent tool-call
visibility" as a gap: the
forwarder is wired (it tags
every sub-agent event with
``payload['subagent_id']``)
but the TUI ``chat_app.py``
does not yet subscribe to
the parent bus to render
``[sub:abc1] tool=...``
rows.

This test verifies the
**forwarder contract**
(what the TUI *would*
consume):

  1. A tool event on the
     parent bus that
     matches a
     ``_FORWARDED_EVENT_TYPES``
     key (``tool.started``,
     ``tool.finished``,
     ``detector.*``) is
     re-emitted with
     ``payload['subagent_id']``
     set.
  2. The ``subagent.started``
     event is emitted on
     ``__enter__``.
  3. The
     ``subagent.finished``
     event is emitted on
     ``__exit__``.
  4. Events NOT in
     ``_FORWARDED_EVENT_TYPES``
     are NOT re-emitted
     (the forwarder filters
     them out so the TUI
     timeline is not
     flooded with non-
     sub-agent events).
  5. ``short_subagent_prefix``
     returns the first 7
     characters (the
     format the TUI uses
     for ``[sub:abc1]``
     rows).

The TUI rendering itself
is out of scope for Phase 1
(``chat_app.py`` is a 6044-line
god-file that needs the
Phase 4 refactor before
new TUI features can land
safely; per the USER.md
hard contract, the TUI
structure is a Phase 4+
user-confirmed change).

R-2026-06-15 (Phase 1 + P1-10 fix):
the forwarder subscribes to
the **process-global bus**
(``manusift.events.get_bus()``).
Tests that exercise the
forwarder must
``reset_bus()`` BEFORE the
forwarder ``__enter__`` --
otherwise the previous
forwarder instance is
still subscribed, and any
event it re-emits is
captured by *this* test's
listener (and the cycle
repeats until ``_listener``
hits 320+ entries).
"""
from __future__ import annotations

import pytest

from manusift.events import (
    Event,
    EventBus,
    get_bus,
    reset_bus,
)
from manusift.tools.subagent_forwarder import (
    _FORWARDED_EVENT_TYPES,
    _SubagentEventForwarder,
    new_subagent_id,
    short_subagent_prefix,
)


@pytest.fixture
def fresh_bus() -> EventBus:
    """Reset the process-global
    bus before each test so
    that the previous
    forwarder is detached.
    Yields the fresh bus for
    the test to subscribe a
    listener on.
    """
    reset_bus()
    bus = get_bus()
    yield bus
    # ``bus`` is now a
    # dangling reference
    # (next ``reset_bus()``
    # will replace it).  No
    # need to do anything
    # here -- the listener
    # goes out of scope with
    # the test.


def _make_listener(received: list) -> object:
    """Build a listener that
    appends to ``received``.
    """

    class _L:
        def on_event(self, event: Event) -> None:
            received.append(event)

    return _L()


def test_p110_subagent_id_format():
    """``new_subagent_id()``
    returns a string starting
    with ``"sub:"``.
    """
    sid = new_subagent_id()
    assert sid.startswith("sub:")
    # Long enough to be unique
    # but short enough for the
    # TUI prefix.
    assert len(sid) >= 8


def test_p110_short_subagent_prefix_returns_7_chars():
    """``short_subagent_prefix``
    returns the first 7
    characters (the format
    the TUI uses for
    ``[sub:abc1]`` rows).
    """
    sid = "sub:abcdef1234"
    assert short_subagent_prefix(sid) == "sub:abc"


def test_p110_short_subagent_prefix_handles_non_sub_id():
    """If the id does NOT
    start with ``"sub:"``,
    the prefix function
    still returns the first
    7 characters (best-effort
    fallback for malformed
    ids).
    """
    assert (
        short_subagent_prefix("not-a-sub-id") == "not-a-s"
    )


def test_p110_forwarder_emits_started_on_enter(
    fresh_bus: EventBus,
) -> None:
    """The forwarder emits a
    ``subagent.started``
    event on the parent bus
    when ``__enter__`` is
    called.
    """
    received: list[Event] = []
    fresh_bus.subscribe(_make_listener(received))
    sid = "sub:test123"
    with _SubagentEventForwarder(sid, "test summary"):
        pass
    types = [e.type for e in received]
    assert "subagent.started" in types
    assert "subagent.finished" in types


def test_p110_forwarder_tags_event_with_subagent_id(
    fresh_bus: EventBus,
) -> None:
    """A ``tool.started`` event
    on the parent bus is
    forwarded by the
    forwarder (re-emitted with
    ``payload['subagent_id']``
    set).

    R-2026-06-15 (Phase 1 + P1-10):
    the forwarder only
    forwards events whose
    ``type`` is in
    ``_FORWARDED_EVENT_TYPES``
    (see
    ``subagent_forwarder.py``).
    The set covers
    ``tool.started``,
    ``tool.finished``, and
    ``detector.*``.
    """
    received: list[Event] = []
    fresh_bus.subscribe(_make_listener(received))
    sid = "sub:forward1"
    with _SubagentEventForwarder(sid, "do thing"):
        fresh_bus.emit(
            Event(
                type="tool.started",
                payload={
                    "tool": "image_dup",
                    "tool_id": "t1",
                },
            )
        )
    tool_events = [
        e for e in received if e.type == "tool.started"
    ]
    # The forwarder re-emits
    # the original event with
    # ``subagent_id`` added,
    # so we expect exactly
    # ONE ``tool.started``
    # event in the received
    # list (the re-emitted
    # tagged copy), plus the
    # original which was
    # filtered out (the
    # forwarder's listener
    # fires before the
    # subscriber; the
    # original event hits
    # the listener, gets
    # tagged, and the
    # forwarder's bus.emit
    # re-emits the tagged
    # copy -- the tagged copy
    # ALSO reaches our test
    # listener).
    # So we get 2 events:
    # the original (no tag)
    # and the re-emitted
    # tagged copy.
    assert len(tool_events) >= 1
    # At least one of the
    # ``tool.started`` events
    # has ``subagent_id`` set.
    tagged = [
        e
        for e in tool_events
        if e.payload.get("subagent_id") == sid
    ]
    assert len(tagged) == 1, (
        f"expected exactly one "
        f"tagged copy; got "
        f"{len(tagged)} tagged "
        f"and {len(tool_events)} "
        f"total"
    )


def test_p110_forwarder_does_not_forward_unknown_event_types(
    fresh_bus: EventBus,
) -> None:
    """The forwarder only
    forwards events whose
    ``type`` is in
    ``_FORWARDED_EVENT_TYPES``.
    Other events on the bus
    pass through unchanged
    (no ``subagent_id`` is
    added; they are not
    re-emitted).
    """
    received: list[Event] = []
    fresh_bus.subscribe(_make_listener(received))
    sid = "sub:filter1"
    with _SubagentEventForwarder(sid, "filter test"):
        # ``random.event`` is
        # NOT in
        # ``_FORWARDED_EVENT_TYPES``.
        fresh_bus.emit(
            Event(
                type="random.event",
                payload={"x": 1},
            )
        )
    random_events = [
        e for e in received if e.type == "random.event"
    ]
    # The original event
    # reached the listener
    # (the forwarder does
    # NOT swallow unknown
    # events).  No tagged
    # copy was re-emitted.
    assert len(random_events) == 1
    assert (
        random_events[0].payload.get("subagent_id")
        is None
    )


def test_p110_forwarded_event_types_match_audit_documented_set() -> None:
    """The
    ``_FORWARDED_EVENT_TYPES``
    set must include
    ``tool.started`` and
    ``tool.finished`` (the
    events that sub-agent
    tool calls emit on the
    parent bus).  A future
    refactor that drops one
    of these would silently
    break the TUI timeline.
    """
    assert "tool.started" in _FORWARDED_EVENT_TYPES
    assert "tool.finished" in _FORWARDED_EVENT_TYPES


def test_p110_forwarder_is_idempotent_for_single_event(
    fresh_bus: EventBus,
) -> None:
    """A single ``tool.started``
    event yields exactly one
    tagged re-emitted event
    on the parent bus
    (the forwarder does NOT
    loop).
    """
    received: list[Event] = []
    fresh_bus.subscribe(_make_listener(received))
    sid = "sub:idemp1"
    with _SubagentEventForwarder(sid, "x"):
        fresh_bus.emit(
            Event(
                type="tool.started",
                payload={
                    "tool": "x",
                    "tool_id": "t1",
                },
            )
        )
    # Count tagged
    # ``tool.started`` events
    # (those with our
    # ``subagent_id``).
    tagged = [
        e
        for e in received
        if e.type == "tool.started"
        and e.payload.get("subagent_id") == sid
    ]
    assert len(tagged) == 1
