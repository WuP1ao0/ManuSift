"""R-2026-06-15 (Phase 1 + P1-1):
test ``ToolContext.metadata``
read-only invariant.

The original dataclass
``frozen=True`` did NOT
freeze the inner ``dict``
(the class-level flag only
blocks attribute assignment,
not item assignment on a
mutable field).  A tool could
silently mutate
``ctx.metadata`` in place and
corrupt the next tool's view
of the same context (and any
audit log that had snapshotted
the dict by reference).

The fix wraps the dict in a
``MappingProxyType`` in
``__post_init__`` and adds a
``with_metadata`` builder for
the only legitimate use case
(adding a key after
construction).

These tests cover:

  1. ``ctx.metadata`` is a
     ``MappingProxyType`` after
     construction.
  2. ``ctx.metadata["k"] = v``
     raises ``TypeError``.
  3. ``ctx.metadata["k"]``
     read access still works.
  4. ``ctx.with_metadata(**kw)``
     returns a NEW
     ``ToolContext`` with the
     merged keys.
  5. ``ctx.with_metadata`` does
     not mutate the original.
  6. The default
     ``ToolContext(trace_id=)``
     has an empty metadata.
  7. ``ctx.with_metadata`` can
     overwrite an existing
     key.
"""
from __future__ import annotations

import pickle
from types import MappingProxyType

import pytest

from manusift.tools.tool import ToolContext


def test_p11_metadata_is_mappingproxy_after_construction():
    """After
    ``ToolContext(metadata={"k": v})``
    the ``metadata`` field is a
    ``MappingProxyType`` (not
    the original dict).
    """
    ctx = ToolContext(
        trace_id="t", metadata={"k": "v"}
    )
    assert isinstance(
        ctx.metadata, MappingProxyType
    )


def test_p11_metadata_is_empty_mappingproxy_when_default():
    """The default
    ``ToolContext(trace_id=)``
    has an empty
    ``MappingProxyType`` for
    metadata (not ``None``,
    not a mutable dict).
    """
    ctx = ToolContext(trace_id="t")
    assert isinstance(
        ctx.metadata, MappingProxyType
    )
    assert len(ctx.metadata) == 0


def test_p11_metadata_writes_raise_typeerror():
    """Writing to
    ``ctx.metadata["k"] = v``
    must raise ``TypeError``
    -- this is the bug the
    fix is closing.  Note
    that ``MappingProxyType``
    does not expose mutable
    methods (``pop``,
    ``setdefault``, ``update``)
    at all, so those raise
    ``AttributeError``.  Only
    ``__setitem__`` /
    ``__delitem__`` raise
    ``TypeError``.
    """
    ctx = ToolContext(
        trace_id="t", metadata={"k": "v"}
    )
    with pytest.raises(TypeError):
        ctx.metadata["k"] = "new"
    with pytest.raises(TypeError):
        ctx.metadata["new"] = "x"
    with pytest.raises(TypeError):
        del ctx.metadata["k"]


def test_p11_metadata_mutable_methods_absent():
    """``MappingProxyType`` does
    not expose ``dict.pop`` /
    ``dict.setdefault`` /
    ``dict.update`` / etc.
    Calling them raises
    ``AttributeError`` (not
    ``TypeError``).  This is a
    second-line defence: even
    if a tool tried to use a
    dict-specific API, it
    cannot.
    """
    ctx = ToolContext(
        trace_id="t", metadata={"k": "v"}
    )
    with pytest.raises(AttributeError):
        ctx.metadata.pop("k", None)
    with pytest.raises(AttributeError):
        ctx.metadata.setdefault("k", "x")
    with pytest.raises(AttributeError):
        ctx.metadata.update({"k": "v"})
    with pytest.raises(AttributeError):
        ctx.metadata.clear()


def test_p11_metadata_reads_still_work():
    """Read access is unchanged:
    ``ctx.metadata["k"]`` and
    ``ctx.metadata.get("k")``
    both work, and the value is
    the one passed in.
    """
    ctx = ToolContext(
        trace_id="t", metadata={"k": "v"}
    )
    assert ctx.metadata["k"] == "v"
    assert ctx.metadata.get("k") == "v"
    assert ctx.metadata.get("missing") is None


def test_p11_with_metadata_returns_new_context():
    """``with_metadata`` is the
    only supported way to add
    a key after construction;
    it returns a NEW
    ``ToolContext`` with the
    merged keys (a copy-on-write
    pattern).
    """
    ctx = ToolContext(
        trace_id="t", metadata={"a": 1}
    )
    new = ctx.with_metadata(b=2)
    assert new is not ctx
    assert isinstance(
        new.metadata, MappingProxyType
    )
    assert new.metadata["a"] == 1
    assert new.metadata["b"] == 2


def test_p11_with_metadata_does_not_mutate_original():
    """The original ``ctx`` is
    unchanged after
    ``with_metadata`` (the
    ``frozen=True`` invariant
    is preserved).
    """
    ctx = ToolContext(
        trace_id="t", metadata={"a": 1}
    )
    _ = ctx.with_metadata(b=2)
    assert "b" not in ctx.metadata
    assert ctx.metadata == {"a": 1}


def test_p11_with_metadata_overwrites_existing_key():
    """``with_metadata(k=v)``
    when ``k`` is already in
    ``metadata`` overwrites the
    value (dict.update semantics).
    """
    ctx = ToolContext(
        trace_id="t", metadata={"a": 1}
    )
    new = ctx.with_metadata(a=99)
    assert new.metadata["a"] == 99
    assert ctx.metadata["a"] == 1  # original


def test_p11_with_metadata_chains():
    """Multiple ``with_metadata``
    calls chain cleanly.
    """
    ctx = (
        ToolContext(trace_id="t")
        .with_metadata(a=1)
        .with_metadata(b=2)
        .with_metadata(c=3)
    )
    assert ctx.metadata == {
        "a": 1, "b": 2, "c": 3
    }


def test_p11_metadata_is_picklable():
    """``MappingProxyType`` is
    picklable on Python 3.x, so
    the audit log (which
    serialises ``ToolContext``
    via pickle) still works.
    """
    ctx = ToolContext(
        trace_id="t",
        metadata={"a": 1, "b": [1, 2]},
    )
    roundtrip = pickle.loads(
        pickle.dumps(ctx)
    )
    assert roundtrip.trace_id == "t"
    assert roundtrip.metadata == {
        "a": 1, "b": [1, 2]
    }


def test_p11_metadata_is_hashable():
    """``MappingProxyType`` is
    not hashable (mapping),
    but ``ToolContext`` itself
    is hashable via the
    dataclass.  The hash is
    derived from ``trace_id``
    + ``current_pdf`` only
    (the metadata is excluded
    from ``__hash__`` by the
    default dataclass rules).
    """
    ctx1 = ToolContext(trace_id="t")
    ctx2 = ToolContext(
        trace_id="t", metadata={"a": 1}
    )
    # Equal trace_id => equal
    # hash.
    assert hash(ctx1) == hash(ctx2)
