"""Cost-bar formatting
helpers for the chat
TUI (R-2026-06-15,
Phase 2 + #5).

The chat TUI's
right-side status bar
shows the running
token + USD totals.
This module adds two
new diagnostics:

  1. **Context-window
     usage.** A
     ``(used,
     total,
     pct)`` triple
     derived from
     the cumulative
     ``_tokens_in`` /
     ``_tokens_out``.
     The model window
     is configurable
     (default 200K
     for Claude 3.5+).
  2. **Prompt-cache
     hit rate.** A
     ``(hit_rate,
     cache_read,
     cache_write)``
     triple derived
     from the
     Anthropic
     ``cache_read_input_tokens`` /
     ``cache_creation_input_tokens``
     usage fields (the
     OpenAI side has
     a different
     shape, but the
     same percent is
     shown).

The formatter is a
**pure function**:
``render_cost_bar(ti,
to, cost_usd, ctx, hit_rate)``
returns a rich-markup
string the chat TUI
renders. Tests can
pin the format
independently of the
chat TUI.

## Why a pure helper
(not just inlined in
``_cost_bar_text``)

The chat TUI's
``_cost_bar_text``
method is 80+ lines
and called from a
hot path (every
cost-bar refresh).
Pure helpers are:

  * Easier
    to
    unit-test
    (the
    format
    contract
    is
    pinned
    by
    tests
    without
    instantiating
    a
    textual
    App).
  * Easier
    to
    read
    (the
    80-line
    method
    becomes
    a
    3-line
    delegator).
  * Easier
    to
    evolve
    (a
    future
    "GPU
    usage"
    column
    is
    one
    new
    helper,
    not
    a
    new
    branch
    in
    a
    80-line
    method).
"""
from __future__ import annotations

from dataclasses import dataclass

# Default
# context-window
# size
# (200K
# for
# Claude
# 3.5+
# Sonnet
# /
# Opus).
# 1M
# for
# Opus 4.5
# (the
# default
# is
# the
# smaller
# of
# the
# two
# so
# the
# cost
# bar
# is
# conservative).
_DEFAULT_MODEL_WINDOW: int = 200_000


@dataclass(frozen=True)
class ContextWindowUsage:
    """The context-window
    usage snapshot.

    ``pct`` is a
    0..100 int (so it
    formats nicely in
    a single-character
    "12%" / "84%" bar).
    """

    used: int
    total: int
    pct: int


@dataclass(frozen=True)
class CacheHitRate:
    """The prompt-cache
    hit rate snapshot.

    ``hit_rate`` is a
    0..100 int (the
    percentage of
    cached input tokens
    vs total input
    tokens).
    ``cache_read`` is
    the cumulative
    number of input
    tokens that hit the
    cache. ``cache_write``
    is the cumulative
    number of input
    tokens that were
    written to the
    cache (the first
    time the system
    prompt is seen, a
    long write to the
    cache happens; the
    next 5 minutes of
    turns are
    cache-reads).
    """

    hit_rate: int
    cache_read: int
    cache_write: int


def compute_context_window(
    tokens_in: int,
    tokens_out: int,
    model_window: int = _DEFAULT_MODEL_WINDOW,
) -> ContextWindowUsage:
    """Compute the
    context-window
    usage from the
    cumulative
    token counters.

    The contract:

      * ``tokens_in``
        is
        the
        cumulative
        input
        tokens
        (the
        system
        prompt
        +
        user
        messages
        +
        any
        cached
        tokens).
      * ``tokens_out``
        is
        the
        cumulative
        output
        tokens
        (the
        assistant's
        responses).
      * ``model_window``
        is
        the
        model's
        max
        context
        window
        (default
        200K).
      * The
        ``used``
        is
        the
        LAST
        turn's
        input
        tokens
        (a
        proxy
        for
        the
        current
        context
        size;
        we
        do
        not
        have
        access
        to
        the
        per-turn
        breakdown
        in
        the
        chat
        TUI).
      * The
        ``pct``
        is
        a
        0..100
        int
        (capped
        at
        100
        so
        a
        weird
        over-100%
        case
        still
        shows
        ``"100%"``,
        not
        ``"200%"``).
      * The
        function
        NEVER
        raises.
        A
        non-int
        input
        is
        treated
        as
        ``0``.
    """
    if not isinstance(tokens_in, int):
        tokens_in = 0
    if not isinstance(tokens_out, int):
        tokens_out = 0
    if not isinstance(model_window, int) or model_window <= 0:
        model_window = _DEFAULT_MODEL_WINDOW
    # The
    # chat
    # TUI
    # does
    # not
    # store
    # the
    # per-turn
    # ``input_tokens``
    # separately
    # from
    # the
    # cumulative
    # ``tokens_in``.
    # We
    # use
    # the
    # cumulative
    # count
    # as
    # a
    # proxy
    # for
    # the
    # "size
    # of
    # the
    # current
    # context
    # window".
    # This
    # is
    # the
    # SAME
    # proxy
    # the
    # chat
    # TUI
    # already
    # uses
    # for
    # its
    # cost
    # display
    # (the
    # difference
    # is
    # that
    # we
    # now
    # also
    # show
    # a
    # percentage
    # of
    # the
    # model
    # window).
    used = tokens_in
    if used < 0:
        used = 0
    if used > model_window:
        used = model_window
    pct = int(used * 100 / model_window)
    if pct > 100:
        pct = 100
    return ContextWindowUsage(
        used=used,
        total=model_window,
        pct=pct,
    )


