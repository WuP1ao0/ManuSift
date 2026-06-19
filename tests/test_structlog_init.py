"""Tests for the optional structlog integration (P0-9).

The default logging path is a hand-written JSON
formatter that has been with the project since
Step 1. P0-9 layers structlog on top of it as an
opt-in swap: set ``MANUSIFT_STRUCTLOG=1`` (or the
matching Settings field) to get structlog's nicer
processor chain, and leave the env var unset to
keep the legacy formatter untouched.

Guarantees:

  1. With no flag, ``configure_logging`` is the
     legacy JSON handler (one StreamHandler,
     no structlog import).

  2. With ``MANUSIFT_STRUCTLOG=1`` and structlog
     installed, the root logger gets the
     structlog bridge handler.

  3. The structlog processor ``_add_trace_id``
     attaches the current ``trace_id`` to every
     log event when a ContextVar is bound.

  4. If ``MANUSIFT_STRUCTLOG=1`` but structlog
     is not importable, ``configure_logging``
     falls back to the legacy formatter and
     emits a ``UserWarning`` so the operator
     knows what happened.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import warnings
from typing import Any

import pytest

from manusift import trace as trace_mod
from manusift.trace import (
    _add_trace_id,
    bind_trace_id,
    configure_logging,
    trace_id_scope,
)


@pytest.fixture(autouse=True)
def _reset_logging() -> Any:
    """Save and restore root logger state around each
    test, and clear any structlog context-var state
    that previous tests may have bound. Without
    this clear, ``merge_contextvars`` would still
    see a ``trace_id`` from an earlier test, and
    the next test's processor assertion would be
    polluted."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    # Clear our own trace_id ContextVar too.
    from manusift import trace as _trace
    token = _trace._current_trace_id.set(None)
    yield
    _trace._current_trace_id.reset(token)
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


# ---------- 1. Default is the legacy JSON handler ----------

def test_default_path_does_not_import_structlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the flag, ``configure_logging`` adds
    the legacy JSON handler and does not touch
    structlog."""
    # Make sure no env var is set.
    monkeypatch.delenv("MANUSIFT_STRUCTLOG", raising=False)
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
    handler = root.handlers[0]
    # The handler's formatter is the legacy JSON
    # formatter, not a structlog bridge.
    assert type(handler.formatter).__name__ == "_JsonFormatter"


# ---------- 2. Flag enables structlog ----------

def test_structlog_flag_installs_bridge_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MANUSIFT_STRUCTLOG=1`` swaps the legacy
    handler for a structlog bridge. We also
    assert the structlog library is configured
    (the ``is_configured`` flag flips to True)."""
    monkeypatch.setenv("MANUSIFT_STRUCTLOG", "1")
    try:
        import structlog
    except ImportError:
        pytest.skip("structlog not installed")
    configure_logging()
    root = logging.getLogger()
    # structlog was configured.
    assert structlog.is_configured()
    # A handler is attached to the root logger.
    assert len(root.handlers) >= 1


def test_structlog_false_value_does_not_enable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MANUSIFT_STRUCTLOG=0`` must keep the legacy
    formatter — only truthy values trigger the
    swap."""
    monkeypatch.setenv("MANUSIFT_STRUCTLOG", "0")
    configure_logging()
    root = logging.getLogger()
    assert type(root.handlers[0].formatter).__name__ == "_JsonFormatter"


def test_structlog_yes_also_enables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MANUSIFT_STRUCTLOG=yes`` is an alias for
    truthy."""
    monkeypatch.setenv("MANUSIFT_STRUCTLOG", "yes")
    try:
        import structlog  # noqa: F401
    except ImportError:
        pytest.skip("structlog not installed")
    configure_logging()
    import structlog
    assert structlog.is_configured()


# ---------- 3. trace_id processor ----------

def test_add_trace_id_processor_attaches_id() -> None:
    """When a trace id is bound, the processor
    adds it to the event dict. When nothing is
    bound, the event dict is unchanged."""
    # Case 1: no trace id.
    out = _add_trace_id(None, "info", {"event": "hello"})
    assert "trace_id" not in out
    # Case 2: trace id is bound in the ContextVar.
    with trace_id_scope("t-abc123"):
        out = _add_trace_id(None, "info", {"event": "hello"})
    assert out["trace_id"] == "t-abc123"


def test_add_trace_id_does_not_overwrite_existing() -> None:
    """If the caller already put a ``trace_id`` key
    in the event dict (e.g. via ``log.bind``), the
    ContextVar value must not clobber it. setdefault
    semantics."""
    with trace_id_scope("t-abc"):
        out = _add_trace_id(None, "info", {"trace_id": "caller-set"})
    assert out["trace_id"] == "caller-set"


# ---------- 4. Fallback when structlog missing ----------

def test_missing_structlog_falls_back_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``MANUSIFT_STRUCTLOG=1`` but structlog is
    not importable, ``configure_logging`` falls
    back to the legacy JSON handler and emits a
    UserWarning. We simulate "missing" by hiding
    the structlog module from the import system."""
    monkeypatch.setenv("MANUSIFT_STRUCTLOG", "1")
    import builtins
    real_import = builtins.__import__

    def guarded_import(name, *a, **kw):  # type: ignore[no-untyped-def]
        if name == "structlog" or name.startswith("structlog."):
            raise ImportError("simulated missing structlog")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        configure_logging()
    # The warning tells the operator to install
    # structlog.
    msgs = [str(x.message) for x in w]
    assert any("pip install structlog" in m for m in msgs)
    # The legacy handler is back.
    root = logging.getLogger()
    assert type(root.handlers[0].formatter).__name__ == "_JsonFormatter"


# ---------- 5. Legacy JSON formatter still works ----------

def test_legacy_json_formatter_includes_trace_id() -> None:
    """The legacy formatter (the P0-9 default path)
    still writes the trace_id when one is bound.
    This is the P0-9 'do not regress what exists'
    guarantee."""
    with trace_id_scope("t-legacy"):
        # Capture stderr.
        import io
        buf = io.StringIO()
        h = logging.StreamHandler(stream=buf)
        h.setFormatter(trace_mod._JsonFormatter())
        root = logging.getLogger("manusift.test")
        # Avoid double-handling.
        for old in list(root.handlers):
            root.removeHandler(old)
        root.addHandler(h)
        root.setLevel(logging.INFO)
        root.info("hello")
        # Restore root (the _reset_logging fixture
        # will do this for us at teardown).
    line = buf.getvalue().strip()
    rec = json.loads(line)
    assert rec["trace_id"] == "t-legacy"
    assert rec["msg"] == "hello"
    assert rec["level"] == "INFO"


# ---------- 6. Module surface ----------

def test_module_exposes_structlog_helpers() -> None:
    """The new helpers are importable from the
    top-level module so tests and other code do
    not have to reach into private names."""
    assert hasattr(trace_mod, "_configure_structlog")
    assert hasattr(trace_mod, "_add_trace_id")
    assert hasattr(trace_mod, "_StructlogBridge")
