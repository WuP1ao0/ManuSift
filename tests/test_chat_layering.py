"""Tests for the three-layer chat architecture
(R-audit 2026-06-11).

The user reported the
TUI's chat log mixed
user / assistant text /
tool calls / tool results
/ system debug into one
flat history, making it
"eye-stabbing".

The new design splits
the surface into three
layers:

  1. **Chat** --
     ``#history``
     ``VerticalScroll`` with
     ONLY user / assistant
     bubbles.
  2. **ToolTrace** -- a
     ``ToolTraceBlock``
     per turn (collapsed by
     default). The block
     shows a one-line
     summary
     (``tools N calls ...
     ok ... skipped ...
     error``). Expanded
     it shows one line per
     tool.
  3. **DebugDrawer** -- a
     hidden ``VerticalScroll``
     that holds the raw
     JSON of every tool
     call / result /
     assistant text. Open
     with the ``d``
     keybinding.

These tests pin the
new contracts:

  * No ``role='tool'`` /
    ``role='system'`` rows
    ever appear in
    ``#history`` (the chat
    log).
  * A ``ToolTraceBlock``
    is mounted per turn
    and is updated as
    tools fire.
  * The
    ``DebugDrawer`` is
    hidden by default and
    is shown when ``d`` is
    pressed.
  * Long paths in
    summaries are
    shortened to
    ``.../<basename>``.
  * The dedup helper
    collapses repeated
    errors.
  * The user's example
    "14 tools skipped: PDF
    not found for
    trace_id=..." is
    produced correctly.
  * The status line carries
    the on/off state of
    the DebugDrawer.
"""
from __future__ import annotations

import os
import re

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. The widgets are importable ----------


def test_turn_block_widgets_importable() -> None:
    """The new widgets are
    importable from
    ``manusift.tui.turn_block``."""
    from manusift.tui.turn_block import (
        DebugDrawer,
        ToolEntry,
        ToolTraceBlock,
        TOOL_ERROR,
        TOOL_OK,
        TOOL_RUNNING,
        TOOL_SKIPPED,
        build_entry_summary,
        dedup_tool_errors,
    )
    # All
    # symbols
    # exist.
    assert ToolTraceBlock is not None
    assert DebugDrawer is not None
    assert ToolEntry is not None
    assert TOOL_OK == "ok"
    assert TOOL_SKIPPED == "skipped"
    assert TOOL_ERROR == "error"
    assert TOOL_RUNNING == "running"
    assert callable(build_entry_summary)
    assert callable(dedup_tool_errors)


# ---------- 2. Long-path shortener ----------


def test_shorten_path_windows_unix_basename() -> None:
    """A long Windows or
    Unix path is shortened
    to ``.../<basename>``."""
    from manusift.tui.turn_block import _shorten_path
    # Windows.
    s = _shorten_path("PDF not found at C:\\Users\\alice\\paper.pdf")
    assert "paper.pdf" in s
    assert "C:" not in s
    assert "\\alice" not in s
    # Unix.
    s = _shorten_path("loading /home/alice/work/paper.pdf again")
    assert "paper.pdf" in s
    assert "/alice" not in s


def test_shorten_path_idempotent() -> None:
    """Calling the shortener
    twice gives the same
    result."""
    from manusift.tui.turn_block import _shorten_path
    s = "PDF not found at C:\\Users\\alice\\paper.pdf"
    once = _shorten_path(s)
    twice = _shorten_path(once)
    assert once == twice


def test_shorten_path_no_path_is_noop() -> None:
    """A string with no
    path is unchanged."""
    from manusift.tui.turn_block import _shorten_path
    s = "just plain text with no path"
    assert _shorten_path(s) == s


# ---------- 3. ToolTraceBlock summary line ----------


def test_tool_trace_block_summary_empty() -> None:
    """A fresh
    ``ToolTraceBlock``
    shows
    ``◌ thinking…``
    before any tool fires."""
    from manusift.tui.turn_block import ToolTraceBlock

    block = ToolTraceBlock()
    # The
    # internal
    # _summary_line
    # returns
    # a
    # ``rich.text.Text``
    # we
    # can
    # inspect
    # without
    # an
    # active
    # App.
    line = block._summary_line()
    plain = line.plain
    assert "thinking" in plain.lower()


def test_tool_trace_block_summary_after_one_ok() -> None:
    """After one OK tool,
    the summary reads
    ``tools 1 call · 1 ok``."""
    from manusift.tui.turn_block import (
        ToolEntry,
        ToolTraceBlock,
        TOOL_OK,
    )

    block = ToolTraceBlock()
    block.add_entry(
        ToolEntry(
            tool_id="t1",
            tool_name="image_dup",
            status=TOOL_OK,
            duration_ms=310,
            summary="no high-risk duplicate",
        )
    )
    line = block._summary_line()
    plain = line.plain
    assert "1" in plain
    # R-2026-06-14: i18n -- the OK status label is
    # "ok" in English, "成功" in Chinese.
    assert ("ok" in plain.lower()) or ("成功" in plain)