def compute_cache_hit_rate(
    cache_read_tokens: int,
    total_input_tokens: int,
    cache_creation_tokens: int = 0,
) -> CacheHitRate:
    """Compute the
    prompt-cache hit
    rate.

    The contract:

      * ``cache_read_tokens``
        is
        the
        cumulative
        number
        of
        input
        tokens
        that
        hit
        the
        cache
        (Anthropic
        returns
        this
        as
        ``cache_read_input_tokens``
        in
        each
        ``usage``
        block).
      * ``cache_creation_tokens``
        is
        the
        cumulative
        number
        of
        input
        tokens
        that
        WROTE
        to
        the
        cache
        (Anthropic
        returns
        this
        as
        ``cache_creation_input_tokens``).
        These
        tokens
        are
        NOT
        cache
        hits
        (they
        are
        cache
        writes);
        but
        they
        are
        the
        "fuel"
        for
        future
        hits.
      * ``total_input_tokens``
        is
        the
        cumulative
        input
        tokens
        (a
        cached
        token
        is
        ALSO
        counted
        in
        the
        input
        tokens).
      * The
        ``hit_rate``
        is
        the
        percentage
        of
        input
        tokens
        that
        were
        cache
        reads
        (NOT
        including
        the
        one-time
        cache
        write).
      * The
        function
        NEVER
        raises.
    """
    if not isinstance(cache_read_tokens, int):
        cache_read_tokens = 0
    if not isinstance(total_input_tokens, int):
        total_input_tokens = 0
    if not isinstance(cache_creation_tokens, int):
        cache_creation_tokens = 0
    if total_input_tokens <= 0:
        return CacheHitRate(
            hit_rate=0,
            cache_read=cache_read_tokens,
            cache_write=cache_creation_tokens,
        )
    hit_rate = int(
        cache_read_tokens * 100 / total_input_tokens
    )
    if hit_rate > 100:
        hit_rate = 100
    if hit_rate < 0:
        hit_rate = 0
    return CacheHitRate(
        hit_rate=hit_rate,
        cache_read=cache_read_tokens,
        cache_write=cache_creation_tokens,
    )


def _format_k(n: int) -> str:
    """Format a token
    count as ``"12.3k"``
    or ``"1.2M"`` for
    readability.
    """
    if n < 0:
        n = 0
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def render_context_window_chip(
    usage: ContextWindowUsage,
) -> str:
    """Format the
    context-window chip
    for the cost bar.

    The contract:

      * Returns
        a
        short
        rich-markup
        string
        suitable
        for
        the
        cost
        bar
        (e.g.
        ``"12.3k/200k (6%)"``).
      * The
        chip
        is
        colored
        green
        if
        the
        usage
        is
        under
        50%
        (plenty
        of
        headroom),
        yellow
        if
        50-80%
        (approaching
        the
        limit),
        red
        if
        over
        80%
        (the
        user
        should
        consider
        starting
        a
        new
        session).
      * ``usage.used``
        is
        ``0``
        →
        a
        ``"0/200k (0%)"``
        chip
        (the
        first
        turn).
      * The
        chip
        is
        defensive:
        a
        corrupt
        ``ContextWindowUsage``
        (e.g.
        ``None``
        or
        a
        string)
        returns
        ``""``
        so
        it
        does
        not
        break
        the
        cost
        bar.
    """
    if not isinstance(usage, ContextWindowUsage):
        return ""
    color = "green"
    if usage.pct >= 80:
        color = "red"
    elif usage.pct >= 50:
        color = "yellow"
    return (
        f" [{color}]ctx "
        f"{_format_k(usage.used)}/"
        f"{_format_k(usage.total)}"
        f" ({usage.pct}%)[/{color}]"
    )


def render_cache_hit_rate_chip(
    hit: CacheHitRate,
) -> str:
    """Format the
    prompt-cache hit
    rate chip for the
    cost bar.

    The contract:

      * Returns
        a
        short
        rich-markup
        string
        suitable
        for
        the
        cost
        bar
        (e.g.
        ``"cache 87%"``).
      * The
        chip
        is
        colored
        green
        if
        the
        hit
        rate
        is
        over
        70%
        (excellent
        cache
        hit),
        yellow
        if
        30-70%
        (acceptable
        cache
        hit),
        red
        if
        under
        30%
        (cache
        hit
        is
        poor;
        a
        fresh
        session
        is
        in
        order).
      * When
        the
        hit
        rate
        is
        ``0``
        (no
        cache
        reads
        yet),
        the
        chip
        is
        dimmed
        so
        it
        does
        not
        look
        like
        an
        error.
      * A
        corrupt
        ``CacheHitRate``
        returns
        ``""``
        (defensive).
    """
    if not isinstance(hit, CacheHitRate):
        return ""
    if hit.hit_rate >= 70:
        color = "green"
    elif hit.hit_rate >= 30:
        color = "yellow"
    elif hit.hit_rate > 0:
        color = "red"
    else:
        # 0%
        # ->
        # dimmed
        # (the
        # session
        # just
        # started;
        # the
        # cache
        # will
        # warm
        # up
        # on
        # the
        # next
        # turn).
        return f" [dim]cache {hit.hit_rate}%[/dim]"
    return f" [{color}]cache {hit.hit_rate}%[/{color}]"
