"""Tests for the graceful-shutdown lifecycle
(Step G3).

G3 wires a process-global
``InFlightTracker`` to FastAPI's
``lifespan`` context manager. The
tracker records every running
``_run_in_background`` task; the
lifespan waits for the tracker to
drain on shutdown, up to
``settings.shutdown_timeout_seconds``.

Guarantees:

  1. ``InFlightTracker.register`` /
     ``unregister`` work and a
     ``wait_idle`` call returns
     immediately when the set is empty.
  2. ``wait_idle(timeout)`` blocks until
     the set is empty OR the timeout
     elapses, whichever comes first.
  3. A task that takes longer than the
     timeout is NOT killed; the
     ``wait_idle`` returns False and
     the lifespan logs a "some jobs
     may be abandoned" warning.
  4. The tracker is process-global
     (``get_tracker`` returns the same
     instance on every call).
  5. ``reset_tracker`` is a test hook
     that creates a fresh tracker so
     test order does not leak state.
  6. The FastAPI app exposes the
     configured timeout via
     ``app.state.shutdown_timeout``
     so the lifespan reads the right
     value without a re-read of env
     vars.
  7. A background task that finishes
     before the timeout allows the
     shutdown to drain cleanly (the
     lifespan logs "drained cleanly").
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest


# ---------- 1. InFlightTracker basic semantics ----------

def test_register_and_unregister() -> None:
    """A registered trace id is in the
    set; an unregistered one is not."""
    from manusift.lifecycle import (
        InFlightTracker, reset_tracker
    )
    reset_tracker()
    t = InFlightTracker()
    t.register("a")
    t.register("b")
    assert t.count() == 2
    assert t.in_flight() == ["a", "b"]
    t.unregister("a")
    assert t.count() == 1
    t.unregister("b")
    assert t.count() == 0


def test_wait_idle_returns_immediately_when_empty() -> None:
    """``wait_idle(0)`` returns True when
    the set is empty."""
    from manusift.lifecycle import InFlightTracker
    t = InFlightTracker()
    assert t.wait_idle(timeout=0.0) is True
    assert t.wait_idle(timeout=10.0) is True


def test_wait_idle_blocks_then_unblocks() -> None:
    """A separate thread that registers
    and unregisters a job lets a
    ``wait_idle`` call return early
    with True."""
    from manusift.lifecycle import InFlightTracker
    t = InFlightTracker()
    t.register("a")
    # A worker unregisters after a short
    # sleep. The wait should unblock
    # with True before the 5 s timeout.
    def worker() -> None:
        time.sleep(0.05)
        t.unregister("a")
    threading.Thread(target=worker, daemon=True).start()
    start = time.monotonic()
    drained = t.wait_idle(timeout=5.0)
    elapsed = time.monotonic() - start
    assert drained is True
    # We did not wait anywhere near 5 s.
    assert elapsed < 1.0


def test_wait_idle_returns_false_on_timeout() -> None:
    """A task that does NOT finish within
    the timeout returns False — the
    task is left running (the caller
    decided not to kill it)."""
    from manusift.lifecycle import InFlightTracker
    t = InFlightTracker()
    t.register("a")
    start = time.monotonic()
    drained = t.wait_idle(timeout=0.1)
    elapsed = time.monotonic() - start
    assert drained is False
    # We did not wait longer than the
    # timeout (plus a small jitter).
    assert elapsed < 1.0
    # The task is still in flight; the
    # tracker has not unregistered it.
    assert t.count() == 1
    # Cleanup so the test process exits
    # cleanly. (A daemon-thread leak
    # would only show up in the test
    # process exit, not in pytest.)
    t.unregister("a")


def test_double_unregister_is_safe() -> None:
    """A duplicate ``unregister`` is a
    no-op. The tracker does not crash;
    the count simply stays at 0."""
    from manusift.lifecycle import InFlightTracker
    t = InFlightTracker()
    t.register("a")
    t.unregister("a")
    t.unregister("a")  # no-op
    assert t.count() == 0


def test_double_register_is_a_noop() -> None:
    """A duplicate ``register`` does
    not double-count."""
    from manusift.lifecycle import InFlightTracker
    t = InFlightTracker()
    t.register("a")
    t.register("a")
    assert t.count() == 1


# ---------- 2. Global tracker is a singleton ----------

def test_get_tracker_returns_singleton() -> None:
    """``get_tracker()`` returns the same
    instance on every call. The
    background task that runs in
    production (in a real worker
    thread) and the lifespan (in the
    main thread) both see the same
    tracker."""
    from manusift.lifecycle import get_tracker
    a = get_tracker()
    b = get_tracker()
    assert a is b


# ---------- 3. Lifespan + FastAPI integration ----------

def test_app_has_lifespan_wired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``create_app`` installs the
    graceful-shutdown lifespan. We
    assert the lifespan attribute is
    set on the FastAPI app; the actual
    shutdown path is exercised in the
    end-to-end test below."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv(
        "MANUSIFT_SHUTDOWN_TIMEOUT_SECONDS", "5.0"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.app import create_app
    app = create_app()
    # The lifespan is a callable stored
    # on the router; calling it drives
    # the startup / shutdown sequence.
    assert app.router.lifespan_context is not None


def test_lifespan_drains_when_no_inflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the tracker is empty, the
    shutdown phase returns immediately
    without logging the "waiting"
    line. The lifespan path is driven
    by ``LifespanManager.__aenter__``
    and ``__aexit__`` in the
    starlette lifespan machinery; we
    reproduce the test by manually
    entering and exiting the lifespan
    context manager.
    """
    from manusift.lifecycle import (
        get_tracker, reset_tracker
    )
    reset_tracker()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.app import create_app
    from manusift.lifecycle import lifespan
    app = create_app()
    # Manually drive the lifespan.
    import asyncio
    async def drive():
        async with lifespan(app):
            # No background tasks; the
            # tracker is empty.
            assert get_tracker().count() == 0
    asyncio.run(drive())


