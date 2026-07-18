"""R-2026-06-19 (P2-C6):
``citation_network``
cache TTL.

The previous
implementation
cached every
Crossref
response
forever (the
cache file is
a flat
``dict[str, dict]``
keyed by the
query).  P2-C6
adds:

  * a
    ``ts``
    timestamp
    on every
    cache write
    so the
    cache
    knows when
    the entry
    was
    written;
  * a
    default
    30-day
    TTL
    (configurable
    via
    ``MANUSIFT_CITATION_CACHE_TTL``,
    seconds);
  * a
    backward-compat
    rule
    that
    pre-P2-C6
    entries
    (no
    ``ts``)
    are
    treated
    as
    **stale**
    so the
    first
    run
    after
    upgrade
    re-fetches
    everything
    (safer than
    trusting
    entries of
    unknown
    age).

Tests:

  * ``_is_cache_entry_stale``
    returns
    True for
    entries
    with no
    ``ts``
    key
    (pre-P2-C6
    format).
  * ``_is_cache_entry_stale``
    returns
    False for
    fresh
    entries
    (within
    TTL).
  * ``_is_cache_entry_stale``
    returns
    True for
    old
    entries
    (past
    TTL).
  * ``_is_cache_entry_stale``
    returns
    True when
    ``MANUSIFT_CITATION_CACHE_TTL=0``
    (force
    re-fetch).
  * ``_get_cache_ttl_seconds``
    returns
    the
    default
    when no
    env var
    is set.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manusift.detectors.citation_network import (  # noqa: E402
    DEFAULT_CITATION_CACHE_TTL_SECONDS,
    _get_cache_ttl_seconds,
    _is_cache_entry_stale,
)


# ---------------------------------------------------------------------------
# _is_cache_entry_stale
# ---------------------------------------------------------------------------


class TestIsCacheEntryStale:
    def test_no_ts_key_is_stale(self):
        """Pre-P2-C6 entries
        (no ``ts``) are
        treated as stale."""
        entry = {"item": {"title": "old"}}
        assert _is_cache_entry_stale(entry) is True

    def test_fresh_entry_is_not_stale(self):
        now = time.time()
        entry = {
            "item": {"title": "new"},
            "ts": now,
        }
        assert _is_cache_entry_stale(entry) is False

    def test_old_entry_is_stale(self):
        now = time.time()
        old_ts = now - (DEFAULT_CITATION_CACHE_TTL_SECONDS + 1)
        entry = {"item": {"title": "old"}, "ts": old_ts}
        assert _is_cache_entry_stale(entry) is True

    def test_exactly_at_ttl_boundary_is_not_stale(
        self, monkeypatch
    ):
        """An entry with
        age == TTL is
        still fresh (we
        use ``>`` not
        ``>=``)."""
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "100"
        )
        now = time.time()
        entry = {
            "item": {"title": "x"},
            "ts": now - 100,
        }
        # age == 100 == TTL: not
        # stale (the next
        # second it will be).
        assert _is_cache_entry_stale(entry) is False

    def test_ttl_zero_always_stale(
        self, monkeypatch
    ):
        """``TTL=0`` means
        "always re-fetch"
        (useful for the
        "I just edited
        a paper and want
        the latest
        metadata" use
        case)."""
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "0"
        )
        now = time.time()
        entry = {
            "item": {"title": "x"},
            "ts": now,  # just written
        }
        assert _is_cache_entry_stale(entry) is True

    def test_custom_ttl_via_env(
        self, monkeypatch
    ):
        """A 60-second TTL
        is honored."""
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "60"
        )
        now = time.time()
        # 30 seconds old: fresh
        assert _is_cache_entry_stale(
            {"item": {}, "ts": now - 30}
        ) is False
        # 90 seconds old: stale
        assert _is_cache_entry_stale(
            {"item": {}, "ts": now - 90}
        ) is True


# ---------------------------------------------------------------------------
# _get_cache_ttl_seconds
# ---------------------------------------------------------------------------


class TestGetCacheTtlSeconds:
    def test_default_when_no_env(self, monkeypatch):
        monkeypatch.delenv(
            "MANUSIFT_CITATION_CACHE_TTL", raising=False
        )
        assert (
            _get_cache_ttl_seconds()
            == DEFAULT_CITATION_CACHE_TTL_SECONDS
        )

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "1234"
        )
        assert _get_cache_ttl_seconds() == 1234

    def test_invalid_env_falls_back_to_default(
        self, monkeypatch
    ):
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "not-a-number"
        )
        assert (
            _get_cache_ttl_seconds()
            == DEFAULT_CITATION_CACHE_TTL_SECONDS
        )

    def test_negative_env_returns_zero(self, monkeypatch):
        # Negative TTL is
        # treated as
        # "never cache" (0
        # = always re-fetch).
        monkeypatch.setenv(
            "MANUSIFT_CITATION_CACHE_TTL", "-1"
        )
        assert _get_cache_ttl_seconds() == 0
