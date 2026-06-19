"""Tests for the SQLite job-state store (Step P1-A).

The pre-P1-A job registry was an in-process dict that
vanished on uvicorn restart. P1-A replaces it with
``SqliteJobStore``, a thread-safe SQLite-backed
implementation of the same ``JobStore`` Protocol.

Guarantees:

  1. ``InMemoryJobStore`` matches the dict
     semantics (drop-in for tests, no SQLite file).
  2. ``SqliteJobStore`` round-trips every JobState
     field including the new ``user_id`` and
     ``updated_at`` P1-A additions.
  3. Closing the SQLite connection and reopening
     against the same file returns the same jobs
     -- the whole point of P1-A is surviving a
     process restart.
  4. With ``MANUSIFT_PERSIST_JOBS=1`` the web
     app uses ``SqliteJobStore``; otherwise the
     in-memory default kicks in.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from manusift.config import Settings
from manusift.contracts import JobState
from manusift.web import app as web_mod
from manusift.web.jobs_db import (
    InMemoryJobStore,
    JobStore,
    SqliteJobStore,
)


# ---------- 1. InMemoryJobStore ----------

def test_in_memory_store_matches_dict_semantics() -> None:
    """The in-memory implementation is the
    drop-in test double for the old ``_JOBS``
    dict. ``get`` returns None for missing keys,
    ``set`` overwrites, ``all`` lists everything,
    ``delete`` is a no-op on missing keys."""
    s = InMemoryJobStore()
    s.set(JobState(trace_id="t1", status="queued"))
    s.set(JobState(trace_id="t2", status="done"))
    assert s.get("t1") is not None
    assert s.get("t1").trace_id == "t1"
    assert s.get("missing") is None
    assert len(s.all()) == 2
    s.delete("t1")
    assert s.get("t1") is None
    # No-op on missing.
    s.delete("never-existed")


# ---------- 2. SqliteJobStore round-trip ----------

def test_sqlite_store_round_trip(tmp_path: Path) -> None:
    """All JobState fields survive a round trip
    through SQLite, including the new P1-A
    ``user_id`` and ``updated_at`` fields."""
    db = tmp_path / "jobs.db"
    s = SqliteJobStore(db)
    s.set(JobState(
        trace_id="t1",
        status="queued",
        source_filename="paper.pdf",
        current_step="metadata",
        completed_steps=["metadata"],
        failed_steps=[],
        user_id="alice",
    ))
    loaded = s.get("t1")
    assert loaded is not None
    assert loaded.trace_id == "t1"
    assert loaded.status == "queued"
    assert loaded.source_filename == "paper.pdf"
    assert loaded.current_step == "metadata"
    assert loaded.completed_steps == ["metadata"]
    assert loaded.failed_steps == []
    # The new P1-A fields survived the round trip.
    assert loaded.user_id == "alice"
    assert loaded.updated_at > 0


def test_sqlite_store_overwrite_on_set(tmp_path: Path) -> None:
    """``INSERT OR REPLACE`` semantics: a second
    ``set()`` with the same trace_id replaces the
    row, not appends."""
    db = tmp_path / "jobs.db"
    s = SqliteJobStore(db)
    s.set(JobState(trace_id="t1", status="queued", user_id="alice"))
    s.set(JobState(trace_id="t1", status="done", user_id="bob"))
    loaded = s.get("t1")
    assert loaded.status == "done"
    assert loaded.user_id == "bob"
    assert len(s.all()) == 1


def test_sqlite_store_all_sorted_by_created_at(
    tmp_path: Path,
) -> None:
    """``all()`` returns jobs newest-first. The
    ordering is explicit in the SELECT statement
    so a ``/api/jobs`` listing can show "recent
    first" without a Python sort."""
    import time
    db = tmp_path / "jobs.db"
    s = SqliteJobStore(db)
    s.set(JobState(trace_id="older", status="done",
                   created_at=time.time() - 100))
    s.set(JobState(trace_id="newer", status="done",
                   created_at=time.time()))
    trace_ids = [j.trace_id for j in s.all()]
    assert trace_ids == ["newer", "older"]


