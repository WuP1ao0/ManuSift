"""Tests for the hook registry (Step E5).

E5 introduces a single
``HookRegistry`` that supports an
arbitrary number of subscribers per
hook name. The pipeline and the
agent loop call
``hooks.dispatch("on_step", res, job_state)``
and the registry fans the call out
to every registered subscriber.

Guarantees:

  1. ``subscribe(name, fn)`` returns
     ``fn`` for symmetric
     ``unsubscribe`` use.
  2. ``dispatch(name, *args, **kwargs)``
     invokes every registered
     subscriber in registration
     order. A subscriber that raises
     is logged and skipped; the next
     subscriber still fires.
  3. ``unsubscribe`` for an unknown
     hook name or function is a
     no-op; the registry does not
     raise.
  4. ``subscribers(name)`` returns a
     snapshot, not the live list, so
     a subscriber that
     subscribes/unsubscribes during
     a dispatch does not race the
     iteration.
  5. ``reset_hooks`` is a test hook
     that clears every subscriber
     and returns a fresh registry.
  6. ``iter_entrypoint_hooks`` yields
     ``(name, fn)`` tuples from the
     ``manusift.hooks`` entry-point
     group. A plugin that returns a
     list of tuples is supported.
  7. ``iter_entrypoint_hooks``
     auto-registers the returned
     callables on the global
     registry.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest


# ---------- 1. HookRegistry basics ----------

def test_subscribe_returns_handle() -> None:
    """``subscribe`` returns ``fn`` for
    symmetric ``unsubscribe`` use."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()

    def my_fn(*a, **k) -> None:
        pass

    handle = h.subscribe("on_step", my_fn)
    assert handle is my_fn


def test_dispatch_invokes_subscribers_in_registration_order() -> None:
    """``dispatch`` invokes every
    registered subscriber in
    registration order."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    seen: list[str] = []
    h.subscribe("x", lambda *a, **k: seen.append("a"))
    h.subscribe("x", lambda *a, **k: seen.append("b"))
    h.subscribe("x", lambda *a, **k: seen.append("c"))
    h.dispatch("x", 1, 2, 3)
    assert seen == ["a", "b", "c"]


def test_dispatch_passes_args_and_kwargs() -> None:
    """``dispatch`` forwards the
    positional and keyword
    arguments to every
    subscriber."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    received: list[tuple[tuple, dict]] = []
    def capture(*args, **kwargs):
        received.append((args, kwargs))
    h.subscribe("x", capture)
    h.dispatch("x", 1, 2, k="v")
    assert received == [((1, 2), {"k": "v"})]


def test_dispatch_skips_subscribers_that_raise() -> None:
    """A subscriber that raises is
    logged and skipped; the next
    subscriber still fires."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    seen: list[str] = []
    def boom(*a, **k) -> None:
        raise RuntimeError("nope")
    h.subscribe("x", boom)
    h.subscribe("x", lambda *a, **k: seen.append("a"))
    # Capture log records to assert
    # the warning was emitted.
    records: list[logging.LogRecord] = []
    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
    handler = _Capture()
    logger = logging.getLogger("manusift.hooks")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        h.dispatch("x", 1, 2)
    finally:
        logger.setLevel(old_level)
        logger.removeHandler(handler)
    # The non-raising subscriber
    # still fired.
    assert seen == ["a"]
    # The warning was logged.
    msgs = [r.getMessage() for r in records]
    assert any("subscriber raised" in m for m in msgs)


def test_unsubscribe_removes_subscriber() -> None:
    """``unsubscribe`` removes the
    function from the hook's
    subscriber list. A subsequent
    dispatch does not call it."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    seen: list[str] = []
    fn = lambda *a, **k: seen.append("a")
    h.subscribe("x", fn)
    h.unsubscribe("x", fn)
    h.dispatch("x")
    assert seen == []


def test_unsubscribe_unknown_is_noop() -> None:
    """``unsubscribe`` for an
    unknown hook name or function
    is a no-op; the registry does
    not raise."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    h.unsubscribe("never-registered", lambda *a, **k: None)


def test_subscribers_returns_snapshot() -> None:
    """``subscribers(name)`` returns a
    snapshot, not the live list.
    A subscriber that
    subscribes/unsubscribes during
    a dispatch does not race the
    iteration."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    a = lambda *a, **k: None
    b = lambda *a, **k: None
    h.subscribe("x", a)
    snap = h.subscribers("x")
    h.subscribe("x", b)
    # The snapshot does not include
    # the new subscriber.
    assert snap == [a]
    assert h.subscribers("x") == [a, b]


