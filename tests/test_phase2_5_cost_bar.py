"""Tests for the R-2026-06-15
(Phase 2 + #5) cost-bar
polish.

Covers:

  * ``compute_context_window``
    - pct
      calculation
    - cap
      at
      100
    - tolerance
      (non-int
      input,
      bad
      model
      window)
  * ``compute_cache_hit_rate``
    - hit
      rate
      from
      cache_read
      vs
      total_input
    - cache_creation
      is
      NOT
      included
      in
      the
      hit
      rate
    - tolerance
      (non-int
      input,
      zero
      total_input)
  * ``render_context_window_chip``
    - green
      <
      50%
    - yellow
      50-80%
    - red
      >=
      80%
    - format
      includes
      ``"ctx"``,
      ``"200k"``,
      ``"%"``
  * ``render_cache_hit_rate_chip``
    - green
      >=
      70%
    - yellow
      30-70%
    - red
      1-29%
    - dimmed
      0%
    - format
      includes
      ``"cache"``
      and
      ``"%"``
  * Defensive
    tolerance
    (corrupt
    dataclass
    input
    returns
    ``""``)

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helper + thin
wiring, both tested.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tui.cost_bar import (
    CacheHitRate,
    ContextWindowUsage,
    _format_k,
    compute_cache_hit_rate,
    compute_context_window,
    render_cache_hit_rate_chip,
    render_context_window_chip,
)


# --------------------------------------------------------------------
# compute_context_window
# --------------------------------------------------------------------


def test_context_window_zero():
    """A zero-token
    session is
    ``0/200k (0%)``.
    """
    out = compute_context_window(0, 0)
    assert out == ContextWindowUsage(
        used=0, total=200_000, pct=0
    )


def test_context_window_under_50_pct_is_under_threshold():
    """A small session
    (12k tokens) is
    well under the
    50% threshold.
    """
    out = compute_context_window(12_000, 5_000)
    assert out.pct == 6
    assert out.used == 12_000
    assert out.total == 200_000


def test_context_window_at_50_pct():
    out = compute_context_window(100_000, 0)
    assert out.pct == 50
    assert out.used == 100_000


def test_context_window_at_80_pct():
    out = compute_context_window(160_000, 0)
    assert out.pct == 80
    assert out.used == 160_000


def test_context_window_at_100_pct_capped():
    """A 250k-token
    session is
    capped at 100%
    (the user has
    overflowed the
    model window).
    """
    out = compute_context_window(250_000, 0)
    assert out.pct == 100
    assert out.used == 200_000  # capped to model window


def test_context_window_custom_window():
    """The model
    window is
    configurable
    (e.g. a 1M-token
    Opus 4.5 session).
    """
    out = compute_context_window(
        100_000, 0, model_window=1_000_000
    )
    assert out.pct == 10
    assert out.total == 1_000_000


def test_context_window_non_int_input_treated_as_zero():
    """A non-int
    ``tokens_in``
    is treated as
    ``0`` so the
    cost bar does
    not crash on a
    missing field.
    """
    out = compute_context_window(None, 0)
    assert out.used == 0
    out = compute_context_window("1000", 0)
    assert out.used == 0


def test_context_window_bad_model_window_falls_back_to_default():
    """A
    non-positive
    ``model_window``
    falls back to
    the default
    (200K) so the
    cost bar does
    not crash.
    """
    out = compute_context_window(50_000, 0, model_window=0)
    assert out.total == 200_000
    out = compute_context_window(50_000, 0, model_window=-1)
    assert out.total == 200_000
    out = compute_context_window(50_000, 0, model_window="junk")
    assert out.total == 200_000


def test_context_window_negative_tokens_clamped_to_zero():
    """A negative
    ``tokens_in``
    (e.g. a buggy
    LLM client) is
    clamped to
    ``0`` (the
    cost bar does
    not show a
    negative
    usage).
    """
    out = compute_context_window(-100, 0)
    assert out.used == 0


# --------------------------------------------------------------------
# compute_cache_hit_rate
# --------------------------------------------------------------------


def test_cache_hit_rate_zero():
    """A session with
    no cache reads
    yet is ``0%``
    (and the
    chip is
    dimmed).
    """
    out = compute_cache_hit_rate(0, 1000)
    assert out.hit_rate == 0
    assert out.cache_read == 0


def test_cache_hit_rate_full_hit():
    """A session
    where every
    input token
    was a cache
    read is
    ``100%``.
    """
    out = compute_cache_hit_rate(1000, 1000)
    assert out.hit_rate == 100


def test_cache_hit_rate_partial():
    """A session
    where half the
    input tokens
    were cache
    reads is
    ``50%``.
    """
    out = compute_cache_hit_rate(500, 1000)
    assert out.hit_rate == 50


def test_cache_hit_rate_capped_at_100():
    """A session
    where
    ``cache_read > total_input``
    (which can
    happen if the
    cache read
    tokens are
    double-counted)
    is capped at
    100% (the cost
    bar does not
    show
    ``"cache 200%"``).
    """
    out = compute_cache_hit_rate(2000, 1000)
    assert out.hit_rate == 100


def test_cache_hit_rate_creation_tokens_dont_inflate_rate():
    """``cache_creation_tokens``
    is the ONE-TIME
    cost of writing
    the system
    prompt to the
    cache. It is
    NOT a cache
    read. The
    ``hit_rate``
    field is
    derived from
    ``cache_read / total_input``
    only (NOT
    ``cache_read / (cache_read + cache_creation)``).
    """
    out = compute_cache_hit_rate(
        cache_read_tokens=1000,
        total_input_tokens=2000,
        cache_creation_tokens=1500,
    )
    # 1000/2000 = 50%
    # (the 1500
    # cache_creation_tokens
    # are fuel for
    # future hits;
    # they do NOT
    # count
    # against
    # the
    # hit
    # rate).
    assert out.hit_rate == 50
    # The
    # cache_creation
    # count
    # is
    # preserved
    # in
    # the
    # result
    # (for
    # future
    # use).
    assert out.cache_write == 1500


def test_cache_hit_rate_zero_total_input():
    """A session
    where
    ``total_input_tokens == 0``
    yields a
    ``hit_rate`` of
    ``0`` (the
    denominator
    is the
    ``total_input``
    count, not
    the
    ``cache_read``
    count; a zero
    total yields a
    zero rate).
    """
    out = compute_cache_hit_rate(0, 0)
    assert out.hit_rate == 0


def test_cache_hit_rate_non_int_input():
    """A non-int
    input is
    treated as
    ``0`` (the
    cost bar does
    not crash on a
    missing field).
    """
    out = compute_cache_hit_rate(
        None, 1000, None
    )
    assert out.hit_rate == 0
    out = compute_cache_hit_rate(
        "500", "1000"
    )
    assert out.hit_rate == 0


# --------------------------------------------------------------------
# render_context_window_chip
# --------------------------------------------------------------------


def test_context_chip_zero_state():
    out = render_context_window_chip(
        ContextWindowUsage(
            used=0, total=200_000, pct=0
        )
    )
    assert "ctx" in out
    assert "200" in out
    assert "0%" in out
    # 0%
    # is
    # green
    # (plenty
    # of
    # headroom).
    assert "[green]" in out


def test_context_chip_under_50_pct_green():
    out = render_context_window_chip(
        ContextWindowUsage(
            used=12_000, total=200_000, pct=6
        )
    )
    assert "[green]" in out
    assert "12.0k" in out
    assert "6%" in out


def test_context_chip_at_50_pct_yellow():
    out = render_context_window_chip(
        ContextWindowUsage(
            used=100_000, total=200_000, pct=50
        )
    )
    assert "[yellow]" in out


def test_context_chip_at_80_pct_red():
    out = render_context_window_chip(
        ContextWindowUsage(
            used=160_000, total=200_000, pct=80
        )
    )
    assert "[red]" in out


def test_context_chip_above_80_pct_red():
    out = render_context_window_chip(
        ContextWindowUsage(
            used=180_000, total=200_000, pct=90
        )
    )
    assert "[red]" in out


def test_context_chip_corrupt_input_returns_empty():
    """A corrupt
    ``ContextWindowUsage``
    (e.g. ``None``
    or a string)
    returns ``""``
    so the cost
    bar does not
    crash.
    """
    assert render_context_window_chip(None) == ""
    assert render_context_window_chip("x") == ""


# --------------------------------------------------------------------
# render_cache_hit_rate_chip
# --------------------------------------------------------------------


def test_cache_chip_zero_state_is_dimmed():
    """A 0% cache
    hit rate is
    dimmed (the
    session just
    started; the
    cache will
    warm up on the
    next turn).
    """
    out = render_cache_hit_rate_chip(
        CacheHitRate(
            hit_rate=0,
            cache_read=0,
            cache_write=1500,
        )
    )
    assert "[dim]" in out
    assert "cache 0%" in out
    # The
    # cache_write
    # is
    # NOT
    # in
    # the
    # chip
    # (we
    # only
    # show
    # the
    # hit
    # rate).
    assert "1500" not in out


def test_cache_chip_high_hit_rate_green():
    out = render_cache_hit_rate_chip(
        CacheHitRate(
            hit_rate=87,
            cache_read=8_700,
            cache_write=1_500,
        )
    )
    assert "[green]" in out
    assert "87%" in out


def test_cache_chip_medium_hit_rate_yellow():
    out = render_cache_hit_rate_chip(
        CacheHitRate(
            hit_rate=50,
            cache_read=500,
            cache_write=1500,
        )
    )
    assert "[yellow]" in out
    assert "50%" in out


def test_cache_chip_low_hit_rate_red():
    out = render_cache_hit_rate_chip(
        CacheHitRate(
            hit_rate=20,
            cache_read=200,
            cache_write=1500,
        )
    )
    assert "[red]" in out
    assert "20%" in out


def test_cache_chip_at_70_pct_threshold_green():
    """The boundary
    is INCLUSIVE
    on the high
    side: ``hit_rate
    == 70`` is
    green (the
    user has a
    solid cache
    hit).
    """
    out = render_cache_hit_rate_chip(
        CacheHitRate(
            hit_rate=70, cache_read=0, cache_write=0
        )
    )
    assert "[green]" in out


def test_cache_chip_corrupt_input_returns_empty():
    assert render_cache_hit_rate_chip(None) == ""
    assert render_cache_hit_rate_chip("x") == ""


# --------------------------------------------------------------------
# _format_k
# --------------------------------------------------------------------


def test_format_k_below_1k():
    assert _format_k(0) == "0"
    assert _format_k(500) == "500"
    assert _format_k(999) == "999"


def test_format_k_1k_to_1m():
    assert _format_k(1_000) == "1.0k"
    assert _format_k(12_000) == "12.0k"
    assert _format_k(123_456) == "123.5k"
    assert _format_k(999_999) == "1000.0k"


def test_format_k_above_1m():
    assert _format_k(1_000_000) == "1.0M"
    assert _format_k(1_500_000) == "1.5M"


def test_format_k_negative_clamped_to_zero():
    """A negative
    count is
    clamped to
    ``0`` (the
    chip never
    shows a
    negative
    number).
    """
    assert _format_k(-1) == "0"
    assert _format_k(-100) == "0"
