"""Tests for the R-2026-06-15
(Phase 0 + 3c) prompt-caching
helper + resume helper.

Covers:

  * ``build_anthropic_cache_metadata``
    returns the right
    ``cache_control`` block
    for each TTL.
  * ``mark_anthropic_system_for_cache``
    + ``mark_anthropic_tools_for_cache``
    attach the
    cache-control marker to
    the LAST block / tool
    only (the rest are
    untouched; marking all
    blocks would invalidate
    the cache on any small
    edit).
  * ``openai_cache_key_from_session``
    returns a session-stable
    key.
  * ``build_openai_cache_extra_body``
    returns the right
    ``extra_body`` block.
  * ``Settings.prompt_cache_ttl``
    is a string field with
    the default
    ``"ephemeral"``.

For the resume helper:

  * ``list_sessions``
    enumerates session
    directories and returns
    their message counts +
    the last user preview.
  * ``parse_resume_arg``
    handles ``""``,
    ``"new"``, integer
    indices, hex prefixes,
    and rejects unknown
    arguments.
  * ``render_resume_listing``
    produces a multi-line
    text block with the
    correct column layout.

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure-helper + thin wiring,
both tested.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.config import Settings
from manusift.llm.prompt_cache import (
    build_anthropic_cache_metadata,
    build_openai_cache_extra_body,
    mark_anthropic_system_for_cache,
    mark_anthropic_tools_for_cache,
    openai_cache_key_from_session,
)
from manusift.tui.resume import (
    SessionListing,
    list_sessions,
    parse_resume_arg,
    render_resume_listing,
)


# --------------------------------------------------------------------
# prompt_cache: build_anthropic_cache_metadata
# --------------------------------------------------------------------


def test_ephemeral_returns_just_type():
    out = build_anthropic_cache_metadata(
        "ephemeral"
    )
    assert out == {"type": "ephemeral"}


def test_5m_returns_ttl():
    out = build_anthropic_cache_metadata("5m")
    assert out == {"type": "ephemeral", "ttl": "5m"}


def test_1h_returns_ttl():
    out = build_anthropic_cache_metadata("1h")
    assert out == {"type": "ephemeral", "ttl": "1h"}


def test_off_returns_empty_dict():
    out = build_anthropic_cache_metadata("off")
    assert out == {}


def test_invalid_ttl_raises_value_error():
    with pytest.raises(ValueError):
        build_anthropic_cache_metadata("bogus")


# --------------------------------------------------------------------
# prompt_cache: mark_anthropic_system_for_cache
# --------------------------------------------------------------------


def test_mark_system_marks_last_block():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    out = mark_anthropic_system_for_cache(
        blocks, "ephemeral"
    )
    # The first block is
    # untouched.
    assert "cache_control" not in out[0]
    # The last block has
    # the marker.
    assert out[-1]["cache_control"] == {
        "type": "ephemeral"
    }
    # The text content is
    # preserved.
    assert out[-1]["text"] == "second"


def test_mark_system_with_off_returns_unchanged():
    blocks = [{"type": "text", "text": "x"}]
    out = mark_anthropic_system_for_cache(
        blocks, "off"
    )
    assert out == blocks
    assert "cache_control" not in out[0]


def test_mark_system_with_empty_list_returns_empty():
    out = mark_anthropic_system_for_cache(
        [], "ephemeral"
    )
    assert out == []


# --------------------------------------------------------------------
# prompt_cache: mark_anthropic_tools_for_cache
# --------------------------------------------------------------------


def test_mark_tools_marks_last_tool():
    tools = [
        {"name": "a", "description": ""},
        {"name": "b", "description": ""},
        {"name": "c", "description": ""},
    ]
    out = mark_anthropic_tools_for_cache(
        tools, "1h"
    )
    assert "cache_control" not in out[0]
    assert "cache_control" not in out[1]
    assert out[2]["cache_control"] == {
        "type": "ephemeral",
        "ttl": "1h",
    }


def test_mark_tools_with_off_returns_unchanged():
    tools = [{"name": "a"}]
    out = mark_anthropic_tools_for_cache(
        tools, "off"
    )
    assert out == tools


# --------------------------------------------------------------------
# prompt_cache: openai_cache_key_from_session
# --------------------------------------------------------------------


def test_openai_cache_key_uses_session_id():
    key = openai_cache_key_from_session("abc123")
    assert "abc123" in key
    # The
    # ``prompt_cache_key``
    # is
    # opaque
    # but
    # must
    # be
    # session-stable
    # (the
    # same
    # input
    # always
    # produces
    # the
    # same
    # output).
    assert (
        openai_cache_key_from_session("abc123")
        == key
    )
    # A
    # different
    # session
    # id
    # produces
    # a
    # different
    # key.
    assert (
        openai_cache_key_from_session("xyz789")
        != key
    )


# --------------------------------------------------------------------
# prompt_cache: build_openai_cache_extra_body
# --------------------------------------------------------------------


def test_openai_extra_body_ephemeral():
    out = build_openai_cache_extra_body(
        cache_key="ignored", ttl="ephemeral"
    )
    assert out == {"cache": {"type": "ephemeral"}}


def test_openai_extra_body_off_returns_empty():
    out = build_openai_cache_extra_body(
        cache_key="ignored", ttl="off"
    )
    assert out == {}


def test_openai_extra_body_invalid_raises():
    with pytest.raises(ValueError):
        build_openai_cache_extra_body(
            cache_key="x", ttl="bogus"
        )


# --------------------------------------------------------------------
# Settings.prompt_cache_ttl
# --------------------------------------------------------------------


def test_settings_prompt_cache_ttl_default():
    s = Settings()
    assert s.prompt_cache_ttl == "ephemeral"


# --------------------------------------------------------------------
# resume: list_sessions
# --------------------------------------------------------------------


def _write_session(
    tmp_path: Path,
    session_id: str,
    messages: list[dict[str, Any]],
    model: str = "claude-opus-4-5",
) -> Path:
    """Helper: write a
    fake session
    directory.
    """
    d = tmp_path / session_id
    d.mkdir()
    (d / "messages.jsonl").write_text(
        "\n".join(
            json.dumps(m, ensure_ascii=False)
            for m in messages
        ),
        encoding="utf-8",
    )
    (d / "session.json").write_text(
        json.dumps(
            {"model": model, "schema": "x"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return d


def test_list_sessions_empty_dir(tmp_path: Path):
    out = list_sessions(tmp_path)
    assert out == []


def test_list_sessions_missing_dir(tmp_path: Path):
    out = list_sessions(tmp_path / "does-not-exist")
    assert out == []


def test_list_sessions_returns_one_row_per_dir(
    tmp_path: Path,
):
    _write_session(
        tmp_path,
        "sess-a",
        [{"role": "user", "content": "hi"}],
    )
    _write_session(
        tmp_path,
        "sess-b",
        [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ],
    )
    out = list_sessions(tmp_path)
    assert len(out) == 2
    ids = {s.session_id for s in out}
    assert ids == {"sess-a", "sess-b"}


def test_list_sessions_counts_messages(tmp_path: Path):
    _write_session(
        tmp_path,
        "sess-a",
        [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ],
    )
    out = list_sessions(tmp_path)
    assert len(out) == 1
    assert out[0].message_count == 3


def test_list_sessions_previews_last_user_message(
    tmp_path: Path,
):
    _write_session(
        tmp_path,
        "sess-a",
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ],
    )
    out = list_sessions(tmp_path)
    # The
    # preview
    # is
    # the
    # MOST
    # RECENT
    # user
    # message,
    # not
    # the
    # first.
    assert out[0].last_user_preview.startswith(
        "second"
    )


def test_list_sessions_no_user_messages(tmp_path: Path):
    _write_session(
        tmp_path,
        "sess-a",
        [
            {"role": "assistant", "content": "hi"},
        ],
    )
    out = list_sessions(tmp_path)
    assert (
        out[0].last_user_preview
        == "(no user messages yet)"
    )


def test_list_sessions_reads_model_from_meta(
    tmp_path: Path,
):
    _write_session(
        tmp_path,
        "sess-a",
        [{"role": "user", "content": "x"}],
        model="claude-opus-4-5",
    )
    out = list_sessions(tmp_path)
    assert out[0].model == "claude-opus-4-5"


def test_list_sessions_tolerates_missing_meta(
    tmp_path: Path,
):
    d = tmp_path / "sess-a"
    d.mkdir()
    (d / "messages.jsonl").write_text(
        json.dumps(
            {"role": "user", "content": "x"}
        ),
        encoding="utf-8",
    )
    # No
    # session.json
    out = list_sessions(tmp_path)
    assert out[0].model == "?"


def test_list_sessions_tolerates_corrupt_meta(
    tmp_path: Path,
):
    d = tmp_path / "sess-a"
    d.mkdir()
    (d / "messages.jsonl").write_text(
        json.dumps(
            {"role": "user", "content": "x"}
        ),
        encoding="utf-8",
    )
    (d / "session.json").write_text(
        "not-valid-json", encoding="utf-8"
    )
    out = list_sessions(tmp_path)
    assert out[0].model == "?"


def test_list_sessions_truncates_long_preview(
    tmp_path: Path,
):
    long = "x" * 200
    _write_session(
        tmp_path,
        "sess-a",
        [{"role": "user", "content": long}],
    )
    out = list_sessions(tmp_path)
    # The
    # preview
    # is
    # truncated
    # to
    # 80
    # chars
    # with
    # an
    # ellipsis.
    assert len(out[0].last_user_preview) <= 83
    assert out[0].last_user_preview.endswith(
        "..."
    )


# --------------------------------------------------------------------
# resume: parse_resume_arg
# --------------------------------------------------------------------


def test_parse_empty_arg_returns_list_mode():
    target = parse_resume_arg("", [])
    assert target.mode == "list"


def test_parse_whitespace_only_returns_list_mode():
    target = parse_resume_arg("   ", [])
    assert target.mode == "list"


def test_parse_new_returns_new_mode():
    target = parse_resume_arg("new", [])
    assert target.mode == "new"


def test_parse_integer_index_returns_switch():
    listings = [
        SessionListing(
            session_id="a",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
        SessionListing(
            session_id="b",
            message_count=2,
            last_user_preview="y",
            last_message_ts=2.0,
            model="?",
        ),
    ]
    # ``"1"``
    # is
    # the
    # most
    # recent.
    target = parse_resume_arg("1", listings)
    assert target.mode == "switch"
    assert target.session_id == "a"
    # ``"2"``
    # is
    # the
    # second-most
    # recent.
    target = parse_resume_arg("2", listings)
    assert target.mode == "switch"
    assert target.session_id == "b"


def test_parse_out_of_range_index_returns_invalid():
    listings = [
        SessionListing(
            session_id="a",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    target = parse_resume_arg("5", listings)
    assert target.mode == "invalid"
    assert "out of range" in target.reason


def test_parse_hex_prefix_matches_session_id():
    listings = [
        SessionListing(
            session_id="abc123def456",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
        SessionListing(
            session_id="deadbeef0001",
            message_count=2,
            last_user_preview="y",
            last_message_ts=2.0,
            model="?",
        ),
    ]
    # A
    # valid
    # hex
    # prefix
    # matches
    # the
    # first
    # listing.
    target = parse_resume_arg("abc", listings)
    assert target.mode == "switch"
    assert target.session_id == "abc123def456"
    # A
    # different
    # valid
    # hex
    # prefix
    # matches
    # the
    # second.
    target = parse_resume_arg("dead", listings)
    assert target.mode == "switch"
    assert target.session_id == "deadbeef0001"
    # The
    # lookup
    # is
    # case-insensitive.
    target = parse_resume_arg("ABC", listings)
    assert target.mode == "switch"
    # Mixed-case
    # also works.
    target = parse_resume_arg("aBc", listings)
    assert target.mode == "switch"


def test_parse_non_hex_prefix_returns_invalid():
    """A prefix containing
    non-hex characters
    (``x``, ``y``, ``z``)
    is rejected: the
    ``_HEX_PREFIX``
    regex requires every
    character to be in
    ``[0-9a-fA-F]``. The
    user gets a
    "unknown resume
    target" error.
    """
    listings = [
        SessionListing(
            session_id="abc123def456",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    target = parse_resume_arg("xyz", listings)
    assert target.mode == "invalid"


def test_parse_hex_prefix_no_match_returns_invalid():
    listings = [
        SessionListing(
            session_id="abc123def456",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    # A
    # valid
    # hex
    # prefix
    # that
    # does
    # not
    # match
    # any
    # session
    # id.
    target = parse_resume_arg("fff", listings)
    assert target.mode == "invalid"
    assert "no session id starts with" in (
        target.reason
    )


def test_parse_unknown_arg_returns_invalid():
    target = parse_resume_arg("hello world", [])
    assert target.mode == "invalid"
    assert "unknown resume target" in (
        target.reason
    )


# --------------------------------------------------------------------
# resume: render_resume_listing
# --------------------------------------------------------------------


def test_render_listing_empty():
    out = render_resume_listing([])
    assert (
        "no saved sessions; this is your first run."
        in out
    )


def test_render_listing_has_header():
    listings = [
        SessionListing(
            session_id="a",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    out = render_resume_listing(listings)
    assert "=== Past chat sessions ===" in out
    # The
    # first
    # column
    # is
    # the
    # 1-based
    # index.
    assert "1. a" in out
    # The
    # singular
    # form
    # is
    # used
    # for
    # ``message_count == 1``.
    assert "1 msg" in out


def test_render_listing_plural_messages():
    listings = [
        SessionListing(
            session_id="a",
            message_count=2,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    out = render_resume_listing(listings)
    assert "2 msgs" in out


def test_render_listing_includes_model_suffix():
    listings = [
        SessionListing(
            session_id="a",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="claude-opus-4-5",
        ),
    ]
    out = render_resume_listing(listings)
    assert "(model=claude-opus-4-5)" in out


def test_render_listing_omits_unknown_model_suffix():
    listings = [
        SessionListing(
            session_id="a",
            message_count=1,
            last_user_preview="x",
            last_message_ts=1.0,
            model="?",
        ),
    ]
    out = render_resume_listing(listings)
    assert "(model=?)" not in out
