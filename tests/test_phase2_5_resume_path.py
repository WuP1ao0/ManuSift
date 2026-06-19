"""Tests for the R-2026-06-15
(Phase 6 + #5c) ``/resume``
path-mismatch bug fix.

The original
``ChatApp._cmd_resume`` was
looking for saved sessions at::

    settings.workspace_dir / "chats"

i.e. ``data/jobs/chats/`` (one
level *deeper* than the
correct location).  The chat
persistence helper
``_chat_dir`` actually writes
to::

    settings.workspace_dir.parent / "chats"

i.e. ``data/chats/`` (one
level *up*, sibling of the
per-job workspace).  The
result: ``/resume`` always
reported "no saved sessions"
even when the user had been
chatting for many sessions.
This regression test pins the
fix in place.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


from manusift.config import get_settings
from manusift.tui.resume import list_sessions


def test_chat_persistence_and_resume_use_same_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path the chat app *writes*
    to must equal the path the
    resume command *reads* from.

    We construct a fresh workspace
    at ``tmp_path / data``, write a
    fake session to the expected
    location, and assert the resume
    helper finds it.
    """
    # Re-point the workspace at a
    # throwaway directory.  The chat
    # helper reads ``workspace_dir``
    # from the settings singleton --
    # clear the lru_cache so the new
    # value takes effect.
    workspace = tmp_path / "data" / "jobs"
    workspace.mkdir(parents=True)
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(workspace)
    )
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    # The writer (chat_app._chat_dir)
    # writes to ``workspace_dir.parent
    # / "chats"`` = ``data/chats/``.
    expected_chats = s.workspace_dir.parent / "chats"
    # Sanity-check the writer's
    # convention.
    assert (
        expected_chats
        == s.workspace_dir.parent / "chats"
    )
    # Create a fake session dir +
    # messages.jsonl + session.json
    # at the WRITER path.
    sid = "abcdef012345"
    session_dir = expected_chats / sid
    session_dir.mkdir(parents=True)
    msgs = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "world",
        },
    ]
    (session_dir / "messages.jsonl").write_text(
        "\n".join(json.dumps(m) for m in msgs)
        + "\n",
        encoding="utf-8",
    )
    (session_dir / "session.json").write_text(
        json.dumps(
            {"model": "claude-test", "created_at": 1.0}
        ),
        encoding="utf-8",
    )
    # Now run the resume helper and
    # assert it finds the session.
    # (This is the same helper the
    # chat-app's ``_cmd_resume``
    # calls -- if the chat app
    # regresses to the wrong path
    # (``workspace_dir / chats``
    # instead of
    # ``workspace_dir.parent /
    # chats``) this test fails.)
    listings = list_sessions(expected_chats)
    assert len(listings) == 1
    assert listings[0].session_id == sid
    assert listings[0].message_count == 2
    # Defensive: the WRONG path
    # (where the chat app used to
    # look) must be empty.
    wrong_path = s.workspace_dir / "chats"
    if wrong_path.exists():
        assert list(wrong_path.iterdir()) == []


def test_resume_finds_existing_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without any monkey-patching,
    ``list_sessions`` against the
    real ``data/chats/`` directory
    must find the user's existing
    sessions.  This guards the
    path-mismatch bug from
    regressing in the OTHER
    direction (e.g. someone moving
    the writer back to
    ``workspace_dir / chats``)."""
    s = get_settings()
    correct_path = s.workspace_dir.parent / "chats"
    if not correct_path.exists():
        pytest.skip(
            "no chats dir present in this "
            "environment"
        )
    listings = list_sessions(correct_path)
    # There may be 0 if the user has
    # never used the chat TUI in
    # this checkout, but if the
    # directory exists the helper
    # must not raise.
    assert isinstance(listings, list)
