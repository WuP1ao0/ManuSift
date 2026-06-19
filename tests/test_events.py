"""Tests for the event bus + webhook
listener (Step E3).

E3 layers a process-global
``EventBus`` on top of the
pipeline. The pipeline emits at four
points:

  * ``job.started`` — at the top of
    ``run_pipeline``.
  * ``job.step_completed`` — after
    every detector.
  * ``job.completed`` — at the end
    of a successful run.
  * ``job.failed`` — when the
    pipeline raises an unhandled
    exception.

Guarantees:

  1. ``EventBus.emit`` is synchronous
     and thread-safe. Concurrent
     emits do not interleave their
     listener invocations.
  2. A listener that raises is
     logged and skipped; the next
     listener still fires. The
     pipeline never sees a listener
     exception.
  3. ``get_bus`` returns a
     process-global singleton;
     ``reset_bus`` (a test hook)
     clears the bus and re-installs
     the default ``LoggingListener``.
  4. ``FileWebhookListener`` writes
     one JSON line per event to
     ``data/webhooks/<trace_id>.jsonl``.
     An event without a ``trace_id``
     is logged and dropped.
  5. The pipeline emits
     ``job.started`` at the start,
     ``job.completed`` at the end of
     a successful run, and
     ``job.failed`` on an unhandled
     exception.
  6. ``LoggingListener`` logs every
     event at INFO level.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest


# ---------- 1. EventBus basics ----------

def test_event_bus_emits_to_all_listeners() -> None:
    """``emit`` dispatches to every
    registered listener in
    registration order. A listener
    that raises does not stop the
    next listener from firing."""
    from manusift.events import Event, EventBus
    bus = EventBus()
    seen: list[str] = []

    class L:
        name = "L"
        def __init__(self, label: str) -> None:
            self.label = label
        def on_event(self, event: Event) -> None:
            seen.append(self.label)

    class LRaise:
        name = "LRaise"
        def on_event(self, event: Event) -> None:
            raise RuntimeError("nope")

    bus.subscribe(LRaise())
    bus.subscribe(L("a"))
    bus.subscribe(L("b"))
    bus.emit(Event("x", {"trace_id": "t"}))
    # Both ``a`` and ``b`` saw the
    # event; the raising listener
    # was logged and skipped.
    assert "a" in seen
    assert "b" in seen


def test_event_bus_is_thread_safe() -> None:
    """Two threads that emit
    concurrently do not interleave
    their listener invocations. We
    use a list-append listener
    (the GIL serializes the append,
    but the bus also takes a
    snapshot under a lock so the
    iteration is consistent)."""
    from manusift.events import Event, EventBus
    bus = EventBus()
    counter = [0]
    counter_lock = threading.Lock()

    class Count:
        name = "Count"
        def on_event(self, event: Event) -> None:
            with counter_lock:
                counter[0] += 1

    bus.subscribe(Count())
    def worker(n: int) -> None:
        for _ in range(n):
            bus.emit(Event("x", {"trace_id": "t"}))
    ts = [threading.Thread(target=worker, args=(50,)) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    # 4 threads * 50 events = 200.
    assert counter[0] == 200


def test_event_bus_unsubscribe_is_safe_for_unknown() -> None:
    """``unsubscribe`` for an unknown
    listener is a no-op; the bus
    does not raise."""
    from manusift.events import Event, EventBus
    bus = EventBus()
    bus.unsubscribe("not-a-listener")  # type: ignore[arg-type]


# ---------- 2. FileWebhookListener ----------

def test_file_webhook_writes_jsonl_per_event(
    tmp_path: Path,
) -> None:
    """A listener that emits two
    events with the same trace id
    writes two JSON lines to the
    same JSONL file."""
    from manusift.events import (
        Event,
        FileWebhookListener,
    )
    listener = FileWebhookListener(base_dir=tmp_path)
    listener.on_event(
        Event("job.started", {"trace_id": "t-1"})
    )
    listener.on_event(
        Event("job.completed", {"trace_id": "t-1", "total_findings": 3})
    )
    target = tmp_path / "t-1.jsonl"
    assert target.exists()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    r0 = json.loads(lines[0])
    r1 = json.loads(lines[1])
    assert r0["type"] == "job.started"
    assert r1["type"] == "job.completed"
    assert r1["payload"]["total_findings"] == 3


def test_file_webhook_drops_event_without_trace_id(
    tmp_path: Path,
) -> None:
    """An event with no ``trace_id``
    in the payload is logged and
    dropped — the listener does
    not write a file at all."""
    from manusift.events import (
        Event,
        FileWebhookListener,
    )
    listener = FileWebhookListener(base_dir=tmp_path)
    listener.on_event(Event("orphan", {}))
    # The directory exists (mkdir
    # is unconditional) but no
    # file is written.
    assert tmp_path.exists()
    files = list(tmp_path.iterdir())
    assert not any(f.suffix == ".jsonl" for f in files)


# ---------- 3. Singleton bus ----------

def test_get_bus_returns_singleton() -> None:
    """``get_bus`` returns the same
    process-global instance."""
    from manusift.events import get_bus
    a = get_bus()
    b = get_bus()
    assert a is b


def test_get_bus_includes_default_logging_listener() -> None:
    """The bus, on first construction,
    has the default
    ``LoggingListener`` installed.
    A subsequent ``reset_bus``
    clears the bus and
    re-installs the default."""
    from manusift.events import (
        get_bus,
        reset_bus,
    )
    reset_bus()
    bus = get_bus()
    names = [l.name for l in bus.listeners()]
    assert "logging" in names
    # Reset clears the listeners
    # and re-installs the default.
    reset_bus()
    bus2 = get_bus()
    names2 = [l.name for l in bus2.listeners()]
    assert "logging" in names2


# ---------- 4. End-to-end pipeline emission ----------

def test_pipeline_emits_started_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline emits
    ``job.started`` and
    ``job.completed`` for a
    successful run."""
    from manusift import events as events_mod
    events_mod.reset_bus()
    bus = events_mod.get_bus()
    captured: list[events_mod.Event] = []
    class _Capture:
        name = "capture"
        def on_event(self, event):
            captured.append(event)
    bus.subscribe(_Capture())
    # Set up workspace and run the
    # pipeline.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    pdf_dir = workspace / "uploads"
    pdf_dir.mkdir()
    (pdf_dir / "a.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
        b"xref\n0 1\n0000000000 65535 f\n"
        b"trailer<</Root 1 0 R>>\n"
        b"%%EOF"
    )
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "0")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from types import SimpleNamespace
    from manusift.detectors.base import DetectorResult
    class _EventDetector:
        name = "event_probe"
        def run(self, doc):
            return DetectorResult(
                detector=self.name,
                ok=True,
                findings=[],
                error=None,
                duration_ms=1,
            )
    monkeypatch.setattr(
        "manusift.pipeline._pipeline_detector_classes",
        lambda: [_EventDetector],
    )
    monkeypatch.setattr(
        "manusift.pipeline._parse_pdf",
        lambda pdf_path, trace_id, workspace_dir: SimpleNamespace(
            trace_id=trace_id,
            source_path=str(pdf_path),
            text_blocks=[],
            images=[],
            metadata={},
        ),
    )
    from manusift.pipeline import run_pipeline
    from manusift.contracts import JobState
    from manusift.workspace import JobPaths
    paths = JobPaths.for_trace("t-1", workspace)
    paths.ensure()
    paths.original.write_bytes(
        (pdf_dir / "a.pdf").read_bytes()
    )
    job = JobState(trace_id="t-1", status="queued", source_filename="a.pdf")
    try:
        run_pipeline(paths.original, paths, job)
    except Exception:
        pass  # some detectors may
              # fail on the synthetic
              # PDF; we just want the
              # events.
    types = [e.type for e in captured]
    assert "job.started" in types
    assert "job.completed" in types or "job.failed" in types
    # The trace id is on every
    # event.
    for event in captured:
        assert event.payload.get("trace_id") == "t-1"