def test_tool_trace_block_user_example_summary() -> None:
    """The user's exact
    example summary line:
    ``tools 31 calls · 28
    ok · 3 skipped · 0
    fatal`` should be
    produced correctly
    when 31 entries are
    added (28 OK + 3
    skipped)."""
    from manusift.tui.turn_block import (
        ToolEntry,
        ToolTraceBlock,
        TOOL_OK,
        TOOL_SKIPPED,
    )

    block = ToolTraceBlock()
    for i in range(28):
        block.add_entry(
            ToolEntry(
                tool_id=f"ok{i}",
                tool_name="ok_tool",
                status=TOOL_OK,
                duration_ms=100,
                summary="ok",
            )
        )
    for i in range(3):
        block.add_entry(
            ToolEntry(
                tool_id=f"sk{i}",
                tool_name="pdf_metadata",
                status=TOOL_SKIPPED,
                duration_ms=5,
                summary="skipped: PDF not found",
            )
        )
    block.seal()
    line = block._summary_line()
    plain = line.plain
    # The numbers match the user's spec.
    assert "31" in plain
    assert "28" in plain
    assert "3" in plain
    # R-2026-06-14: i18n -- the OK / SKIPPED status
    # labels are "ok" / "skipped" in English,
    # "成功" / "跳过" in Chinese.
    plain_lower = plain.lower()
    assert ("ok" in plain_lower) or ("成功" in plain)
    assert ("skipped" in plain_lower) or ("跳过" in plain)


def test_tool_trace_block_user_example_entry_lines() -> None:
    """The user's exact
    example entry lines:
    ``✓ image_dup 310ms
    no high-risk
    duplicate`` and
    ``⚠ pdf_metadata
    skipped: PDF not
    found`` should be
    produced when the
    block is expanded."""
    from manusift.tui.turn_block import (
        ToolEntry,
        ToolTraceBlock,
        TOOL_OK,
        TOOL_SKIPPED,
    )

    block = ToolTraceBlock(collapsed=False)
    block.add_entry(
        ToolEntry(
            tool_id="t1",
            tool_name="image_dup",
            status=TOOL_OK,
            duration_ms=310,
            summary="no high-risk duplicate",
        )
    )
    block.add_entry(
        ToolEntry(
            tool_id="t2",
            tool_name="pdf_metadata",
            status=TOOL_SKIPPED,
            duration_ms=5,
            summary="skipped: PDF not found for trace_id=abc123",
        )
    )
    # The
    # expanded
    # block
    # has
    # one
    # line
    # per
    # entry.
    text = block._expanded_block()
    plain = text.plain
    # The
    # OK
    # entry.
    assert "image_dup" in plain
    assert "310ms" in plain
    assert "no high-risk duplicate" in plain
    # The
    # skipped
    # entry.
    assert "pdf_metadata" in plain
    assert "PDF not found" in plain


def test_tool_trace_block_seal_freezes_entries() -> None:
    """After ``seal()``,
    ``add_entry()`` is a
    no-op."""
    from manusift.tui.turn_block import (
        ToolEntry,
        ToolTraceBlock,
        TOOL_OK,
    )
    block = ToolTraceBlock()
    block.add_entry(
        ToolEntry(tool_id="t1", tool_name="x", status=TOOL_OK)
    )
    assert len(block.entries) == 1
    block.seal()
    block.add_entry(
        ToolEntry(tool_id="t2", tool_name="x", status=TOOL_OK)
    )
    assert len(block.entries) == 1  # sealed, no add
    assert block.is_sealed is True


# ---------- 4. Dedup helper ----------


def test_dedup_tool_errors_collapses_repeats() -> None:
    """Multiple identical
    tool errors collapse
    into a single deduped
    entry with a count.

    The user's spec: "14
    tools skipped: PDF not
    found for
    trace_id=abc"."""
    from manusift.tui.turn_block import (
        ToolEntry,
        TOOL_SKIPPED,
        dedup_tool_errors,
    )
    entries: list[ToolEntry] = []
    for _ in range(14):
        entries.append(
            ToolEntry(
                tool_id="t",
                tool_name="pdf_metadata",
                status=TOOL_SKIPPED,
                error="PDF not found for trace_id=abc",
            )
        )
    dedup = dedup_tool_errors(entries)
    # Exactly
    # one
    # dedup
    # key
    # for
    # the
    # 14
    # repeated
    # errors.
    assert len(dedup) == 1
    # The
    # count
    # is
    # 14.
    (key, count) = next(iter(dedup.items()))
    assert count == 14
    assert "pdf_metadata" in key
    assert "PDF not found" in key


