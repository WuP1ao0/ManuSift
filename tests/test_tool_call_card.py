"""R-2026-06-16 (Phase 4 +
tool-call-card):
the new
``ToolCallCard``
widget is
mounted in the
chat scrollback
on every tool /
detector call.
It is the
Claude-Code-style
persistent
action block
the user asked for.

These tests verify:

  * the
    card
    renders
    the
    header
    line
    (tool
    name,
    timestamp,
    status
    icon,
    status
    word,
    duration)
  * the
    body
    shows
    raw_input
    args
    (key:
    value
    lines)
  * the
    body
    shows
    output
    fields
    that
    are
    NOT
    already
    in
    raw_input
    (dedup)
  * error
    /
    skipped
    entries
    show
    the
    error
    message
    in
    a
    contrasting
    color
  * CSS
    classes
    reflect
    status
  * set_entry()
    updates
    the
    same
    widget
    in
    place
    (no
    duplicate
    card)

We use the
``_build()`` method
directly to avoid
Textual's async
render-lifecycle
quirks
(``card.render()``
returns the
default empty
``Static`` content
before the first
paint cycle has
fired)."""

import asyncio
import json
import time

import pytest

# The tests can run on any platform; the
# ``run_test`` pilot only requires a textual
# TTY-less environment which the
# ``MANUSIFT_SKIP_TUI_TESTS=1`` env-guard
# does NOT apply to (we use ``run_test``
# in-process).


@pytest.fixture
def setup_pilot():
    """Spin up a ``ChatApp`` inside ``run_test`` so
    ``#history`` and the CSS tree are
    alive."""

    async def _factory():
        from manusift.tui.chat_app import ChatApp
        from textual.containers import VerticalScroll
        app = ChatApp()
        async with app.run_test() as pilot:
            history = app.query_one(
                "#history", VerticalScroll
            )
            yield app, pilot, history
            # Teardown:
            # remove all
            # the cards
            # we may
            # have
            # mounted
            # during
            # the test
            for child in list(history.children):
                if child.__class__.__name__ in (
                    "ToolCallCard",
                ):
                    child.remove()
    return _factory


def test_card_header_line_shows_tool_name_and_status(
    setup_pilot,
):
    """Header
    must
    read
    ``● <name>  ✓ <status>  (Xms)``
    so the
    user
    sees
    the
    call
    at
    a
    glance."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e = ToolEntry(
                tool_id="t1",
                tool_name="image_dup",
                status=TOOL_OK,
                duration_ms=310,
                summary="",
                raw_input={},
                raw_output="",
                error="",
            )
            card = ToolCallCard(
                e, id="tcc-1"
            )
            history.mount(card)
            await pilot.pause(0.1)
            txt = card._build().plain
            assert "image_dup" in txt
            assert "ok" in txt
            assert "310ms" in txt
            assert "●" in txt
    asyncio.run(driver())


def test_card_body_shows_raw_input_key_value_lines(
    setup_pilot,
):
    """Body
    must
    show
    one
    ``key:
    value``
    line
    per
    raw_input
    arg."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e = ToolEntry(
                tool_id="t2",
                tool_name="read_file",
                status=TOOL_OK,
                duration_ms=12,
                summary="",
                raw_input={
                    "path": r"C:\foo\Table_S1.xlsx",
                },
                raw_output="",
                error="",
            )
            card = ToolCallCard(
                e, id="tcc-2"
            )
            history.mount(card)
            await pilot.pause(0.1)
            txt = card._build().plain
            assert "path:" in txt
            assert "Table_S1.xlsx" in txt
    asyncio.run(driver())


