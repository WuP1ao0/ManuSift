"""R-2026-06-20 (CDE-UI-P0.7):
regression test for
the error /
warn status
coloring.

The clig.dev
principle:
"Quiet but
precise" -- an
error message
should be
visually
distinct from a
normal status
message.

Before P0.7,
``_set_status``
only set
gray text
($mocha-subtext)
on both "ready"
and "agent
crashed".
After P0.7,
``_set_status``
takes a
``level``
kwarg
("info" /
"warn" /
"error") and
the #tool-status
widget gets a
CSS class
(.status-warn
yellow bold /
.status-error
red bold /
.status-info
gray).
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


def _set_status_and_get_classes(
    app: ChatApp, text: str, level: str
) -> set[str]:
    app._set_status(text, level=level)
    widget = app.query_one("#tool-status")
    return set(widget.classes or [])


@pytest.mark.asyncio
async def test_status_info_class() -> None:
    """``_set_status("hi", level="info")`` adds
    ``status-info`` (gray, default).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        classes = _set_status_and_get_classes(
            app, "ready", level="info"
        )
        assert "status-info" in classes, (
            f"expected status-info class; got {classes!r}"
        )


@pytest.mark.asyncio
async def test_status_warn_class() -> None:
    """``_set_status("oops", level="warn")`` adds
    ``status-warn`` (yellow, bold).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        classes = _set_status_and_get_classes(
            app, "aborted", level="warn"
        )
        assert "status-warn" in classes, (
            f"expected status-warn class; got {classes!r}"
        )
        # ``status-info``
        # must be
        # removed
        # when we
        # switch
        # levels
        # (single class
        # at a time).
        assert "status-info" not in classes


@pytest.mark.asyncio
async def test_status_error_class() -> None:
    """``_set_status("crashed", level="error")``
    adds ``status-error`` (red, bold).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        classes = _set_status_and_get_classes(
            app, "agent crashed", level="error"
        )
        assert "status-error" in classes, (
            f"expected status-error class; got {classes!r}"
        )
        assert "status-info" not in classes
        assert "status-warn" not in classes


@pytest.mark.asyncio
async def test_action_abort_uses_warn_level() -> None:
    """The Ctrl+C / Esc action_abort path
    must mark the status as warn (not info)
    so the user sees the abort visually.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        # The actual abort path -- call it.
        app.action_abort()
        await pilot.pause(0.05)
        classes = set(app.query_one("#tool-status").classes or [])
        assert "status-warn" in classes, (
            f"action_abort should mark status as warn; "
            f"got classes={classes!r}"
        )


@pytest.mark.asyncio
async def test_status_class_swapping() -> None:
    """Successive ``_set_status`` calls with
    different levels must swap the CSS
    class (no accumulation).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        _set_status_and_get_classes(app, "1", level="info")
        _set_status_and_get_classes(app, "2", level="error")
        _set_status_and_get_classes(app, "3", level="warn")
        classes = set(app.query_one("#tool-status").classes or [])
        assert "status-warn" in classes
        # info and error
        # must NOT
        # both be
        # present --
        # exactly
        # one level
        # at a time.
        status_classes = {
            c for c in classes
            if c in ("status-info", "status-warn", "status-error")
        }
        assert len(status_classes) == 1, (
            f"expected exactly one status class; "
            f"got {status_classes!r}"
        )