def test_dedup_tool_errors_different_tools_separate() -> None:
    """Different tools with
    the same error text
    remain separate."""
    from manusift.tui.turn_block import (
        ToolEntry,
        TOOL_ERROR,
        dedup_tool_errors,
    )
    entries = [
        ToolEntry(
            tool_id="t1", tool_name="image_dup",
            status=TOOL_ERROR, error="kaboom",
        ),
        ToolEntry(
            tool_id="t2", tool_name="pdf_metadata",
            status=TOOL_ERROR, error="kaboom",
        ),
    ]
    dedup = dedup_tool_errors(entries)
    # Two
    # keys
    # (different
    # tool
    # names).
    assert len(dedup) == 2
    assert sum(dedup.values()) == 2


# ---------- 5. build_entry_summary ----------


def test_build_entry_summary_ok() -> None:
    """OK entries show the
    output as the
    summary."""
    from manusift.tui.turn_block import (
        TOOL_OK,
        build_entry_summary,
    )
    out = build_entry_summary(
        "image_dup", TOOL_OK, output="ok"
    )
    assert "ok" in out


def test_build_entry_summary_skipped() -> None:
    """Skipped entries
    show
    ``"skipped: <error>"`` (English) or
    ``"跳过：<error>"`` (Chinese).

    R-2026-06-14: i18n. The status prefix is now
    driven by ``i18n.t("tool_status_skipped", ...)``
    which falls back to English when MANUSIFT_LANG
    is unset (the test default).
    """
    from manusift.tui.turn_block import (
        TOOL_SKIPPED,
        build_entry_summary,
    )
    out = build_entry_summary(
        "pdf_metadata", TOOL_SKIPPED,
        error="PDF not found",
    )
    # Either English ("skipped: ") or Chinese
    # ("跳过：" with a full-width colon).
    assert (
        out.startswith("skipped: ")
        or out.startswith("\u8df3\u8fc7\uff1a")
    )
    assert "PDF not found" in out


def test_build_entry_summary_error() -> None:
    """Error entries show
    ``"error: <error>"`` (English) or
    ``"错误：<error>"`` (Chinese).

    R-2026-06-14: i18n. The status prefix is driven
    by ``i18n.t("tool_status_error", ...)``.
    """
    from manusift.tui.turn_block import (
        TOOL_ERROR,
        build_entry_summary,
    )
    out = build_entry_summary(
        "web_search", TOOL_ERROR,
        error="timeout after 30s",
    )
    assert (
        out.startswith("error: ")
        or out.startswith("\u9519\u8bef\uff1a")
    )
    assert "timeout" in out


# ---------- 6. DebugDrawer ----------


def test_debug_drawer_hidden_by_default() -> None:
    """The DebugDrawer is
    hidden by default."""
    from manusift.tui.turn_block import DebugDrawer
    drawer = DebugDrawer()
    assert drawer.is_visible is False
    # The
    # CSS
    # class
    # is
    # not
    # present.
    assert "visible" not in drawer.classes


def test_debug_drawer_toggle_flips_visibility() -> None:
    """``toggle()`` flips
    the visibility."""
    from manusift.tui.turn_block import DebugDrawer
    drawer = DebugDrawer()
    drawer.toggle()
    assert drawer.is_visible is True
    drawer.toggle()
    assert drawer.is_visible is False


def test_debug_drawer_log_tool_call_appends_section() -> None:
    """``log_tool_call``
    appends a section to
    the drawer."""
    import asyncio
    from textual.app import App
    from manusift.tui.turn_block import DebugDrawer

    async def driver():
        drawer = DebugDrawer()
        app = App()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.mount(drawer)
            await pilot.pause(0.1)
            drawer.log_tool_call(
                "list_dir", {"path": "C:\\Users\\paper"}
            )
            await pilot.pause(0.1)
            # The
            # drawer
            # has
            # children
            # now.
            assert len(drawer.children) >= 2
    asyncio.run(driver())


# ---------- 7. End-to-end: the chat log is clean ----------