def test_card_dedups_path_already_in_raw_input(
    setup_pilot,
):
    """If
    ``path``
    is
    in
    both
    raw_input
    AND
    raw_output,
    the
    card
    must
    show
    it
    ONCE
    (not
    twice).
    Otherwise
    the
    chat
    scrollback
    becomes
    a
    duplicate
    echo."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e = ToolEntry(
                tool_id="t3",
                tool_name="read_file",
                status=TOOL_OK,
                duration_ms=12,
                summary="5 rows x 8 cols",
                raw_input={
                    "path": r"C:\foo\Table.xlsx",
                },
                raw_output=json.dumps(
                    {
                        "ok": True,
                        "row_count": 5,
                        "path": (
                            r"C:\foo\Table.xlsx"
                        ),
                    }
                ),
                error="",
            )
            card = ToolCallCard(
                e, id="tcc-3"
            )
            history.mount(card)
            await pilot.pause(0.1)
            txt = card._build().plain
            # ``path:`` should
            # appear
            # exactly
            # ONCE
            # (not
            # twice).
            assert txt.count("path:") == 1, (
                f"expected 1 'path:' line, "
                f"got {txt.count('path:')}; "
                f"full text:\n{txt}"
            )
            # The
            # value
            # should
            # still
            # be
            # rendered.
            assert "Table.xlsx" in txt
    asyncio.run(driver())


def test_card_shows_output_fields_not_in_raw_input(
    setup_pilot,
):
    """If
    raw_output
    has
    a
    key
    that
    raw_input
    does
    NOT
    have
    (e.g.
    ``row_count``),
    the
    card
    must
    show
    it
    as
    a
    new
    line."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e = ToolEntry(
                tool_id="t4",
                tool_name="read_file",
                status=TOOL_OK,
                duration_ms=12,
                summary="",
                raw_input={
                    "path": r"C:\foo\Table.xlsx",
                },
                raw_output=json.dumps(
                    {
                        "ok": True,
                        "row_count": 42,
                        "column_count": 7,
                    }
                ),
                error="",
            )
            card = ToolCallCard(
                e, id="tcc-4"
            )
            history.mount(card)
            await pilot.pause(0.1)
            txt = card._build().plain
            assert "row_count" in txt
            assert "42" in txt
            assert "column_count" in txt
            assert "7" in txt
    asyncio.run(driver())


def test_card_error_status_shows_error_message(
    setup_pilot,
):
    """Error
    entries
    must
    show
    the
    error
    text
    so
    the
    user
    can
    see
    WHY
    a
    call
    failed."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e = ToolEntry(
                tool_id="t5",
                tool_name="bash",
                status="error",
                duration_ms=2400,
                summary="exit 1",
                raw_input={
                    "command": "python --version",
                },
                raw_output=json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "Python not found"
                        ),
                    }
                ),
                error="Python not found",
            )
            card = ToolCallCard(
                e, id="tcc-5"
            )
            history.mount(card)
            await pilot.pause(0.1)
            txt = card._build().plain
            assert "error" in txt
            assert "Python not found" in txt
            assert "command:" in txt
            assert "2.4s" in txt
    asyncio.run(driver())


def test_card_set_entry_updates_in_place(
    setup_pilot,
):
    """``set_entry()``
    should
    update
    the
    *same*
    card
    (no
    duplicate
    card
    mounts).
    This
    is
    the
    critical
    property
    that
    prevents
    the
    chat
    scrollback
    from
    doubling
    every
    call."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK, TOOL_RUNNING,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            e_run = ToolEntry(
                tool_id="t6",
                tool_name="image_dup",
                status=TOOL_RUNNING,
                duration_ms=None,
                summary="",
                raw_input={},
                raw_output="",
                error="",
            )
            card = ToolCallCard(
                e_run, id="tcc-6"
            )
            history.mount(card)
            await pilot.pause(0.1)
            # Check
            # running
            # state
            assert "tool-call-card-running" in card.classes
            # Update
            # to
            # ok
            e_ok = ToolEntry(
                tool_id="t6",
                tool_name="image_dup",
                status=TOOL_OK,
                duration_ms=310,
                summary="no high-risk duplicate",
                raw_input={},
                raw_output="",
                error="",
            )
            card.set_entry(e_ok)
            await pilot.pause(0.1)
            # No
            # duplicate
            # card
            # should
            # exist
            cards = [
                c
                for c in history.children
                if c.__class__.__name__
                == "ToolCallCard"
                and c.id == "tcc-6"
            ]
            assert len(cards) == 1
            assert "tool-call-card-ok" in card.classes
            assert "tool-call-card-running" not in card.classes
            txt = card._build().plain
            assert "310ms" in txt
            assert "no high-risk duplicate" in txt
    asyncio.run(driver())


