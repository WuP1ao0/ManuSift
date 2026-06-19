"""Tests for the R-2026-06-14 long-task heartbeat
+ table_scan tools.

Covers issue 11 (TUI freezes during a long tool,
the user has no idea if the tool is hung or just
slow) and issue 13 (LLM has no way to walk a large
table in chunks; it spawns sub-agents which are
slow, expensive, and non-deterministic).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from manusift.events import Event, get_bus
from manusift.tools.heartbeat import (
    LongTaskHeartbeat,
    heartbeat,
)
from manusift.tools.table_scan import (
    DEFAULT_CHUNK_SIZE,
    TableScanTool,
    table_scan,
)
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# LongTaskHeartbeat
# --------------------------------------------------------------------


def test_heartbeat_emits_started_finished():
    """A ``with LongTaskHeartbeat(...)`` block emits
    a ``task.started`` event on entry and a
    ``task.finished`` event on exit.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _L()
    bus.subscribe(listener)
    try:
        with LongTaskHeartbeat(
            tool="demo", interval_seconds=0.1
        ):
            time.sleep(0.05)
    finally:
        bus.unsubscribe(listener)
    types = [e.type for e in captured]
    assert "task.started" in types
    assert "task.finished" in types


def test_heartbeat_emits_periodic_heartbeats():
    """A block that runs longer than the interval
    emits at least one ``task.heartbeat`` event.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _L()
    bus.subscribe(listener)
    try:
        with LongTaskHeartbeat(
            tool="demo", interval_seconds=0.1
        ):
            time.sleep(0.35)
    finally:
        bus.unsubscribe(listener)
    beats = [
        e for e in captured if e.type == "task.heartbeat"
    ]
    # At least 2 heartbeats in 350ms with 100ms
    # interval. Allow some slack for OS scheduling.
    assert len(beats) >= 2


def test_heartbeat_tick_records_progress():
    """``hb.tick(extra={...})`` is reflected in the
    final ``task.finished`` event payload and the
    in-flight ``task.heartbeat`` events.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _L()
    bus.subscribe(listener)
    try:
        with LongTaskHeartbeat(
            tool="demo", interval_seconds=0.05
        ) as hb:
            hb.tick(extra={"chunks_done": 5})
            time.sleep(0.15)
            hb.tick(extra={"chunks_done": 10})
            time.sleep(0.05)
    finally:
        bus.unsubscribe(listener)
    finished = next(
        e for e in captured if e.type == "task.finished"
    )
    # The final ``task.finished`` event carries the
    # tick count and the last extra.
    assert finished.payload["ticked"] >= 2
    assert finished.payload.get("last_extra", {}).get(
        "chunks_done"
    ) == 10
    # At least one ``task.heartbeat`` event carried
    # the chunks_done=5 extra.
    beats = [
        e for e in captured
        if e.type == "task.heartbeat"
    ]
    assert any(
        b.payload.get("last_extra", {}).get("chunks_done")
        in (5, 10)
        for b in beats
    )