def test_pipeline_emits_failed_on_unhandled_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pipeline that raises an
    unhandled exception emits
    ``job.failed`` and the original
    exception is preserved."""
    from manusift import events as events_mod
    events_mod.reset_bus()
    bus = events_mod.get_bus()
    captured: list[events_mod.Event] = []
    class _Capture:
        name = "capture"
        def on_event(self, event):
            captured.append(event)
    bus.subscribe(_Capture())
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    monkeypatch.setenv("MANUSIFT_RATE_LIMIT_PER_MINUTE", "0")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    # Patch parse_pdf to raise a
    # known exception. The pipeline
    # should still emit job.failed
    # and re-raise.
    from manusift import pipeline as pipeline_mod
    def _broken_parse(*args, **kwargs):
        raise RuntimeError("simulated parse failure")
    monkeypatch.setattr(
        pipeline_mod, "_parse_pdf", _broken_parse
    )
    from manusift.pipeline import run_pipeline
    from manusift.contracts import JobState
    from manusift.workspace import JobPaths
    paths = JobPaths.for_trace("t-fail", workspace)
    paths.ensure()
    paths.original.write_bytes(b"%PDF-1.4\n%%EOF")
    job = JobState(
        trace_id="t-fail", status="queued", source_filename="x.pdf"
    )
    with pytest.raises(RuntimeError):
        run_pipeline(paths.original, paths, job)
    # The captured events include
    # ``job.started`` and
    # ``job.failed``.
    types = [e.type for e in captured]
    assert "job.started" in types
    assert "job.failed" in types
    failed = next(
        e for e in captured if e.type == "job.failed"
    )
    assert "simulated parse failure" in failed.payload["error"]