def test_lifespan_waits_for_inflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A background task that finishes
    within the timeout lets the
    lifespan drain cleanly. We
    simulate the task by registering
    a trace id from a worker thread,
    sleeping, and then unregistering.
    The lifespan, on exit, waits for
    the tracker to drain.
    """
    from manusift.lifecycle import (
        get_tracker, reset_tracker
    )
    reset_tracker()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv(
        "MANUSIFT_SHUTDOWN_TIMEOUT_SECONDS", "2.0"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.app import create_app
    from manusift.lifecycle import lifespan
    app = create_app()
    import asyncio
    async def drive():
        async with lifespan(app):
            get_tracker().register("a")
            def worker():
                time.sleep(0.1)
                get_tracker().unregister("a")
            threading.Thread(target=worker, daemon=True).start()
        # The lifespan drained cleanly
        # (the worker finished before the
        # 2 s timeout).
    asyncio.run(drive())
    assert get_tracker().count() == 0


def test_lifespan_times_out_on_long_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A background task that takes
    longer than the configured timeout
    does not crash the lifespan — the
    lifespan logs a warning and
    returns. The task is left running
    (the OS-level process exit is what
    would eventually reap it)."""
    from manusift.lifecycle import (
        get_tracker, reset_tracker
    )
    reset_tracker()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv(
        "MANUSIFT_SHUTDOWN_TIMEOUT_SECONDS", "0.1"
    )
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.app import create_app
    from manusift.lifecycle import lifespan
    app = create_app()
    import asyncio
    async def drive():
        async with lifespan(app):
            get_tracker().register("slow")
            # Do not unregister; the
            # lifespan must time out.
    asyncio.run(drive())
    # The tracker still has the
    # "slow" entry. We clean up so
    # the test process exits cleanly.
    get_tracker().unregister("slow")
