"""Smoke tests for the chat-tui detector-trace integration
(R-2026-06-13).

These tests cover the *seam* between the chat app and the
detector-trace layer: they assert the symbols import
correctly, the bus listener is registered on first turn,
and the key binding is wired up. We do not run the
textual app in a Pilot harness here (that is a separate,
heavier test layer in the existing test suite).

Covers:

  1. **Symbols import** (test_detector_block_symbols):
     the chat app re-exports the new symbols
     (DetectorTraceBlock, install_default_listener,
     ALL_DETECTOR_EVENTS).
  2. **Key binding wired**
     (test_x_keybinding_is_registered): the ``x`` key
     triggers ``action_toggle_detector_trace`` on the
     chat app.
  3. **No raw JSON leaks into the block**
     (test_no_raw_json_in_detector_block): the per-row
     expansion never includes the raw finding JSON.
  4. **Lifecycle from event to summary line**
     (test_event_to_summary_round_trip): a
     ``detector.*`` event ends up reflected in the
     summary line of the block.
  5. **Final sealed summary** (test_final_sealed_summary):
     after a complete run, the summary line is the
     final form (no "running…" suffix) and matches the
     user's spec.
"""
from __future__ import annotations

from manusift.events import Event
from manusift.tui.chat_app import (
    ALL_DETECTOR_EVENTS,
    DetectorTraceBlock,
    install_default_listener,
)


# ---------- 1. symbols import ----------

def test_detector_block_symbols() -> None:
    """The chat-app re-exports the new detector-trace symbols."""
    assert DetectorTraceBlock is not None
    assert install_default_listener is not None
    assert "detector.started" in ALL_DETECTOR_EVENTS
    assert "detector.done" in ALL_DETECTOR_EVENTS
    assert "detector.skipped" in ALL_DETECTOR_EVENTS
    assert "detector.error" in ALL_DETECTOR_EVENTS


# ---------- 2. key binding wired ----------

def test_x_keybinding_is_registered() -> None:
    """The ``x`` key triggers ``action_toggle_detector_trace``.

    We introspect the ``BINDINGS`` class attribute on
    ``ChatApp`` and assert the action is present. This
    protects against a refactor that drops the binding.
    """
    from manusift.tui.chat_app import ChatApp
    binding_actions = {b.action for b in ChatApp.BINDINGS}
    assert "toggle_detector_trace" in binding_actions


# ---------- 3. no raw JSON in expanded block ----------

def test_no_raw_json_in_detector_block() -> None:
    """The detector block never includes raw finding JSON."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "r", "detector_count": 1},
    ))
    block.on_event_received(Event(
        "detector.done", {
            "trace_id": "r", "detector": "image_dup",
            "duration_ms": 10, "findings_count": 50,
        },
    ))
    block.set_collapsed(False)
    expanded = block._expanded_block().plain
    # No JSON shapes leak.
    assert "{" not in expanded
    assert "\"detector\"" not in expanded
    assert "evidence" not in expanded


# ---------- 4. event to summary round-trip ----------

def test_event_to_summary_round_trip() -> None:
    """A full lifecycle of events ends up reflected in the
    block's summary line."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "t", "detector_count": 3},
    ))
    # Done 2
    for name in ("a", "b"):
        block.on_event_received(Event(
            "detector.done", {
                "trace_id": "t", "detector": name,
                "duration_ms": 1, "findings_count": 2,
            },
        ))
    # Skipped 1
    block.on_event_received(Event(
        "detector.skipped", {
            "trace_id": "t", "detector": "c",
            "reason": "no data",
        },
    ))
    s = block._summary_line().plain
    assert "2/3 done" in s
    assert "4 findings" in s
    assert "1 skipped" in s
    # No "running" suffix because nothing is in flight.
    assert "running" not in s


# ---------- 5. final sealed summary ----------

def test_final_sealed_summary() -> None:
    """After a full run (no in-flight detectors), the
    summary line is in its final form and matches the
    user's spec (``detectors 38/38 done · 5 findings ·
    7 skipped · 0 errors``)."""
    block = DetectorTraceBlock()
    block.on_event_received(Event(
        "job.started", {"trace_id": "f", "detector_count": 3},
    ))
    # Done with 5 findings.
    block.on_event_received(Event(
        "detector.started", {"trace_id": "f", "detector": "a"},
    ))
    block.on_event_received(Event(
        "detector.done", {
            "trace_id": "f", "detector": "a",
            "duration_ms": 10, "findings_count": 5,
        },
    ))
    # Skipped 1.
    block.on_event_received(Event(
        "detector.skipped", {
            "trace_id": "f", "detector": "b",
            "reason": "no data",
        },
    ))
    # Error 1.
    block.on_event_received(Event(
        "detector.error", {
            "trace_id": "f", "detector": "c",
            "error": "boom", "duration_ms": 1,
        },
    ))
    block.on_event_received(Event(
        "job.completed", {"trace_id": "f"},
    ))
    s = block._summary_line().plain
    assert "1/3 done" in s
    assert "5 findings" in s
    assert "1 skipped" in s
    assert "1 error" in s
    # The "running…" suffix is gone because nothing is in flight.
    assert "running…" not in s


# ---------- 6. listener installs correctly ----------

def test_install_default_listener_returns_handle() -> None:
    """install_default_listener returns a Listener-shaped object."""
    block = DetectorTraceBlock()
    listener = install_default_listener(block)
    assert listener is not None
    # Listener has the expected name.
    assert getattr(listener, "name", None) == "detector_trace_block"
    # Forwarding a no-op event does not raise.
    listener.on_event(Event(
        "detector.started", {"trace_id": "x", "detector": "d"},
    ))