"""Tests for the detector-trace instrumentation layer
(R-2026-06-13).

Covers:

  1. **Event lifecycle** (test_event_lifecycle_round_trip): a
     started -> done pair populates the trace correctly.
  2. **Skip event** (test_skip_event): detector.skipped
     populates ``skip_reason``.
  3. **Error event** (test_error_event): detector.error
     populates ``error`` + ``duration_ms``.
  4. **Progress event** (test_progress_event_updates_phase):
     detector.progress updates the in-flight detector's
     ``phase`` field.
  5. **Heuristic + is_builtin** (test_should_skip_plugin_is_no_op):
     plugin detectors are not pre-skipped.
  6. **No deadlock on to_summary** (test_to_summary_does_not_deadlock):
     regression for the to_summary() lock re-entrancy bug.
  7. **Listener on_event bridges correctly** (test_listener_bridges):
     DetectorTraceListener writes the right fields to the
     trace.
"""
from __future__ import annotations

from manusift.detector_trace import (
    DETECTOR_DONE,
    DETECTOR_ERROR,
    DETECTOR_PROGRESS,
    DETECTOR_SKIPPED,
    DETECTOR_STARTED,
    DetectorTrace,
    DetectorTraceListener,
    should_skip_detector,
)
from manusift.events import Event, get_bus


def _doc(text_blocks=None, tables=None, images=None, source_path="/x.pdf"):
    """Build a minimal doc duck-type for the skip heuristic."""
    class _TextBlock:
        def __init__(self, t):
            self.text = t
    tb = [_TextBlock(t) for t in (text_blocks or [])]
    return type(
        "D", (), {
            "text_blocks": tb, "tables": tables or [],
            "images": images or [],
            "source_path": source_path,
        }
    )()


# ---------- 1. event lifecycle ----------

def test_event_lifecycle_round_trip() -> None:
    """A started -> done pair populates the trace correctly."""
    trace = DetectorTrace(trace_id="t1", total=1)
    listener = DetectorTraceListener(trace)
    listener.on_event(Event(DETECTOR_STARTED, {
        "trace_id": "t1", "detector": "metadata",
    }))
    listener.on_event(Event(DETECTOR_DONE, {
        "trace_id": "t1", "detector": "metadata",
        "duration_ms": 42, "findings_count": 3,
    }))
    assert len(trace.records) == 1
    e = trace.records[0]
    assert e.detector == "metadata"
    assert e.status == DETECTOR_DONE
    assert e.duration_ms == 42
    assert e.finding_count == 3


def test_skip_event() -> None:
    """detector.skipped populates skip_reason."""
    trace = DetectorTrace(trace_id="t2", total=1)
    listener = DetectorTraceListener(trace)
    listener.on_event(Event(DETECTOR_SKIPPED, {
        "trace_id": "t2", "detector": "image_dup",
        "reason": "no raster images extracted from PDF",
    }))
    assert len(trace.records) == 1
    e = trace.records[0]
    assert e.status == DETECTOR_SKIPPED
    assert e.skip_reason == "no raster images extracted from PDF"


def test_error_event() -> None:
    """detector.error populates error + duration_ms."""
    trace = DetectorTrace(trace_id="t3", total=1)
    listener = DetectorTraceListener(trace)
    listener.on_event(Event(DETECTOR_ERROR, {
        "trace_id": "t3", "detector": "text_patterns",
        "error": "UnicodeDecodeError: bad byte", "duration_ms": 12,
    }))
    e = trace.records[0]
    assert e.status == DETECTOR_ERROR
    assert e.error == "UnicodeDecodeError: bad byte"
    assert e.duration_ms == 12


def test_progress_event_updates_phase() -> None:
    """detector.progress updates the in-flight detector's phase."""
    trace = DetectorTrace(trace_id="t4", total=1)
    listener = DetectorTraceListener(trace)
    listener.on_event(Event(DETECTOR_STARTED, {
        "trace_id": "t4", "detector": "image_forensics",
        "phase": "scanning figure panels",
    }))
    listener.on_event(Event(DETECTOR_PROGRESS, {
        "trace_id": "t4", "detector": "image_forensics",
        "phase": "computing noise maps",
    }))
    e = trace.records[0]
    assert e.phase == "computing noise maps"
    assert e.status == DETECTOR_STARTED  # still running


# ---------- 2. heuristic + plugin respect ----------

def test_should_skip_plugin_is_no_op() -> None:
    """Plugin (is_builtin=False) detectors are not pre-skipped."""
    # A doc with NO references -- the heuristic would skip
    # ``citation_network`` if it were built-in. But we pass
    # is_builtin=False, so the skip is suppressed.
    doc = _doc(text_blocks=["hello world"], tables=[], images=[])
    skip, reason = should_skip_detector(
        "citation_network", doc, is_builtin=False,
    )
    assert skip is False
    assert reason == ""


