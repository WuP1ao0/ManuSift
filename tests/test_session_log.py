"""Tests for the R-2026-06-14 P2.1 SessionLog
JSONL append-only sink.

The contract:

  * Each ``append(event, payload)`` writes
    one JSON line to the on-disk file.
  * The line includes the session id, the
    version stamp, the timestamp, the
    event type, and the payload.
  * Non-ASCII payloads (e.g. a Chinese
    tool name) are written as UTF-8
    without ``\\uXXXX`` escapes.
  * Multiple appends produce multiple
    lines, in order.
  * ``read_all()`` parses every line
    back to a dict; an empty file
    parses to an empty list.
  * The session id is stable for the
    lifetime of a ``SessionLog``
    instance and is auto-generated as
    a 12-char hex string when no
    session id is passed.
  * The on-disk file path is
    ``<workspace>/sessions/<sid>.jsonl``
    by default; passing ``path=``
    overrides this for tests.
  * ``reset()`` deletes the file (test
    hook).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from manusift.observability import (
    SESSION_LOG_VERSION,
    SessionLog,
)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return tmp_path


# --------------------------------------------------------------------
# Append + read
# --------------------------------------------------------------------


def test_append_creates_file(ws: Path):
    log = SessionLog(ws)
    log.append("tool.started", {"tool": "bash"})
    assert log.path.exists()


def test_append_writes_one_line_per_call(ws: Path):
    log = SessionLog(ws)
    log.append("a", {"x": 1})
    log.append("b", {"x": 2})
    log.append("c", {"x": 3})
    text = log.path.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l]
    assert len(lines) == 3


def test_append_line_includes_session_id(ws: Path):
    log = SessionLog(ws, session_id="abc123")
    log.append("e1", {})
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["session_id"] == "abc123"


def test_append_line_includes_version(ws: Path):
    log = SessionLog(ws)
    log.append("e1", {})
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["session_version"] == SESSION_LOG_VERSION


def test_append_line_includes_event(ws: Path):
    log = SessionLog(ws)
    log.append("tool.started", {"tool": "bash"})
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["event"] == "tool.started"


def test_append_line_includes_payload(ws: Path):
    log = SessionLog(ws)
    log.append("e1", {"k": "v", "n": 42})
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["payload"] == {"k": "v", "n": 42}


# --------------------------------------------------------------------
# UTF-8 / non-ASCII
# --------------------------------------------------------------------


def test_non_ascii_payload_written_as_utf8(ws: Path):
    log = SessionLog(ws)
    log.append("detector.run", {"name": "图像去重"})
    text = log.path.read_text(encoding="utf-8")
    # The Chinese characters appear
    # verbatim, not as \uXXXX escapes.
    assert "图像去重" in text
    # And parses back.
    rec = json.loads(text.splitlines()[0])
    assert rec["payload"]["name"] == "图像去重"


# --------------------------------------------------------------------
# Session id generation
# --------------------------------------------------------------------


def test_default_session_id_is_12_char_hex(ws: Path):
    log = SessionLog(ws)
    assert re.fullmatch(r"[0-9a-f]{12}", log.session_id)


def test_default_session_ids_are_unique(ws: Path):
    a = SessionLog(ws)
    b = SessionLog(ws)
    assert a.session_id != b.session_id


# --------------------------------------------------------------------
# On-disk path
# --------------------------------------------------------------------


def test_default_path_is_under_workspace_sessions(ws: Path):
    log = SessionLog(ws)
    assert log.path.parent == ws / "sessions"
    assert log.path.name == f"{log.session_id}.jsonl"


def test_explicit_path_overrides_default(ws: Path):
    custom = ws / "custom_dir" / "log.jsonl"
    log = SessionLog(ws, path=custom)
    log.append("e1", {})
    assert custom.exists()
    assert log.path == custom


# --------------------------------------------------------------------
# read_all
# --------------------------------------------------------------------


def test_read_all_parses_every_line(ws: Path):
    log = SessionLog(ws)
    log.append("a", {"n": 1})
    log.append("b", {"n": 2})
    records = log.read_all()
    assert len(records) == 2
    assert records[0]["event"] == "a"
    assert records[1]["event"] == "b"


def test_read_all_empty_when_no_file(ws: Path):
    log = SessionLog(ws)
    assert log.read_all() == []


def test_read_all_skips_garbled_lines(ws: Path):
    """A corrupt line in the middle of
    the file does not crash the
    reader; it is skipped.
    """
    log = SessionLog(ws)
    log.append("a", {})
    # Inject a garbage line.
    with log.path.open("a", encoding="utf-8") as f:
        f.write("this is not json\n")
    log.append("b", {})
    records = log.read_all()
    assert len(records) == 2
    assert records[0]["event"] == "a"
    assert records[1]["event"] == "b"


# --------------------------------------------------------------------
# reset test hook
# --------------------------------------------------------------------


def test_reset_deletes_file(ws: Path):
    log = SessionLog(ws)
    log.append("e1", {})
    assert log.path.exists()
    log.reset()
    assert not log.path.exists()


# --------------------------------------------------------------------
# timestamp
# --------------------------------------------------------------------


def test_append_uses_supplied_timestamp(ws: Path):
    log = SessionLog(ws)
    log.append("e1", {}, ts=12345.678)
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["ts"] == 12345.678


def test_append_auto_fills_timestamp(ws: Path):
    log = SessionLog(ws)
    t_before = time.time()
    log.append("e1", {})
    t_after = time.time()
    rec = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert t_before <= rec["ts"] <= t_after


# --------------------------------------------------------------------
# Multiple SessionLog instances sharing the same workspace
# --------------------------------------------------------------------


def test_two_sessions_write_to_separate_files(ws: Path):
    a = SessionLog(ws, session_id="sess-aaa")
    b = SessionLog(ws, session_id="sess-bbb")
    a.append("e1", {"which": "a"})
    b.append("e1", {"which": "b"})
    a_text = a.path.read_text(encoding="utf-8")
    b_text = b.path.read_text(encoding="utf-8")
    # ``a`` only mentions its own session.
    assert "sess-aaa" in a_text
    assert "sess-bbb" not in a_text
    assert "sess-bbb" in b_text
    assert "sess-aaa" not in b_text