def test_dispatch_to_unknown_hook_is_noop() -> None:
    """``dispatch`` to a hook with no
    subscribers is a no-op (not an
    error). The pipeline's
    ``hooks.dispatch("on_step", ...)``
    is safe to call before any
    subscriber has been wired."""
    from manusift.hooks import HookRegistry
    h = HookRegistry()
    # No raise.
    h.dispatch("never-registered", 1, 2, 3)


# ---------- 2. Singleton + reset hook ----------

def test_get_hooks_returns_singleton() -> None:
    """``get_hooks`` returns the
    process-global singleton."""
    from manusift.hooks import get_hooks, reset_hooks
    reset_hooks()
    a = get_hooks()
    b = get_hooks()
    assert a is b


def test_reset_hooks_clears_all_subscribers() -> None:
    """``reset_hooks`` clears every
    subscriber from every hook and
    returns a fresh registry."""
    from manusift.hooks import get_hooks, reset_hooks
    reset_hooks()
    h = get_hooks()
    h.subscribe("a", lambda *a, **k: None)
    h.subscribe("b", lambda *a, **k: None)
    reset_hooks()
    h2 = get_hooks()
    assert h2.subscribers("a") == []
    assert h2.subscribers("b") == []


# ---------- 3. Entry-point discovery ----------

def test_iter_entrypoint_hooks_loads_callables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``iter_entrypoint_hooks`` yields
    ``(name, fn)`` tuples from the
    ``manusift.hooks`` entry-point
    group and auto-registers the
    callables on the global
    registry."""
    from manusift import hooks as hooks_mod
    hooks_mod.reset_hooks()
    seen: list[str] = []

    def my_fn(*args, **kwargs):
        seen.append("plugin-1")

    class _FakeEP:
        def __init__(self, name, target):
            self.name = name
            self.value = f"fake:{name}"
            self._target = target
        def load(self):
            return self._target

    monkeypatch.setattr(
        hooks_mod.metadata, "entry_points",
        lambda *, group: [_FakeEP("on_step", my_fn)],
    )
    out = hooks_mod.iter_entrypoint_hooks()
    assert ("on_step", my_fn) in out
    # Auto-registered on the global
    # registry.
    h = hooks_mod.get_hooks()
    assert my_fn in h.subscribers("on_step")
    # And the dispatch path works.
    h.dispatch("on_step")
    assert "plugin-1" in seen


def test_iter_entrypoint_hooks_accepts_list_of_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin entry point that
    returns a list of ``(name, fn)``
    tuples is supported. Each
    tuple is registered on the
    global registry."""
    from manusift import hooks as hooks_mod
    hooks_mod.reset_hooks()
    received: list[str] = []

    def on_step_fn(*a, **k) -> None:
        received.append("on_step")

    def on_audit_fn(*a, **k) -> None:
        received.append("on_audit")

    class _FakeEP:
        def __init__(self):
            self.name = "multi"
            self.value = "fake:multi"
        def load(self):
            return [
                ("on_step", on_step_fn),
                ("on_audit", on_audit_fn),
            ]

    monkeypatch.setattr(
        hooks_mod.metadata, "entry_points",
        lambda *, group: [_FakeEP()],
    )
    out = hooks_mod.iter_entrypoint_hooks()
    names = [n for n, _ in out]
    assert "on_step" in names
    assert "on_audit" in names
    h = hooks_mod.get_hooks()
    h.dispatch("on_step")
    h.dispatch("on_audit")
    assert "on_step" in received
    assert "on_audit" in received


def test_iter_entrypoint_hooks_handles_invalid_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entry point that does not
    return a callable or a list of
    tuples is logged and skipped."""
    from manusift import hooks as hooks_mod
    hooks_mod.reset_hooks()
    records: list[logging.LogRecord] = []
    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)
    handler = _Capture()
    logger = logging.getLogger("manusift.hooks")
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        class _FakeEP:
            def __init__(self):
                self.name = "bad"
                self.value = "fake:bad"
            def load(self):
                # Returns a string, which
                # is not callable and not
                # a list of tuples.
                return "not-a-callable"
        monkeypatch.setattr(
            hooks_mod.metadata, "entry_points",
            lambda *, group: [_FakeEP()],
        )
        out = hooks_mod.iter_entrypoint_hooks()
    finally:
        logger.setLevel(old_level)
        logger.removeHandler(handler)
    # The bad entry point is
    # skipped — no (name, fn) tuple
    # is yielded.
    assert out == []
    # And the warning was logged.
    msgs = [r.getMessage() for r in records]
    assert any("did not return" in m for m in msgs)