def test_should_skip_builtin_image_dup_on_no_images() -> None:
    """Built-in image_dup is skipped when no images extracted."""
    doc = _doc(text_blocks=["some text"], tables=[], images=[])
    skip, reason = should_skip_detector(
        "image_dup", doc, is_builtin=True,
    )
    assert skip is True
    assert "no raster images" in reason.lower()


def test_should_skip_builtin_image_dup_with_images() -> None:
    """Built-in image_dup is NOT skipped when images exist."""
    doc = _doc(text_blocks=["text"], tables=[], images=[object()])
    skip, reason = should_skip_detector(
        "image_dup", doc, is_builtin=True,
    )
    assert skip is False


def test_should_skip_builtin_text_patterns_on_no_text() -> None:
    """Built-in text_patterns skipped when no body text."""
    doc = _doc(text_blocks=[], tables=[], images=[])
    skip, reason = should_skip_detector(
        "text_patterns", doc, is_builtin=True,
    )
    assert skip is True
    assert "no body text" in reason.lower()


# ---------- 3. regression: no deadlock in to_summary ----------

def test_to_summary_does_not_deadlock() -> None:
    """Regression test: ``to_summary`` must not re-acquire its
    own lock. Previously this deadlocked because
    ``findings_total()`` was called inside the locked block."""
    trace = DetectorTrace(trace_id="dl", total=2)
    trace.record_started("metadata")
    trace.record_done("metadata", 10, 5)
    trace.record_started("image_dup")
    trace.record_done("image_dup", 20, 0)
    # This MUST return without hanging. Use a short timeout by
    # running in the same thread; the test will hang forever
    # if the lock is broken.
    summary = trace.to_summary()
    assert summary["total"] == 2
    assert summary["completed"] == 2
    assert summary["findings_total"] == 5
    assert len(summary["detectors"]) == 2


def test_to_summary_counts_skipped_and_error() -> None:
    """Counts in to_summary reflect skipped / error correctly."""
    trace = DetectorTrace(trace_id="c", total=3)
    trace.record_started("a")
    trace.record_done("a", 10, 1)
    trace.record_skipped("b", "no images")
    trace.record_error("c", "boom", 5)
    s = trace.to_summary()
    assert s["completed"] == 1
    assert s["skipped"] == 1
    assert s["error"] == 1
    assert s["running"] == 0
    assert s["findings_total"] == 1


# ---------- 4. listener bridges ----------

def test_listener_ignores_non_detector_events() -> None:
    """Non-detector events (e.g. job.started) do not crash the
    listener when they reach it."""
    trace = DetectorTrace(trace_id="x", total=1)
    listener = DetectorTraceListener(trace)
    # Should not raise and should not add a record.
    listener.on_event(Event("job.started", {"trace_id": "x"}))
    listener.on_event(Event("job.completed", {"trace_id": "x"}))
    listener.on_event(Event("job.failed", {"trace_id": "x"}))
    assert len(trace.records) == 0


def test_listener_done_overwrites_resumed_step() -> None:
    """A duplicate done event overwrites the previous record
    (idempotent for resumed checkpoints)."""
    trace = DetectorTrace(trace_id="r", total=1)
    listener = DetectorTraceListener(trace)
    listener.on_event(Event(DETECTOR_STARTED, {
        "trace_id": "r", "detector": "metadata",
    }))
    listener.on_event(Event(DETECTOR_DONE, {
        "trace_id": "r", "detector": "metadata",
        "duration_ms": 10, "findings_count": 0,
    }))
    listener.on_event(Event(DETECTOR_DONE, {
        "trace_id": "r", "detector": "metadata",
        "duration_ms": 25, "findings_count": 2,
    }))
    # The trace still has exactly one record (by detector name);
    # the second done event overwrites the same record.
    e = trace._by_detector["metadata"]
    assert e.duration_ms == 25
    assert e.finding_count == 2
    # And the records list contains only one entry.
    assert len(trace.records) == 1


# ---------- 5. counts / queries ----------

def test_running_query_returns_in_flight() -> None:
    """``running()`` returns the most recent started entry."""
    trace = DetectorTrace(trace_id="r", total=3)
    trace.record_started("a")
    trace.record_done("a", 10, 1)
    trace.record_started("b")
    # 'b' is still in flight
    running = trace.running()
    assert running is not None
    assert running.detector == "b"


def test_findings_total_sums_done_only() -> None:
    """``findings_total`` sums finding_count across all records
    (including started/skipped/error with 0)."""
    trace = DetectorTrace(trace_id="f", total=3)
    trace.record_started("a")
    trace.record_done("a", 10, 5)
    trace.record_started("b")
    trace.record_done("b", 10, 3)
    trace.record_skipped("c", "no data")
    assert trace.findings_total() == 8


def test_done_returns_true_after_all_finish() -> None:
    """``done()`` returns True when no detector is still running."""
    trace = DetectorTrace(trace_id="d", total=1)
    assert trace.done() is False
    trace.record_started("a")
    assert trace.done() is False
    trace.record_done("a", 10, 1)
    assert trace.done() is True
    # Adding more records (a new run) is still fine.
    trace.record_started("b")
    assert trace.done() is False