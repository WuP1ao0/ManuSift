"""R-2026-06-15 (Phase 1 + P1-2):
test the explicit
``ToolResult.from_envelope``
builder and verify that
``from_legacy_output`` is
deprecated.

The audit flagged
``from_legacy_output`` as a
string-typed contract with
two Hyrum's-Law traps:

  1. ``output.startswith("error:")``
     treats any string that
     *happens* to start with
     the literal ``error:``
     (e.g. ``echo "error: file
     not found"``) as a tool
     failure.  This is a
     legitimate-but-incorrect
     classification for benign
     shell output.

  2. ``json.loads(output)``
     inspects an ``ok=false``
     flag in the parsed dict;
     tools that forget the
     flag (or use a different
     spelling like
     ``success`` or
     ``status``) silently
     fall through to
     ``ok=true``.

The replacement is
``from_envelope``, which
takes explicit ``ok``,
``error_kind``, and
``error`` fields.  No
string-prefix heuristics are
applied; the caller states
directly whether the tool
succeeded.

This test exercises:

  1. ``from_envelope(ok=True)``
     returns a successful
     ``ToolResult``.
  2. ``from_envelope(ok=False)``
     returns a failed
     ``ToolResult`` and
     carries the ``error_kind``
     in metadata.
  3. ``from_envelope`` rejects
     ``ok=True`` with a
     non-None ``error``.
  4. ``from_envelope`` rejects
     ``ok=False`` without an
     ``error``.
  5. ``from_envelope`` does
     NOT classify strings
     starting with ``error:``
     as failures (the old
     Hyrum's-Law trap is
     closed).
  6. ``from_envelope`` does
     NOT inspect the JSON
     ``ok`` flag (the second
     Hyrum's-Law trap is
     closed).
  7. ``from_legacy_output``
     emits a
     ``DeprecationWarning``
     (one per call site
     documented; the warning
     message references the
     new builder).
  8. ``from_legacy_output``
     still works (preserved
     for the AgentLoop path
     during the v1.x series).
"""
from __future__ import annotations

import json
import warnings

import pytest

from manusift.tools.tool import ToolResult


def test_p12_from_envelope_ok():
    """A successful envelope
    carries the ``result`` and
    has ``ok=True`` and
    ``error=None``.
    """
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"stdout": "hello", "exit_code": 0},
    )
    assert r.ok is True
    assert r.error is None
    assert r.result == {
        "stdout": "hello", "exit_code": 0
    }


def test_p12_from_envelope_fail_carries_error_kind():
    """A failed envelope carries
    the ``error_kind`` in the
    metadata (so the LLM-facing
    renderer can switch on it)
    and the human-readable
    ``error`` string.
    """
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=False,
        error_kind="budget_exhausted",
        error="timeout after 30s",
    )
    assert r.ok is False
    assert r.error == "timeout after 30s"
    assert r.metadata["error_kind"] == (
        "budget_exhausted"
    )


def test_p12_from_envelope_fail_without_error_kind():
    """``error_kind`` is
    optional on failure -- some
    failures don't fit a
    category.  ``error`` is
    still required.
    """
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=False,
        error="something went wrong",
    )
    assert r.ok is False
    assert r.error == "something went wrong"
    # error_kind absent.
    assert "error_kind" not in r.metadata


def test_p12_from_envelope_rejects_ok_with_error():
    """``ok=True`` with a
    non-None ``error`` or
    ``error_kind`` is
    rejected -- a successful
    tool result has no error
    information.
    """
    with pytest.raises(ValueError):
        ToolResult.from_envelope(
            trace_id="t1",
            tool_name="bash",
            ok=True,
            error="should not be set",
        )
    with pytest.raises(ValueError):
        ToolResult.from_envelope(
            trace_id="t1",
            tool_name="bash",
            ok=True,
            error_kind="command_failed",
        )


def test_p12_from_envelope_rejects_fail_without_error():
    """``ok=False`` without an
    ``error`` string is
    rejected -- the renderer
    uses ``error`` as the
    user-facing message.
    """
    with pytest.raises(ValueError):
        ToolResult.from_envelope(
            trace_id="t1",
            tool_name="bash",
            ok=False,
            error_kind="budget_exhausted",
        )


def test_p12_from_envelope_does_not_inspect_string_prefix():
    """``from_envelope`` does
    NOT classify strings
    starting with ``error:``
    as failures.  A string
    that happens to start
    with ``error:`` (e.g.
    ``echo "error: file not
    found"``) is *success*
    data, not a failure.
    """
    # This used to be a
    # failure under
    # ``from_legacy_output``.
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result="error: file not found",
    )
    assert r.ok is True
    assert r.result == "error: file not found"
    assert r.error is None


def test_p12_from_envelope_does_not_inspect_json_ok_flag():
    """``from_envelope`` does
    NOT inspect an ``ok``
    field in the result
    dict.  The caller states
    ``ok`` explicitly.
    """
    # A dict with ``ok=false``
    # in the body is *success*
    # data (e.g. a tool that
    # reports a count, or a
    # cached query result),
    # not a failure.
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="data_query",
        ok=True,
        result={"ok": False, "rows": []},
    )
    assert r.ok is True
    assert r.result == {"ok": False, "rows": []}


def test_p12_from_legacy_output_emits_deprecation_warning():
    """The legacy path is
    deprecated.  New code
    must use
    ``from_envelope``.  We
    emit a
    ``DeprecationWarning``
    so the test suite catches
    accidental re-use.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ToolResult.from_legacy_output(
            trace_id="t1",
            tool_name="bash",
            output='{"ok": true, "result": "x"}',
        )
    assert any(
        issubclass(w.category, DeprecationWarning)
        for w in caught
    ), "from_legacy_output did not emit DeprecationWarning"
    assert any(
        "from_envelope" in str(w.message)
        for w in caught
    ), "deprecation warning does not reference the new builder"


def test_p12_from_legacy_output_still_works():
    """The legacy path is
    preserved (deprecation
    only -- no removal).  The
    AgentLoop uses it for
    string-returning tools.
    """
    with warnings.catch_warnings():
        # Suppress the
        # DeprecationWarning so
        # the test assertion is
        # clean.
        warnings.simplefilter("ignore", DeprecationWarning)
        r = ToolResult.from_legacy_output(
            trace_id="t1",
            tool_name="bash",
            output='{"ok": true, "result": "x"}',
        )
    assert r.ok is True
    assert r.result == {"ok": True, "result": "x"}


def test_p12_from_envelope_with_latency_and_metadata():
    """``from_envelope`` carries
    ``latency_ms`` and
    caller-supplied
    ``metadata`` unchanged.
    """
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=True,
        result={"ok": True},
        latency_ms=42,
        metadata={"shell_mode": "bash"},
    )
    assert r.latency_ms == 42
    assert r.metadata == {"shell_mode": "bash"}


def test_p12_to_json_envelope_round_trip():
    """``to_json`` /
    ``from_envelope`` round
    trip preserves the
    ``error_kind`` in
    metadata.
    """
    r = ToolResult.from_envelope(
        trace_id="t1",
        tool_name="bash",
        ok=False,
        error_kind="command_failed",
        error="exit code 1",
    )
    parsed = json.loads(r.to_json())
    assert parsed["ok"] is False
    assert parsed["error"] == "exit code 1"
    assert parsed["metadata"]["error_kind"] == (
        "command_failed"
    )
