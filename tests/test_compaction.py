"""Tests for the chat-log compactor (Step P1-C).

Pre-P1-C, ``data/chats/<sid>/messages.jsonl`` and
``tool_calls.jsonl`` grow forever. P1-C layers a
manual compaction: the live file is renamed to
``<name>.<YYYY-MM-DD>.jsonl.gz`` and gzipped, a
fresh empty live file is created, and the cycle
restarts on the next run.

Guarantees:

  1. A non-empty live file gets gzipped to
     ``<name>.<date>.jsonl.gz`` and the live file
     is truncated.
  2. An empty live file is not gzipped (no
     point in compressing an empty stream).
  3. The date stamp is the live file's mtime,
     not "now", so back-dated data is archived
     under the day it was actually written.
  4. Two rotations on the same day produce
     ``<name>.<date>.00.jsonl.gz`` and
     ``<name>.<date>.01.jsonl.gz`` — no overwrite.
  5. ``iter_archives`` returns archives
     newest-first by mtime.
  6. ``compact_all_chat_sessions`` walks the chat
     root and processes every session.
  7. ``main()`` returns 0 even if a per-session
     failure happens (best-effort cleanup).
"""
from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from manusift.compaction import (
    chat_sessions_root,
    compact_all_chat_sessions,
    compact_chat_session,
    iter_archives,
)


# ---------- helpers ----------

def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


# ---------- 1. happy path: rotate one file ----------

def test_compact_rotates_non_empty_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session with a non-empty ``messages.jsonl``
    gets gzipped. The live file is truncated."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid1"
    _write_jsonl(
        session / "messages.jsonl",
        ['{"role":"user","content":"hello"}'],
    )
    rotated = compact_chat_session(session)
    assert rotated == 1
    # Live file is empty (touched back into existence).
    assert (session / "messages.jsonl").exists()
    assert (session / "messages.jsonl").stat().st_size == 0
    # One archive exists.
    archives = list(session.glob("messages.*.jsonl.gz"))
    assert len(archives) == 1
    # The archive is gzipped and contains the
    # original line.
    with gzip.open(archives[0], "rt", encoding="utf-8") as f:
        contents = f.read()
    assert "hello" in contents


# ---------- 2. empty live file is skipped ----------

def test_compact_skips_empty_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty live file is left alone (no point
    in compressing an empty stream into a 22-byte
    gzip header)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid2"
    session.mkdir(parents=True)
    (session / "messages.jsonl").touch()  # exists but empty
    rotated = compact_chat_session(session)
    assert rotated == 0
    assert list(session.glob("*.jsonl.gz")) == []


def test_compact_skips_missing_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session with neither file present is a
    no-op. A future 'create session on first chat'
    path could create a session dir without either
    file, and the compactor must not crash."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "empty"
    session.mkdir(parents=True)
    rotated = compact_chat_session(session)
    assert rotated == 0


# ---------- 3. date stamp comes from mtime ----------

def test_compact_uses_live_mtime_not_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a live file's mtime is 30 days old, the
    archive is named with the date from 30 days
    ago — not today. This is the guarantee an
    operator relies on: 'this is the data from that
    day'."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid3"
    _write_jsonl(
        session / "messages.jsonl",
        ['{"role":"user","content":"old"}'],
    )
    # Backdate the mtime to 30 days ago.
    old = time.time() - 30 * 86400
    os.utime(session / "messages.jsonl", (old, old))
    compact_chat_session(session)
    archives = list(session.glob("messages.*.jsonl.gz"))
    assert len(archives) == 1
    expected = datetime.fromtimestamp(old).strftime("%Y-%m-%d")
    assert expected in archives[0].name


# ---------- 4. two rotations on same day get sequence numbers ----------

def test_compact_same_day_runs_get_sequence_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If we compact twice on the same day, the
    second call must not overwrite the first
    archive; it must produce ``.00`` and ``.01``
    variants."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid4"
    # First cycle.
    _write_jsonl(
        session / "messages.jsonl",
        ['{"role":"user","content":"a"}'],
    )
    first_write_mtime = (session / "messages.jsonl").stat().st_mtime
    compact_chat_session(session)
    # Second cycle on the same day: rewrite and
    # set mtime to match the first archive so the
    # date stamp collides. (Without this, the
    # second write defaults to ``now`` and the
    # compactor would naturally create a
    # different-date archive — the same-day branch
    # we are testing here would never run.)
    _write_jsonl(
        session / "messages.jsonl",
        ['{"role":"user","content":"b"}'],
    )
    first_archive = next(session.glob("messages.*.jsonl.gz"))
    # Use the FIRST WRITE'S mtime (we set it
    # explicitly above, not the archive's mtime
    # which is the post-compress time).
    same = first_write_mtime
    os.utime(session / "messages.jsonl", (same, same))
    compact_chat_session(session)
    date_part = first_archive.name.split(".")[1]
    archives = sorted(session.glob("messages.*.jsonl.gz"))
    assert len(archives) == 2
    # Names: messages.<date>.jsonl.gz and
    #        messages.<date>.00.jsonl.gz.
    assert any(date_part in a.name and ".01." in a.name for a in archives)
    # The second archive contains the new content.
    seq_archive = [a for a in archives if ".01." in a.name][0]
    with gzip.open(seq_archive, "rt", encoding="utf-8") as f:
        assert "b" in f.read()


# ---------- 5. iter_archives yields newest-first ----------

def test_iter_archives_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A future search endpoint can iterate
    archives in mtime order. We just confirm the
    helper respects the contract."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    session = tmp_path / "chats" / "sid5"
    # Two archives on different days.
    _write_jsonl(session / "messages.jsonl", ["a"])
    compact_chat_session(session)
    time.sleep(1.1)  # ensure different mtime
    _write_jsonl(session / "messages.jsonl", ["b"])
    compact_chat_session(session)
    archives = list(iter_archives(session))
    assert len(archives) == 2
    # Newer first.
    mtimes = [a.stat().st_mtime for a in archives]
    assert mtimes == sorted(mtimes, reverse=True)


# ---------- 6. compact_all_chat_sessions walks root ----------

def test_compact_all_processes_every_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``compact_all_chat_sessions`` walks the chat
    root and processes every session. Sessions with
    only the live file each get rotated."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    chats = tmp_path / "chats"
    for sid in ("alice", "bob", "carol"):
        _write_jsonl(
            chats / sid / "messages.jsonl",
            [f'{{"role":"user","content":"{sid}"}}'],
        )
        _write_jsonl(
            chats / sid / "tool_calls.jsonl",
            [f'{{"tool":"x","input":{{}}}}'],
        )
    sessions, files = compact_all_chat_sessions(root=chats)
    assert sessions == 3
    # Each session rotates 2 files (messages + tools).
    assert files == 6
    # Each session has both archives.
    for sid in ("alice", "bob", "carol"):
        names = sorted(
            p.name for p in (chats / sid).glob("*.jsonl.gz")
        )
        assert len(names) == 2


def test_compact_all_handles_missing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the chat root does not exist (fresh
    install, never used chat), the compactor is a
    no-op returning (0, 0)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    sessions, files = compact_all_chat_sessions(
        root=tmp_path / "nope"
    )
    assert (sessions, files) == (0, 0)


# ---------- 7. main() exit code ----------

def test_main_returns_zero(capsys: pytest.CaptureFixture) -> None:
    """``main()`` is the console-script entry point.
    It must return 0 even if individual sessions
    fail (we do not want cron to alert on a single
    bad jsonl)."""
    from manusift.compaction import main
    # The default chat root may or may not exist;
    # main() should still return 0.
    assert main() == 0