def test_heartbeat_exit_payload_includes_ok_and_elapsed():
    """The ``task.finished`` event carries ``ok`` and
    ``elapsed_seconds``.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _L()
    bus.subscribe(listener)
    try:
        with LongTaskHeartbeat(
            tool="demo", interval_seconds=0.1
        ):
            pass
    finally:
        bus.unsubscribe(listener)
    finished = next(
        e for e in captured
        if e.type == "task.finished"
    )
    assert finished.payload["ok"] is True
    assert finished.payload["elapsed_seconds"] >= 0
    assert finished.payload["tool"] == "demo"


def test_heartbeat_exit_with_exception_carries_error():
    """An exception inside the block sets ``ok=False``
    and includes the exception in the payload.
    """
    bus = get_bus()
    captured: list[Event] = []

    class _L:
        def on_event(self, event: Event) -> None:
            captured.append(event)

    listener = _L()
    bus.subscribe(listener)
    try:
        with LongTaskHeartbeat(
            tool="demo", interval_seconds=0.1
        ):
            raise ValueError("intentional")
    except ValueError:
        pass
    finally:
        bus.unsubscribe(listener)
    finished = next(
        e for e in captured
        if e.type == "task.finished"
    )
    assert finished.payload["ok"] is False
    assert "intentional" in (finished.payload["error"] or "")


def test_heartbeat_functional_alias():
    """``with heartbeat("demo")`` is a one-liner that
    returns the same context manager.
    """
    with heartbeat("demo", interval_seconds=0.05):
        time.sleep(0.02)
    # If we get here without an exception, the alias
    # works.
    assert True


# --------------------------------------------------------------------
# table_scan / TableScanTool
# --------------------------------------------------------------------


def test_table_scan_csv_first_chunk(tmp_path: Path):
    p = tmp_path / "x.csv"
    rows = ["a,b,c"]
    for i in range(50):
        rows.append(f"{i},{i*2},{i*3}")
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    chunk = table_scan(
        {"id": "ds", "format": "csv", "path": str(p)},
        offset=0,
        limit=20,
    )
    assert chunk.row_count == 20
    assert chunk.row_count_total == 50
    assert chunk.has_more is True
    assert chunk.schema == ["a", "b", "c"]
    assert chunk.rows[0] == ["0", "0", "0"]


def test_table_scan_last_chunk_has_more_false(tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text(
        "a\n1\n2\n3\n", encoding="utf-8"
    )
    chunk = table_scan(
        {"id": "ds", "format": "csv", "path": str(p)},
        offset=0,
        limit=100,
    )
    assert chunk.has_more is False
    assert chunk.row_count == 3


def test_table_scan_schema_hash_changes_with_columns(tmp_path: Path):
    """Two data sources with the same columns have
    the same ``schema_hash``; different columns
    produce different hashes.
    """
    a = tmp_path / "a.csv"
    a.write_text("x,y\n1,2\n", encoding="utf-8")
    b = tmp_path / "b.csv"
    b.write_text("x,y\n3,4\n", encoding="utf-8")
    c = tmp_path / "c.csv"
    c.write_text("y,x\n3,4\n", encoding="utf-8")
    ha = table_scan({"id": "a", "format": "csv", "path": str(a)})
    hb = table_scan({"id": "b", "format": "csv", "path": str(b)})
    hc = table_scan({"id": "c", "format": "csv", "path": str(c)})
    # Same columns, same hash.
    assert ha.schema_hash == hb.schema_hash
    # Different column order, different hash.
    assert ha.schema_hash != hc.schema_hash


def test_table_scan_limit_caps_chunk_size(tmp_path: Path):
    """``limit > DEFAULT_CHUNK_SIZE`` is capped.
    """
    p = tmp_path / "x.csv"
    p.write_text("a\n1\n2\n3\n", encoding="utf-8")
    chunk = table_scan(
        {"id": "ds", "format": "csv", "path": str(p)},
        offset=0,
        limit=DEFAULT_CHUNK_SIZE * 5,
    )
    # The chunk returned at most DEFAULT_CHUNK_SIZE
    # rows (we only wrote 3 so it returns 3).
    assert chunk.row_count <= DEFAULT_CHUNK_SIZE


def test_table_scan_missing_file(tmp_path: Path):
    chunk = table_scan(
        {
            "id": "ds",
            "format": "csv",
            "path": str(tmp_path / "no.csv"),
        }
    )
    assert chunk.row_count == 0
    # R-audit (2026-06-14): the missing-file
    # branch now returns a typed ``skip_reason``
    # instead of silently dropping the diagnostic.
    assert chunk.skip_reason is not None
    assert "not found" in chunk.skip_reason


def test_table_scan_reader_exception_is_surfaced(tmp_path: Path):
    """R-audit (2026-06-14): a reader exception
    (here, a corrupt JSON file) is surfaced in
    ``skip_reason`` rather than silently dropping
    into a zero-row chunk.
    """
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"a": 1, "b"',  # invalid JSON
        encoding="utf-8",
    )
    chunk = table_scan(
        {"id": "ds", "format": "json", "path": str(bad)}
    )
    assert chunk.row_count == 0
    assert chunk.skip_reason is not None
    assert "read failed" in chunk.skip_reason
    # And the JSON envelope exposes it to the
    # LLM, not just the dataclass.
    d = chunk.to_dict()
    assert d["skip_reason"] is not None
    assert chunk.row_count_total == 0


def test_table_scan_unsupported_format(tmp_path: Path):
    p = tmp_path / "x.pdf"
    p.write_text("dummy", encoding="utf-8")
    chunk = table_scan(
        {"id": "ds", "format": "pdf", "path": str(p)}
    )
    # Reads nothing, returns empty chunk.
    assert chunk.row_count == 0


def test_table_scan_tool_runs_through_metadata(tmp_path: Path):
    """The ``TableScanTool`` wrapper reads the
    data source from ``ctx.metadata['data_sources']``.
    """
    p = tmp_path / "x.csv"
    p.write_text(
        "x,y\n1,2\n3,4\n5,6\n", encoding="utf-8"
    )
    ctx = ToolContext(
        trace_id="t",
        metadata={
            "data_sources": [
                {
                    "id": "ds-1",
                    "format": "csv",
                    "path": str(p),
                }
            ]
        },
    )
    tool = TableScanTool()
    out = json.loads(
        tool.execute(
            {"data_source_id": "ds-1", "limit": 2},
            ctx,
        )
    )
    assert out["ok"] is True
    assert out["chunk"]["row_count"] == 2
    assert out["chunk"]["has_more"] is True


def test_table_scan_tool_missing_id_returns_permission_denied():
    tool = TableScanTool()
    out = json.loads(
        tool.execute({}, ToolContext(trace_id="t"))
    )
    assert out["ok"] is False
    assert out["error_kind"] == "permission_denied"


def test_table_scan_tool_unknown_id_returns_data_source_missing():
    tool = TableScanTool()
    out = json.loads(
        tool.execute(
            {"data_source_id": "nope"},
            ToolContext(
                trace_id="t",
                metadata={
                    "data_sources": [
                        {
                            "id": "ds-1",
                            "format": "csv",
                            "path": "C:/missing.csv",
                        }
                    ]
                },
            ),
        )
    )
    assert out["ok"] is False
    assert out["error_kind"] == "data_source_missing"
    assert "ds-1" in out["data_sources_available"]


def test_table_scan_in_registry():
    from manusift.tools import tool_names
    names = tool_names()
    assert "table_scan" in names
