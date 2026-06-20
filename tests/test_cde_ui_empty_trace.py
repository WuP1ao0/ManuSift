"""R-2026-06-20 (CDE-UI-EMPTY):
regression test for
the "tools 0
calls" stripe
that the user
saw in their
15:51 screenshot
after typing
"你好".

The user asked:
"LLM replied
slowly; is the
'0 tool use'
text related?"

The answer is
"no, that's
not the cause
of slowness"
(the slow part
is the
Anthropic API
latency), but
the "tools 0
calls" stripe
is misleading
UX. For a
greeting turn
where the
LLM never
calls a tool,
the user sees
an empty
"tools 0 calls"
block which
looks like an
error.

Fix:
``ToolTraceBlock.seal()``
hides the
block via
``self.display = False``
when the turn
used zero
tools. The
stripe
disappears
entirely for
tool-less
turns.
"""
from __future__ import annotations

import asyncio

import pytest

from manusift.contracts import ChatMessage
from manusift.llm import MockLLM
from manusift.tui.chat_app import ChatApp


# ---------- 1. ToolTraceBlock hides itself when sealed with 0 entries ----------

def test_tool_trace_block_hides_itself_when_zero_entries() -> None:
    """``ToolTraceBlock.seal()``
    must set
    ``self.display = False``
    when no tools
    were called
    (n == 0).
    The user
    should not see
    a "tools 0
    calls" stripe
    for greeting /
    short Q&A
    turns.
    """
    from manusift.tui.turn_block import ToolTraceBlock
    block = ToolTraceBlock()
    # Pre-seal:
    # visible
    # (PulsatingDots /
    # "thinking"
    # state).
    assert block.display is not False
    # No
    # entries
    # added.
    # Seal.
    block.seal()
    # Post-seal:
    # hidden
    # (display
    # = False).
    assert block.display is False, (
        f"ToolTraceBlock did not hide itself when sealed "
        f"with 0 entries; display = {block.display!r}"
    )


def test_tool_trace_block_stays_visible_when_tools_were_called() -> None:
    """``ToolTraceBlock.seal()``
    must NOT hide
    the block if
    at least one
    tool was
    called. The
    user wants to
    see the
    per-tool counts.
    """
    from manusift.tui.turn_block import (
        ToolEntry,
        TOOL_OK,
        ToolTraceBlock,
    )
    block = ToolTraceBlock()
    block.add_entry(
        ToolEntry(
            tool_id="t1",
            tool_name="read_file",
            status=TOOL_OK,
        )
    )
    block.seal()
    # Block
    # must
    # remain
    # visible
    # (display
    # not
    # False).
    assert block.display is not False, (
        f"ToolTraceBlock hid itself with 1 entry; "
        f"display = {block.display!r}"
    )


# ---------- 2. end-to-end: greeting turn produces no "tools 0 calls" stripe ----------

@pytest.mark.asyncio
async def test_greeting_turn_hides_tool_trace_block() -> None:
    """A user
    message
    that
    triggers
    a
    simple
    greeting
    (no
    tool
    calls)
    must
    not
    leave
    a
    "tools
    0
    calls"
    stripe
    in
    the
    chat
    log.

    Reproduces
    the
    user
    screenshot
    at
    15:51.
    """
    from textual.containers import VerticalScroll
    from textual.widgets import TextArea
    from manusift.tui.turn_block import ToolTraceBlock

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        # Drop
        # the
        # MockLLM
        # banner
        # so
        # the
        # count
        # is
        # clean.
        history = app.query_one("#history", VerticalScroll)
        for child in list(history.children):
            child.remove()
        await pilot.pause(0.05)
        # Submit
        # "hi"
        # (a
        # greeting
        # --
        # no
        # tool
        # calls
        # expected).
        inp = app.query_one("#input", TextArea)
        inp.focus()
        await pilot.pause(0.05)
        inp.text = "hi"
        await pilot.pause(0.05)
        app.action_submit_input()
        # Wait
        # for
        # the
        # agent
        # to
        # finish.
        for _ in range(20):
            await pilot.pause(0.1)
            if not app._agent_running:
                break
        await pilot.pause(0.2)
        # Count
        # visible
        # ToolTraceBlock
        # instances.
        # If
        # the
        # turn
        # was
        # tool-less,
        # the
        # block
        # should
        # be
        # hidden
        # (display
        # =
        # False)
        # so
        # we
        # should
        # see
        # 0
        # visible
        # blocks.
        visible_tool_blocks = [
            w for w in history.children
            if isinstance(w, ToolTraceBlock)
            and w.display is not False
        ]
        assert len(visible_tool_blocks) == 0, (
            f"expected 0 visible ToolTraceBlock widgets after a "
            f"tool-less greeting; found {len(visible_tool_blocks)}"
        )