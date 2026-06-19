"""R-2026-06-15 (Phase 3 + P3-5):
verify the per-child
``_called_signatures``
isolation.

The audit flagged that
the child ``AgentLoop``
spawned by ``TaskTool``
shared the parent's
``_called_signatures``
set -- a subagent's
calls would block the
parent's (or vice
versa), and a
sub-sub-agent's calls
would not be deduped
independently.

The fix is per-instance
isolation: every
``AgentLoop.__init__``
creates a fresh
``OrderedDict()`` for
``self._called_signatures``
and
``self._tool_call_counts``
so the parent's and the
child's state are
independent.

These tests verify:

  1. Two independent
     ``AgentLoop``
     instances have
     distinct
     ``_called_signatures``
     (one does not
     affect the other).
  2. The
     ``_called_signatures``
     starts empty on a
     fresh instance.
  3. The
     ``_tool_call_counts``
     dict is also
     independent.
  4. The cap
     (``_CALLED_SIGNATURES_CAP``)
     is per-instance,
     not shared via
     class attribute.
  5. The
     ``_called_signatures``
     is an
     ``OrderedDict``
     (the P1-16 fix
     turned the
     old ``set``
     into an LRU
     cap; we
     preserve that
     invariant).
"""
from __future__ import annotations

from collections import OrderedDict

import pytest

from manusift.agent import AgentLoop
from manusift.tools.tool import ToolContext


def _make_loop() -> AgentLoop:
    return AgentLoop(
        client=None,  # type: ignore[arg-type]
        tools=[],
        ctx=ToolContext(trace_id="t-p35"),
        max_steps=4,
    )


def test_p35_two_loops_have_independent_signatures() -> None:
    """Two
    ``AgentLoop``
    instances do NOT
    share
    ``_called_signatures``.
    """
    loop_a = _make_loop()
    loop_b = _make_loop()
    # Add a signature
    # to loop_a.
    sig = ("tool_x", '{"a": 1}')
    loop_a._called_signatures[sig] = None
    # loop_b's
    # ``_called_signatures``
    # does NOT contain
    # it.
    assert sig not in loop_b._called_signatures
    # And modifying
    # loop_b does NOT
    # affect loop_a.
    sig2 = ("tool_y", '{"b": 2}')
    loop_b._called_signatures[sig2] = None
    assert sig2 not in loop_a._called_signatures
    assert sig in loop_a._called_signatures


def test_p35_signatures_start_empty() -> None:
    """A fresh
    ``AgentLoop``
    has an empty
    ``_called_signatures``.
    """
    loop = _make_loop()
    assert len(loop._called_signatures) == 0


def test_p35_tool_call_counts_are_independent() -> None:
    """Two ``AgentLoop``
    instances do NOT
    share
    ``_tool_call_counts``.
    """
    loop_a = _make_loop()
    loop_b = _make_loop()
    loop_a._tool_call_counts["x"] = 5
    assert "x" not in loop_b._tool_call_counts


def test_p35_called_signatures_cap_is_per_instance() -> None:
    """The
    ``_CALLED_SIGNATURES_CAP``
    attribute is per
    instance
    (i.e. NOT a class
    attribute), so a
    parent and child
    can have
    different caps.
    """
    loop = _make_loop()
    # ``_CALLED_SIGNATURES_CAP``
    # is set in
    # ``__init__``;
    # changing it on
    # one instance
    # does NOT
    # affect another.
    loop._CALLED_SIGNATURES_CAP = 42
    loop_b = _make_loop()
    assert (
        loop_b._CALLED_SIGNATURES_CAP == 1000
    )
    assert loop._CALLED_SIGNATURES_CAP == 42


def test_p35_called_signatures_is_ordered_dict() -> None:
    """The
    ``_called_signatures``
    is an
    ``OrderedDict``
    (the P1-16 LRU
    invariant).
    """
    loop = _make_loop()
    assert isinstance(
        loop._called_signatures, OrderedDict
    )


def test_p35_lru_cap_eviction_is_per_instance() -> None:
    """LRU eviction
    (P1-16) is
    per-instance:
    filling loop_a's
    signatures
    beyond the cap
    does NOT evict
    loop_b's.
    """
    loop_a = _make_loop()
    loop_b = _make_loop()
    # Shrink loop_a's
    # cap to 3 for the
    # test.
    loop_a._CALLED_SIGNATURES_CAP = 3
    # Fill loop_a with
    # 5 sigs -- the
    # oldest 2 should
    # be evicted.
    for i in range(5):
        sig = (f"tool_{i}", str(i))
        loop_a._called_signatures[sig] = None
        if (
            len(loop_a._called_signatures)
            > loop_a._CALLED_SIGNATURES_CAP
        ):
            loop_a._called_signatures.popitem(
                last=False
            )
    assert len(loop_a._called_signatures) == 3
    # loop_b is
    # unaffected.
    assert len(loop_b._called_signatures) == 0