def test_card_status_css_class_reflects_state(
    setup_pilot,
):
    """The
    CSS
    class
    must
    follow
    the
    state
    so
    the
    left
    border
    color
    changes
    from
    amber
    (running)
    to
    green
    (ok)
    /
    amber
    (skipped)
    /
    red
    (error)."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK, TOOL_RUNNING,
    )
    async def driver():
        async for app, pilot, history in setup_pilot():
            # running
            e1 = ToolEntry(
                tool_id="a", tool_name="x",
                status=TOOL_RUNNING, duration_ms=None,
                summary="", raw_input={}, raw_output="", error="",
            )
            c1 = ToolCallCard(e1, id="tcc-r")
            history.mount(c1)
            await pilot.pause(0.1)
            assert "tool-call-card-running" in c1.classes
            # ok
            c1.set_entry(
                ToolEntry(
                    tool_id="a", tool_name="x",
                    status=TOOL_OK, duration_ms=10,
                    summary="", raw_input={},
                    raw_output="", error="",
                )
            )
            assert "tool-call-card-ok" in c1.classes
            assert (
                "tool-call-card-running" not in c1.classes
            )
            # error
            c1.set_entry(
                ToolEntry(
                    tool_id="a", tool_name="x",
                    status="error", duration_ms=10,
                    summary="", raw_input={},
                    raw_output="", error="boom",
                )
            )
            assert "tool-call-card-error" in c1.classes
            # skipped
            c1.set_entry(
                ToolEntry(
                    tool_id="a", tool_name="x",
                    status="skipped", duration_ms=10,
                    summary="", raw_input={},
                    raw_output="", error="nope",
                )
            )
            assert "tool-call-card-skipped" in c1.classes
    asyncio.run(driver())


def test_card_format_duration_ms_and_seconds():
    """Duration
    formatting:
    sub-second
    =
    ``45ms``,
    multi-second
    =
    ``2.4s``."""
    from manusift.tui.turn_block import _fmt_duration
    assert _fmt_duration(45) == "45ms"
    assert _fmt_duration(999) == "999ms"
    assert _fmt_duration(1000) == "1.0s"
    assert _fmt_duration(1500) == "1.5s"
    assert _fmt_duration(2400) == "2.4s"
    assert _fmt_duration(45000) == "45.0s"


def test_card_render_value_shortens_paths():
    """The
    value
    formatter
    must
    shorten
    Windows
    /
    POSIX
    absolute
    paths
    to
    ``.../<basename>``."""
    from manusift.tui.turn_block import _render_value
    s = _render_value(
        r"C:\Users\foo\data\Table_S1.xlsx"
    )
    assert s.startswith("...")
    assert s.endswith("Table_S1.xlsx")
    s = _render_value("/home/user/data/file.csv")
    assert s.startswith("...")
    assert s.endswith("file.csv")
    # non-path strings pass through
    assert _render_value("hello") == "hello"
    assert _render_value(42) == "42"
    assert _render_value(True) == "true"
    assert _render_value(None) == ""


def test_card_time_format_from_unix_timestamp():
    """The
    timestamp
    in
    the
    header
    is
    rendered
    as
    ``HH:MM:SS``
    from
    the
    ``_started_at``
    key
    in
    raw_input."""
    from manusift.tui.turn_block import (
        ToolCallCard, ToolEntry, TOOL_OK,
    )
    # 2026-06-16 14:35:00 UTC
    ts = time.mktime(
        (2026, 6, 16, 14, 35, 0, 0, 0, 0)
    )
    e = ToolEntry(
        tool_id="t", tool_name="x",
        status=TOOL_OK, duration_ms=10,
        summary="", raw_input={"_started_at": ts},
        raw_output="", error="",
    )
    c = ToolCallCard(e, id="tcc-t")
    # We need to mount for render to work; use a
    # throwaway test app:
    async def driver():
        from manusift.tui.chat_app import ChatApp
        from textual.containers import VerticalScroll
        app = ChatApp()
        async with app.run_test() as pilot:
            history = app.query_one(
                "#history", VerticalScroll
            )
            history.mount(c)
            await pilot.pause(0.1)
            t = c._format_time()
            # local-time HH:MM:SS, so just check
            # ``14:35``
            assert "14:35" in t
    asyncio.run(driver())
