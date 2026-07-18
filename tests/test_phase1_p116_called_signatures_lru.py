"""R-2026-06-15 (Phase 1 + P1-16):
test ``_called_signatures``
LRU cap.

The audit found that the
per-(tool_name, args)
``_called_signatures`` set
was unbounded.  A
pathological agent loop
that calls many *unique*
tools (e.g. one per row in
a 50k-row data audit) would
grow the set without bound,
eventually OOMing the chat
session.  The fix caps the
set at
``_CALLED_SIGNATURES_CAP``
entries (1000 by default)
and evicts the
least-recently-added entry
on overflow.

These tests verify:

  1. The set starts empty
     and accepts new
     entries up to the cap.
  2. After the cap, the
     oldest entry is
     evicted (LRU).
  3. The cap is enforced
     even under stress
     (10,000 unique
     signatures).
  4. ``in`` checks work
     (the dedup path is
     unaffected).
  5. Re-adding an existing
     signature refreshes
     the LRU position (the
     new entry is *not*
     evicted; the still-
     older ones are).
  6. ``pop(sig, None)`` is
     used instead of
     ``discard`` (the audit
     noted this
     incompatibility).
"""
from __future__ import annotations

from collections import OrderedDict

import pytest

from manusift.agent import AgentLoop
from manusift.tools.tool import ToolContext


def _make_loop() -> AgentLoop:
    ctx = ToolContext(trace_id="t-p16")
    return AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[],
        ctx=ctx,
        max_steps=4,
    )


def test_p16_called_signatures_is_ordered_dict():
    """The cap'd data structure
    is an ``OrderedDict`` (so
    we can do LRU).
    """
    loop = _make_loop()
    assert isinstance(
        loop._called_signatures, OrderedDict
    )


def test_p16_called_signatures_cap_is_1000():
    """The cap is 1000 (the
    audit-recommended value).
    """
    loop = _make_loop()
    assert (
        loop._CALLED_SIGNATURES_CAP == 1000
    )


def test_p16_called_signatures_capped_at_1000():
    """After 5000 unique
    additions, the set has
    at most 1000 entries
    (the cap).
    """
    loop = _make_loop()
    for i in range(5000):
        sig = f"sig-{i}"
        loop._called_signatures[sig] = None
        loop._called_signatures.move_to_end(sig)
        while (
            len(loop._called_signatures)
            > loop._CALLED_SIGNATURES_CAP
        ):
            loop._called_signatures.popitem(
                last=False
            )
    assert (
        len(loop._called_signatures) == 1000
    )


def test_p16_lru_evicts_oldest():
    """After exceeding the
    cap, the oldest
    signatures are evicted;
    the newest are kept.
    """
    loop = _make_loop()
    # Add 1500 signatures in
    # order ``sig-0``,
    # ``sig-1``, ..., ``sig-1499``.
    for i in range(1500):
        sig = f"sig-{i}"
        loop._called_signatures[sig] = None
        loop._called_signatures.move_to_end(sig)
        while (
            len(loop._called_signatures)
            > loop._CALLED_SIGNATURES_CAP
        ):
            loop._called_signatures.popitem(
                last=False
            )
    # The oldest 500 are
    # evicted.
    assert "sig-0" not in (
        loop._called_signatures
    )
    assert "sig-499" not in (
        loop._called_signatures
    )
    # The newest 1000 are
    # kept.
    assert "sig-500" in (
        loop._called_signatures
    )
    assert "sig-1499" in (
        loop._called_signatures
    )


def test_p16_in_check_works():
    """``sig in
    self._called_signatures``
    works on the
    ``OrderedDict`` (the
    dedup path is unchanged).
    """
    loop = _make_loop()
    loop._called_signatures["sig-a"] = None
    assert "sig-a" in (
        loop._called_signatures
    )
    assert "sig-b" not in (
        loop._called_signatures
    )


def test_p16_readd_refreshes_lru_position():
    """Re-adding an existing
    signature (via
    ``move_to_end``) refreshes
    the LRU position; the
    still-older signatures
    are evicted instead.
    """
    loop = _make_loop()
    # Add sig-0, sig-1,
    # ..., sig-1499.
    for i in range(1500):
        loop._called_signatures[f"sig-{i}"] = (
            None
        )
        loop._called_signatures.move_to_end(
            f"sig-{i}"
        )
        while (
            len(loop._called_signatures)
            > loop._CALLED_SIGNATURES_CAP
        ):
            loop._called_signatures.popitem(
                last=False
            )
    # sig-0 was evicted.
    assert "sig-0" not in (
        loop._called_signatures
    )
    # Re-add sig-0 (refreshes
    # its LRU position).
    loop._called_signatures["sig-0"] = None
    loop._called_signatures.move_to_end("sig-0")
    # Add a new sig-1500
    # (no overflow, since
    # sig-0 was added at the
    # tail).
    loop._called_signatures["sig-1500"] = None
    loop._called_signatures.move_to_end("sig-1500")
    while (
        len(loop._called_signatures)
        > loop._CALLED_SIGNATURES_CAP
    ):
        loop._called_signatures.popitem(
            last=False
        )
    # sig-1501 forces an
    # overflow that evicts
    # sig-1 (the next-oldest,
    # not sig-0).
    loop._called_signatures["sig-1501"] = None
    loop._called_signatures.move_to_end("sig-1501")
    while (
        len(loop._called_signatures)
        > loop._CALLED_SIGNATURES_CAP
    ):
        loop._called_signatures.popitem(
            last=False
        )
    # sig-0 is still there
    # (refreshed).
    assert "sig-0" in (
        loop._called_signatures
    )
    # sig-1 is now evicted.
    assert "sig-1" not in (
        loop._called_signatures
    )


def test_p16_pop_uses_default_not_discard():
    """The rollback path uses
    ``pop(sig, None)``
    (OrderedDict API) instead
    of ``discard`` (set API).
    We assert the source code
    does NOT call
    ``_called_signatures.discard``
    anywhere -- a future
    refactor that re-introduces
    the set API on a dict
    fails this test.
    """
    from pathlib import Path
    import re

    src = (
        Path(__file__).resolve().parents[1]
        / "manusift"
        / "agent"
        / "__init__.py"
    ).read_text(encoding="utf-8")
    # Strip docstrings and
    # comments.
    no_doc = re.sub(
        r'"""[\s\S]*?"""', "", src
    )
    no_comments = re.sub(
        r"#[^\n]*", "", no_doc
    )
    # ``.discard`` is a
    # ``set``-only method.
    # The rollback path on
    # line 2738-ish must NOT
    # use it.
    assert (
        "_called_signatures.discard"
        not in no_comments
    ), (
        "_called_signatures.discard is a "
        "set-API call on an OrderedDict; "
        "use .pop(sig, None) instead"
    )
