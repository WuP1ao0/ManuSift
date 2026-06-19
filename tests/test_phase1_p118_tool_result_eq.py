"""R-2026-06-15 (Phase 1 + P1-18):
test ``ToolResult.__eq__`` and
``__hash__``.

Before the fix, two
``ToolResult`` instances
with the same fields were
``!=`` by identity, which
broke test fixtures that
compared results across
calls.  The fix adds
explicit ``__eq__`` and
``__hash__`` (the *full*
``@dataclass`` conversion
is deferred to Phase 4
because it would change
the ``__init__`` signature
in a way that breaks ~200
call sites; the
``__eq__`` /
``__hash__`` fix is the
minimum-viable change that
closes the audit gap).

These tests verify:

  1. Two
     ``ToolResult`` instances
     with the same fields
     are equal.
  2. ``ToolResult`` is
     hashable (so it can be
     used in ``set`` and as
     a ``dict`` key).
  3. ``ToolResult`` with
     nested ``result`` /
     ``metadata`` dicts is
     still hashable (the
     hash function recursively
     flattens).
  4. A ``ToolResult``
     compared to a non-
     ``ToolResult`` returns
     ``NotImplemented`` (not
     ``False``), which
     Python's machinery
     handles correctly (the
     other side gets a
     chance).
  5. The equality is
     *field-by-field*; a
     difference in any one
     field produces a
     non-equal result.
"""
from __future__ import annotations

import pytest

from manusift.tools.tool import ToolResult


def test_p18_two_results_with_same_fields_are_equal():
    """Two ``ToolResult``
    instances with the same
    fields compare equal.
    """
    a = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hi"},
        latency_ms=42,
        metadata={"k": "v"},
    )
    b = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hi"},
        latency_ms=42,
        metadata={"k": "v"},
    )
    assert a == b


def test_p18_results_with_different_fields_not_equal():
    """A field-level difference
    produces a non-equal
    result.
    """
    base = dict(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hi"},
        latency_ms=42,
        metadata={"k": "v"},
    )
    a = ToolResult(**base)
    for field, alt in [
        ("trace_id", "t2"),
        ("tool_name", "grep"),
        ("ok", False),
        ("result", {"stdout": "bye"}),
        ("latency_ms", 99),
        ("metadata", {"k": "w"}),
    ]:
        b = ToolResult(**{**base, field: alt})
        assert a != b, (
            f"expected a != b after changing "
            f"{field!r} to {alt!r}"
        )


def test_p18_result_is_hashable():
    """``ToolResult`` is
    hashable; two equal
    results have the same
    hash.
    """
    a = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hi"},
    )
    b = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hi"},
    )
    assert hash(a) == hash(b)
    # ``set`` deduplicates.
    assert len({a, b}) == 1


def test_p18_nested_dict_result_is_hashable():
    """A ``ToolResult`` with a
    nested-dict ``result``
    and a nested-dict
    ``metadata`` is still
    hashable (the hash
    function recursively
    flattens).
    """
    r = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={
            "stdout": "hi",
            "details": {"nested": [1, 2, 3]},
        },
        metadata={
            "shell_mode": "bash",
            "duration": 1.23,
        },
    )
    # No exception raised.
    h = hash(r)
    assert isinstance(h, int)


def test_p18_eq_returns_notimplemented_for_non_toolresult():
    """A ``ToolResult`` compared
    to a non-``ToolResult``
    returns
    ``NotImplemented`` (not
    ``False``), so Python can
    try the other side's
    ``__eq__``.
    """
    r = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
    )
    result = r.__eq__("not a tool result")
    assert result is NotImplemented


def test_p18_factory_methods_produce_equal_results():
    """``ToolResult.ok(...)``
    and
    ``ToolResult.fail(...)``
    produce the same result
    as a direct constructor
    call.
    """
    a = ToolResult.ok(
        trace_id="t1",
        tool_name="bash",
        result={"x": 1},
    )
    b = ToolResult(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"x": 1},
    )
    assert a == b


def test_p18_from_envelope_results_are_equal():
    """Two ``ToolResult`` objects
    built via ``from_envelope``
    with the same fields
    compare equal.
    """
    a = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=False,
        error_kind="command_failed",
        error="exit code 1",
    )
    b = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=False,
        error_kind="command_failed",
        error="exit code 1",
    )
    assert a == b
    assert hash(a) == hash(b)
