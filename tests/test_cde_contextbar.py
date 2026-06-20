"""R-2026-06-20 (CDE-UI-P1.5):
regression test for
the ContextBar.

The TUI's
``App.sub_title``
is the single-line
header at the
top showing all
the session
state. Before
P1.5 it had only
``session`` /
``llm`` / ``pdf``.
After P1.5 it
also has:
- ``pdf=basename``
  (full path was
  too long for
  one line)
- ``plan=on(N)``
  in cyan when
  plan mode is on
- ``cost=$X/$Y``
  in green /
  yellow / red
  based on usage
  fraction

This test
asserts each
section.
"""
from __future__ import annotations

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


@pytest.mark.asyncio
async def test_contextbar_shows_session_id() -> None:
    """``sub_title`` contains the
    session id so the user knows
    which chat they are in.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        assert app._session_id in app.sub_title, (
            f"expected session id {app._session_id!r} "
            f"in sub_title {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_shows_llm_name() -> None:
    """``sub_title`` contains the LLM
    name (lowercase) so the user
    knows which model is active.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        assert "llm=mockllm" in app.sub_title, (
            f"expected 'llm=mockllm' in sub_title; "
            f"got {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_pdf_no_pdf_placeholder() -> None:
    """When no PDF is uploaded,
    ``sub_title`` shows the
    ``pdf=(no pdf loaded)``
    placeholder so the user
    knows they need to upload.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        assert "pdf=(no pdf loaded)" in app.sub_title, (
            f"expected no-PDF placeholder in sub_title; "
            f"got {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_plan_mode_shows_indicator() -> None:
    """When plan mode is on, the
    ``sub_title`` contains a
    ``plan=on(N)`` indicator in
    cyan (Rich markup). N is the
    pending-input queue length.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        app._cmd_plan("on")
        await pilot.pause(0.05)
        assert "[cyan]plan=on(0)[/cyan]" in app.sub_title, (
            f"expected plan=on(0) in cyan in sub_title; "
            f"got {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_plan_mode_count_increases() -> None:
    """Submitting a message while in
    plan mode increments the
    ``plan=on(N)`` count so the
    user sees queue size at a
    glance.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        app._cmd_plan("on")
        await pilot.pause(0.05)
        app._submit_user_message("step 1")
        await pilot.pause(0.05)
        assert "[cyan]plan=on(1)[/cyan]" in app.sub_title, (
            f"expected plan=on(1) in cyan after 1 queue; "
            f"got {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_no_plan_indicator_when_off() -> None:
    """When plan mode is off
    (the default), the
    ``sub_title`` must NOT
    contain a plan
    indicator (otherwise
    the user thinks plan
    is on).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        assert "plan=" not in app.sub_title, (
            f"sub_title must NOT contain plan= when "
            f"plan mode is off; got {app.sub_title!r}"
        )


@pytest.mark.asyncio
async def test_contextbar_cost_part_is_present() -> None:
    """The ``cost=...`` section is
    always present so the user
    can see spending. Format:
    ``cost=$X.XXX`` when no cap
    is set, or ``cost=[color]$X/$Y[/color]``
    when a cap is set.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.1)
        assert "cost=" in app.sub_title, (
            f"expected 'cost=' section in sub_title; "
            f"got {app.sub_title!r}"
        )