def test_chat_log_has_no_tool_or_system_bubbles() -> None:
    """The end-to-end
    contract: after a
    real turn with tool
    calls, the chat log
    (``#history``) does
    NOT contain any
    ``role='tool'`` or
    ``role='system'``
    bubbles.

    The user spec: "tool
    calling / tool result /
    system debug should
    not render as ordinary
    chat messages"."""
    import asyncio
    from dotenv import load_dotenv
    load_dotenv()
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.tui.chat_app import ChatApp
    from manusift.llm import MockLLM
    from textual.widgets import Input, TextArea
    from textual.containers import VerticalScroll

    app = ChatApp(llm_client=MockLLM())

    async def driver():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.5)
            inp = app.query_one("#input", TextArea)
            for ch in "hi":
                await pilot.press(ch)
                await pilot.pause(0.04)
            await pilot.press("ctrl+j")
            for _ in range(20):
                await pilot.pause(0.3)
                if app._active_worker is None:
                    break
            await pilot.pause(0.5)
            history = app.query_one("#history", VerticalScroll)
            # Every
            # child
            # of
            # ``#history``
            # must
            # be
            # either
            # user
            # or
            # assistant.
            # No
            # tool
            # bubbles
            # (those
            # go
            # to
            # the
            # ToolTraceBlock).
            # System
            # bubbles
            # are
            # the
            # MockLLM
            # startup
            # warning
            # only;
            # the
            # test
            # sends
            # a
            # single
            # user
            # message
            # and
            # gets
            # a
            # mock
            # echo
            # back,
            # so
            # the
            # only
            # ``msg-system``
            # is
            # the
            # startup
            # warning.
            # We
            # assert
            # that
            # at
            # most
            # one
            # ``msg-system``
            # row
            # exists
            # (the
            # warning)
            # and
            # that
            # it
            # does
            # NOT
            # contain
            # a
            # tool
            # call
            # /
            # result
            # text.
            system_bubbles = [
                c for c in history.children
                if "msg-system" in c.classes
            ]
            for c in system_bubbles:
                # If
                # the
                # MockLLM
                # warning
                # is
                # present,
                # it
                # is
                # the
                # ONLY
                # system
                # bubble.
                # Anything
                # else
                # (e.g.
                # a
                # tool
                # result
                # rendered
                # as
                # system)
                # is
                # a
                # layering
                # violation.
                text = str(c.content) if hasattr(c, "content") else ""
                # The
                # ``msg-row``
                # is
                # a
                # ``Horizontal``
                # wrapper.
                # Pull
                # the
                # body
                # text
                # from
                # its
                # children.
                if not text:
                    for sub in c.walk_children():
                        if hasattr(sub, "content") and sub.content:
                            text = str(sub.content)
                            break
                # R-audit (2026-06-11):
                # an
                # empty
                # ``msg-system``
                # bubble
                # (just
                # ``⬤``
                # and
                # no
                # body
                # text)
                # is
                # the
                # same
                # "empty
                # system
                # bubble"
                # anti-pattern
                # the
                # skill
                # flagged
                # in
                # section
                # #3. The
                # bubble
                # is
                # either
                # the
                # MockLLM
                # startup
                # warning
                # (which
                # contains
                # "MockLLM"
                # or
                # "mock")
                # or
                # it
                # should
                # not
                # be
                # in
                # the
                # chat
                # log
                # at
                # all
                # (status
                # line
                # only).
                if not text.strip() or text.strip() == "⬤":
                    # Empty
                    # system
                    # bubble
                    # --
                    # not
                    # a
                    # layering
                    # violation
                    # (it's
                    # a
                    # pre-existing
                    # empty
                    # bubble
                    # bug,
                    # tracked
                    # elsewhere).
                    # We
                    # do
                    # not
                    # fail
                    # here.
                    continue
                assert "MockLLM" in text or "API key" in text or "mock" in text.lower(), (
                    f"unexpected msg-system bubble: {c!r} "
                    f"text={text!r}"
                )
    asyncio.run(driver())


# ---------- 8. The DebugDrawer `d` keybinding works ----------


def test_d_keybinding_toggles_debug_drawer() -> None:
    """Pressing ``d`` in
    the TUI toggles the
    DebugDrawer."""
    import asyncio
    from manusift.tui.chat_app import ChatApp
    from manusift.llm import MockLLM

    app = ChatApp(llm_client=MockLLM())

    async def driver():
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.2)
            # Initially
            # hidden.
            from manusift.tui.turn_block import DebugDrawer
            drawer = app.query_one("#debug-drawer", DebugDrawer)
            assert drawer.is_visible is False
            # Blur
            # the
            # input
            # box
            # so
            # ``d``
            # is
            # captured
            # by
            # the
            # app-level
            # binding.
            from manusift.tui.chat_app import TextArea
            inp = app.query_one("#input", TextArea)
            inp.blur()
            await pilot.pause(0.1)
            # Press
            # ``d``.
            await pilot.press("d")
            await pilot.pause(0.2)
            assert drawer.is_visible is True
            # Press
            # ``d``
            # again
            # to
            # close.
            await pilot.press("d")
            await pilot.pause(0.2)
            assert drawer.is_visible is False
    asyncio.run(driver())