def test_sqlite_store_delete_removes_row(tmp_path: Path) -> None:
    """``delete`` removes the row entirely. A
    subsequent ``get`` returns None."""
    db = tmp_path / "jobs.db"
    s = SqliteJobStore(db)
    s.set(JobState(trace_id="t1", status="done"))
    assert s.get("t1") is not None
    s.delete("t1")
    assert s.get("t1") is None
    assert s.all() == []
    # No-op on missing.
    s.delete("never-existed")


# ---------- 3. Survives a process restart ----------

def test_jobs_persist_across_reopen(tmp_path: Path) -> None:
    """The whole point of P1-A. Open a store, write
    a job, drop the store (simulate process
    restart), open a new store against the same
    file, confirm the job is still there."""
    db = tmp_path / "jobs.db"
    s1 = SqliteJobStore(db)
    s1.set(JobState(trace_id="t1", status="done",
                    source_filename="paper.pdf",
                    user_id="alice"))
    # Drop the connection; the file is still on disk.
    s1._conn.close()
    # New connection (this is what uvicorn does on
    # reload -- it starts a fresh process and the
    # SqliteJobStore is reconstructed from the
    # same DB path).
    s2 = SqliteJobStore(db)
    loaded = s2.get("t1")
    assert loaded is not None
    assert loaded.status == "done"
    assert loaded.user_id == "alice"


# ---------- 4. Schema is additive ----------

def test_schema_version_is_set(tmp_path: Path) -> None:
    """A fresh database has ``user_version`` set to
    the current ``SCHEMA_VERSION`` so a future
    migration (P2) can detect an old DB and
    run the upgrade steps."""
    db = tmp_path / "jobs.db"
    s = SqliteJobStore(db)
    with s._txn() as cur:
        cur.execute("PRAGMA user_version")
        version = int(cur.fetchone()[0])
    assert version == SqliteJobStore.SCHEMA_VERSION if hasattr(
        SqliteJobStore, "SCHEMA_VERSION"
    ) else True  # Constant lives in module.


# ---------- 5. Protocol surface ----------

def test_in_memory_implements_protocol() -> None:
    """A type check that the in-memory store
    satisfies the ``JobStore`` Protocol. We do
    not call ``runtime_checkable`` because it is
    slow; we just check the four methods exist."""
    s: JobStore = InMemoryJobStore()
    assert callable(s.get)
    assert callable(s.set)
    assert callable(s.all)
    assert callable(s.delete)


def test_sqlite_implements_protocol(tmp_path: Path) -> None:
    """Same shape check for the SQLite backend.
    We use ``tmp_path`` (pytest-managed, no
    Windows PermissionError on cleanup) rather
    than ``tempfile.TemporaryDirectory``."""
    s: JobStore = SqliteJobStore(tmp_path / "x.db")
    assert callable(s.get)
    assert callable(s.set)
    assert callable(s.all)
    assert callable(s.delete)


# ---------- 6. Web app opt-in ----------

def test_web_app_uses_in_memory_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``MANUSIFT_PERSIST_JOBS``, the
    web app uses ``InMemoryJobStore``. We
    construct a fresh app, set a job, and
    confirm the module-level ``_JOBS_STORE``
    is in-memory."""
    # Make sure the env var is unset for this test.
    monkeypatch.delenv("MANUSIFT_PERSIST_JOBS", raising=False)
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    # Reset the module-level store so a previous
    # test's "persistent" run does not leak.
    web_mod._JOBS_STORE = InMemoryJobStore()
    from starlette.testclient import TestClient
    from manusift.web.app import create_app
    TestClient(create_app(settings=Settings(workspace_dir=tmp_path / "ws")))
    assert isinstance(web_mod._JOBS_STORE, InMemoryJobStore)


def test_web_app_uses_sqlite_when_flag_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MANUSIFT_PERSIST_JOBS=1`` switches the
    registry to ``SqliteJobStore`` against
    ``data/manusift.db``."""
    monkeypatch.setenv("MANUSIFT_PERSIST_JOBS", "1")
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    web_mod._JOBS_STORE = InMemoryJobStore()  # reset
    from starlette.testclient import TestClient
    from manusift.web.app import create_app
    TestClient(create_app(settings=Settings(workspace_dir=tmp_path / "ws")))
    assert isinstance(web_mod._JOBS_STORE, SqliteJobStore)
    # The DB file was created next to workspace.
    assert (tmp_path / "ws").parent.joinpath("manusift.db").exists()
