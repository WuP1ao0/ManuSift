"""Tests for the tool-call stats endpoint (Step P1-D).

The L6 audit log already writes one JSONL line per
``tool.execute`` (with the new P1-D ``ok`` and
``duration_ms`` fields). P1-D aggregates those
records into a per-tool summary that the
``GET /api/tools/stats`` endpoint serves.

Guarantees:

  1. ``ToolStats`` is a dataclass with the five
     documented fields.
  2. ``aggregate_tool_stats`` returns an empty
     list when no audit data exists (fresh
     install, never used chat).
  3. Given a session with two tool calls of
     different latency, the aggregated row has
     correct calls / errors / avg / p50 / p95.
  4. Malformed JSONL lines are silently skipped;
     they do not raise.
  5. Old L6 audit records (pre-P1-D, no ``ok``
     field) still count: the aggregator falls
     back to ``not error``.
  6. The HTTP endpoint returns the same shape as
     ``stats_to_json(aggregate_tool_stats())``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.tools.stats import (
    ToolStats,
    aggregate_tool_stats,
    chat_sessions_root,
    stats_to_json,
)
from manusift.web import app as web_mod


def _write_audit_line(
    session_dir: Path, name: str, record: dict
) -> None:
    """Append a single audit record to a session's
    ``tool_calls.jsonl``. The line shape matches
    what ``AgentLoop._emit_audit`` writes today."""
    session_dir.mkdir(parents=True, exist_ok=True)
    target = session_dir / "tool_calls.jsonl"
    payload = {
        "ts": 1780990000.0,
        "tool": name,
        "input": {},
        "output_preview": "x",
        "error": None,
        "ok": True,
        "duration_ms": 10,
    }
    payload.update(record)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


# ---------- 1. dataclass surface ----------

def test_tool_stats_field_set() -> None:
    """The dataclass has exactly the five fields the
    dashboard renders."""
    s = ToolStats(
        name="x", calls=0, errors=0,
        avg_ms=0, p50_ms=0, p95_ms=0,
    )
    d = s.__dict__
    assert set(d.keys()) == {
        "name", "calls", "errors",
        "avg_ms", "p50_ms", "p95_ms",
    }


# ---------- 2. empty case ----------

def test_aggregate_empty_chat_root(tmp_path: Path) -> None:
    """No chat root, no sessions, no rows."""
    rows = aggregate_tool_stats(root=tmp_path / "nope")
    assert rows == []


def test_stats_to_json_empty() -> None:
    """``stats_to_json`` of an empty list is the
    documented empty shape."""
    out = stats_to_json([])
    assert out == {
        "tools": [],
        "total_tools": 0,
        "total_calls": 0,
        "total_errors": 0,
    }


# ---------- 3. happy path ----------

def test_aggregate_one_session_two_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session with two tools, each called twice
    (one success + one error) yields two
    ``ToolStats`` rows. The most-called tool is
    first.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    chats = tmp_path / "chats"
    session = chats / "sid1"
    # Tool A: 2 calls (1 ok + 1 err), durations 10, 20
    _write_audit_line(session, "metadata", {
        "ok": True, "duration_ms": 10
    })
    _write_audit_line(session, "metadata", {
        "ok": False, "error": "boom", "duration_ms": 20
    })
    # Tool B: 1 ok call, 100 ms
    _write_audit_line(session, "image_dup", {
        "ok": True, "duration_ms": 100
    })
    rows = aggregate_tool_stats(root=chats)
    # Two rows.
    assert len(rows) == 2
    # Sorted by call count desc, then name asc.
    assert rows[0].name == "metadata"
    assert rows[1].name == "image_dup"
    # metadata: 2 calls, 1 error, avg = 15.
    assert rows[0].calls == 2
    assert rows[0].errors == 1
    assert rows[0].avg_ms == 15
    # image_dup: 1 call, 0 errors, 100 ms.
    assert rows[1].calls == 1
    assert rows[1].errors == 0
    assert rows[1].avg_ms == 100
    # The percentiles for a single sample are
    # that sample.
    assert rows[1].p50_ms == 100
    assert rows[1].p95_ms == 100


def test_aggregate_p50_and_p95_for_many_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a session with 10 calls of
    duration 1, 2, ..., 10, the p50 is 6 (the
    5th of 10 sorted is index 5 = 6) and the p95
    is the 9th of 10 sorted = 9 (we use
    ``int(len*0.95)-1`` = 8 -> 9)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid"
    for d in range(1, 11):
        _write_audit_line(session, "x", {
            "ok": True, "duration_ms": d
        })
    rows = aggregate_tool_stats(root=tmp_path / "chats")
    assert len(rows) == 1
    r = rows[0]
    # Average 1..10 = 55 / 10 = 5.
    assert r.avg_ms == 5
    # p50: ds[len//2] = ds[5] = 6.
    assert r.p50_ms == 6
    # p95: ds[max(0, int(10*0.95)-1)] = ds[8] = 9.
    assert r.p95_ms == 9


# ---------- 4. malformed lines are skipped ----------

def test_aggregate_skips_malformed_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt JSONL line must not raise. The
    aggregator returns the well-formed rows only.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid"
    session.mkdir(parents=True)
    target = session / "tool_calls.jsonl"
    # Mix a valid and a broken line.
    target.write_text(
        json.dumps({
            "tool": "x", "ok": True, "duration_ms": 5
        }) + "\n"
        + "{this is not json}\n"
        + json.dumps({
            "tool": "x", "ok": True, "duration_ms": 7
        }) + "\n",
        encoding="utf-8",
    )
    rows = aggregate_tool_stats(root=tmp_path / "chats")
    assert len(rows) == 1
    assert rows[0].calls == 2
    # Average of 5 and 7 = 6.
    assert rows[0].avg_ms == 6


# ---------- 5. old L6 records (no ``ok`` field) ----------

def test_aggregate_handles_legacy_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Records written by the pre-P1-D version of
    ``AgentLoop._emit_audit`` have no ``ok`` field.
    The aggregator falls back to ``not error`` so
    legacy sessions still contribute to the
    dashboard."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid"
    session.mkdir(parents=True)
    target = session / "tool_calls.jsonl"
    target.write_text(
        # No "ok" key, "error": None -> success.
        json.dumps({
            "tool": "legacy", "error": None,
            "duration_ms": 5,
        }) + "\n"
        # No "ok" key, "error" is a string -> failure.
        + json.dumps({
            "tool": "legacy", "error": "kaboom",
            "duration_ms": 8,
        }) + "\n",
        encoding="utf-8",
    )
    rows = aggregate_tool_stats(root=tmp_path / "chats")
    assert len(rows) == 1
    r = rows[0]
    assert r.calls == 2
    # The error one counts as a failure.
    assert r.errors == 1


# ---------- 6. endpoint ----------

def test_endpoint_returns_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The HTTP endpoint returns the same shape as
    ``stats_to_json(aggregate_tool_stats())``. We
    only seed one session so the test is
    deterministic."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    chats = tmp_path / "chats"
    _write_audit_line(chats / "sid", "metadata", {
        "ok": True, "duration_ms": 5
    })
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=workspace)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/tools/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total_tools"] == 1
    assert body["total_calls"] == 1
    assert body["total_errors"] == 0
    assert body["tools"][0]["name"] == "metadata"


def test_endpoint_empty_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No audit data: the endpoint returns the
    empty aggregate shape, not 404."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=workspace)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/tools/stats")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "tools": [],
        "total_tools": 0,
        "total_calls": 0,
        "total_errors": 0,
    }
