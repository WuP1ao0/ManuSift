"""Tests for the chat-mode TUI (Step J5).

Borrowed design from the leaked Claude Code v2.1.88 source
for the TUI surface; agent-loop integration follows Step
J3; tool integration follows J1/J4. The chat TUI is a
new app (not a replacement of the existing 4-栏 jobs
TUI) so users can pick ``manusift-tui`` or
``manusift-chat`` based on what they want to do.

The tests use textual's ``app.run_test()`` to drive the
TUI headlessly. The agent loop runs synchronously inside
the test (no real LLM is needed — the LLMClient is
swapped for ``MockLLM``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from manusift.llm import MockLLM
from manusift.tui.chat_app import (
    ChatApp,
    ChatMessage,
    _append_history,
    _chat_dir,
    _load_history,
    main,
)
from textual.widgets import Static as _TwStatic


# R-audit (2026-06-10):
# ``render_message`` now
# returns a
# ``Horizontal``
# (dot column + body
# column) instead of a
# single ``Static``.
# Tests that used to do
# ``child.content`` on
# every child of
# ``#history`` need a
# small helper that
# walks the tree and
# collects the text of
# every ``Static``
# descendant.
def _collect_text(widget) -> str:
    """Return the
    concatenated
    ``widget.content``
    of every ``Static``
    descendant of
    ``widget`` (depth-
    first). Empty
    strings are skipped.
    """
    from textual.widgets import Static
    parts: list[str] = []
    if isinstance(widget, Static):
        text = str(widget.content)
        if text:
            parts.append(text)
    for child in getattr(widget, "children", []):
        parts.append(_collect_text(child))
    return "\n".join(p for p in parts if p)


def _all_history_text(app) -> list[str]:
    """Return the rendered
    plain text of every
    child of ``#history``
    in the ChatApp."""
    history = app.query_one("#history")
    return [
        _collect_text(child)
        for child in history.children
    ]


# ---------- 1. Basic construction and compose ----------

@pytest.mark.asyncio
async def test_app_composes_with_history_and_input() -> None:
    """A fresh app has a banner, history scroll,
    status line, and input. R-audit (2026-06-10): the
    previous version asserted the textual default
    ``Header`` and ``Footer`` were present. Both are now
    removed; the brand banner (``#banner``) replaces the
    ``Header``, and the default ``Footer`` is gone
    (replaced by a custom ``?`` / ``F1`` help overlay).
    A previous iteration also mounted a ``#meta-line``
    ``Static`` between the banner and the history showing
    ``session=... pdf=... llm=...``; that has been
    removed too. The session/pdf/llm info is held in
    ``ChatApp`` attributes only -- it never appears in the
    on-screen layout.
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        # Wait for the app to fully mount.
        await pilot.pause()
        from textual.widgets import Header, Footer, Input, TextArea, Static
        from textual.containers import VerticalScroll
        assert app.query_one("#history", VerticalScroll) is not None
        assert app.query_one("#tool-status", Static) is not None
        assert app.query_one("#input", TextArea) is not None
        # The brand banner is present.
        # The textual default
        # Header / Footer are NOT.
        # The meta-line is NOT
        # (it would clutter
        # the chat area).
        assert app.query_one("#banner", Static) is not None
        try:
            app.query_one("#meta-line")
            assert False, "meta-line should have been removed"
        except Exception:  # noqa: BLE001
            pass
        try:
            app.query_one(Header)
            assert False, "Header should have been removed"
        except Exception:  # noqa: BLE001
            pass
        try:
            app.query_one(Footer)
            assert False, "Footer should have been removed"
        except Exception:  # noqa: BLE001
            pass


@pytest.mark.asyncio
async def test_app_subtitle_shows_session_and_model() -> None:
    """The header subtitle is informative: it tells the
    user which session and which LLM are in play."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "session=" in app.sub_title
        assert "llm=mock" in app.sub_title
        # No PDF uploaded yet.
        assert "pdf=(no pdf loaded)" in app.sub_title


# ---------- 2. Slash command: /upload ----------

@pytest.mark.asyncio
async def test_upload_copies_pdf_and_binds_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/upload <path>`` copies the PDF into a job dir,
    parses it, and binds the parsed doc into ctx."""
    import fitz  # type: ignore[import-not-found]
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello world")
    pdf_path = tmp_path / "doc.pdf"
    pdf.save(str(pdf_path))
    pdf.close()

    # Point the workspace at a fresh tmp dir.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    chats_root = tmp_path / "chats"
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Type the upload command. The text needs to be set
        # on the Input widget and then we trigger the
        # on_input_submitted handler.
        from textual.widgets import Input, TextArea
        inp = app.query_one("#input", TextArea)
        inp.text = f"/upload {pdf_path}"
        # Simulate pressing Enter.
        await pilot.press("ctrl+j")
        await pilot.pause()
        # The PDF is now bound to ctx: trace_id is the
        # workspace key, current_pdf is the user-facing path.
        assert app._ctx.trace_id
        assert app._ctx.current_pdf == str(pdf_path)
        assert app._parsed_doc is not None
        # The header reflects the new state.
        assert app._ctx.current_pdf in app.sub_title
        # A copy of the PDF is in the workspace.
        copied = workspace / app._ctx.trace_id / "original.pdf"
        assert copied.exists()
        assert app._ctx.metadata["pdf_path"] == str(pdf_path)
        # The system message was appended to the log.
        msgs = _all_history_text(app)
        assert any("loaded" in m for m in msgs)


@pytest.mark.asyncio
async def test_upload_rejects_non_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/upload <not-a-pdf>`` produces a friendly error
    in the log; the ctx is unchanged."""
    not_pdf = tmp_path / "doc.txt"
    not_pdf.write_text("hello", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from textual.widgets import Input, TextArea
        inp = app.query_one("#input", TextArea)
        inp.text = f"/upload {not_pdf}"
        await pilot.press("ctrl+j")
        await pilot.pause()
        # ctx is unchanged.
        assert app._ctx.current_pdf is None
        # An error message was logged.
        msgs = _all_history_text(app)
        assert any("not a PDF" in m for m in msgs)


# ---------- 3. Slash command: /tools ----------

@pytest.mark.asyncio
async def test_tools_command_lists_registered_tools() -> None:
    """``/tools`` lists every tool the agent can call."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from textual.widgets import Input, TextArea
        inp = app.query_one("#input", TextArea)
        inp.text = "/tools"
        await pilot.press("ctrl+j")
        await pilot.pause()
        # R-2026-06-15 (Phase 6 + #5):
        # when the slash popover is
        # visible, the first Enter
        # inserts the command name
        # into the input (without
        # invoking it).  A second
        # Enter is what actually
        # dispatches the command.
        # See ``on_input_submitted``:
        # the popover intercepts the
        # first Enter and converts
        # it to an "insert" gesture.
        # We press Enter twice here
        # to mirror the new UX.
        await pilot.press("ctrl+j")
        await pilot.pause()
        msgs = _all_history_text(app)
        # The 4 built-in tools must be listed.
        joined = "\n".join(msgs)
        assert "metadata" in joined
        assert "image_dup" in joined


# ---------- 4. Slash command: /clear ----------

@pytest.mark.asyncio
async def test_clear_command_clears_on_screen_history_only() -> None:
    """``/clear`` wipes the on-screen log; the persisted
    file is left intact (so a future TUI restart can
    replay the conversation)."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Add a message to the log via the public API.
        app._append_message(
            ChatMessage(role="user", content="hello")
        )
        await pilot.pause()
        # Now /clear.
        from textual.widgets import Input, TextArea
        inp = app.query_one("#input", TextArea)
        inp.text = "/clear"
        # R-2026-06-15 (Phase 6 + #5):
        # the slash popover intercepts
        # the first Enter and converts
        # it to an "insert" gesture
        # (fills the input with the
        # full command name).  A
        # second Enter actually
        # dispatches the command.
        # See ``on_input_submitted``.
        await pilot.press("ctrl+j")
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        # On-screen history is empty.
        children = [m for m in app.query_one("#history").children if m is not None]
        assert children == []
        # But the in-memory list and the persisted file
        # still have the message.
        assert len(app._history) >= 1
        history_file = app._session_dir / "messages.jsonl"
        assert history_file.exists()


# ---------- 5. Agent loop integration ----------

@pytest.mark.asyncio
async def test_user_message_runs_agent_and_appears_in_history() -> None:
    """Type a non-slash message; the agent loop runs (with
    MockLLM, end_turn after one text response) and the
    text appears in the on-screen log."""
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Drive the agent loop directly; we do not exercise
        # the Input widget here because textual's
        # Pilot.press("enter") timing makes it racy in
        # this test environment.
        app._submit_user_message("analyze this paper")
        await pilot.pause()
        msgs = _all_history_text(app)
        joined = "\n".join(msgs)
        # The user message is in the log.
        assert "analyze this paper" in joined
        # The mock echo is in the log too.
        assert "mock echo" in joined


@pytest.mark.asyncio
async def test_input_path_review_ingests_data_and_writes_html_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real Enter-submit in chat-tui should route a
    pasted PDF path plus separate source-data directory
    through the same full tool registry and end by writing
    an HTML report.
    """
    import json as _json
    import fitz

    from manusift.config import get_settings
    from manusift.llm.chat import ChatResponse
    from manusift.tools import iter_registered_tools

    class _HtmlReportLLM:
        name = "html-report-tui-smoke"

        def __init__(self) -> None:
            self.calls = 0
            self.trace_id = ""
            self.tool_names: list[str] = []
            self.data_source_count = 0
            self.detector_result_seen = False
            self.data_source_table_id = ""
            self.data_source_read_seen = False

        def is_available(self):
            return True

        def analyze_finding(self, finding):
            return None

        def _read_ingest_payload(self, messages):
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    try:
                        envelope = _json.loads(block.get("content", ""))
                    except Exception:  # noqa: BLE001
                        continue
                    payload = envelope.get("result", envelope)
                    if (
                        isinstance(payload, dict)
                        and payload.get("trace_id")
                    ):
                            return payload
            return {}

        def _has_detector_result(self, messages):
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    try:
                        envelope = _json.loads(block.get("content", ""))
                    except Exception:  # noqa: BLE001
                        continue
                    if (
                        envelope.get("tool_name") == "metadata"
                        and envelope.get("ok") is True
                    ):
                        return True
            return False

        def _read_table_id_from_list_data_sources(self, messages):
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    try:
                        envelope = _json.loads(block.get("content", ""))
                    except Exception:  # noqa: BLE001
                        continue
                    if envelope.get("tool_name") != "list_data_sources":
                        continue
                    payload = envelope.get("result", {})
                    tables = payload.get("tables", [])
                    if tables:
                        return str(tables[0].get("table_id", ""))
            return ""

        def _has_read_data_source_result(self, messages):
            for message in messages:
                content = message.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if block.get("type") != "tool_result":
                        continue
                    try:
                        envelope = _json.loads(block.get("content", ""))
                    except Exception:  # noqa: BLE001
                        continue
                    if envelope.get("tool_name") != "read_data_source":
                        continue
                    payload = envelope.get("result", {})
                    rows = payload.get("rows", [])
                    headers = payload.get("headers", [])
                    if "group" in headers and rows:
                        return True
            return False

        def chat(self, messages, tools=None, **kw):
            self.calls += 1
            self.tool_names = [
                tool.get("name", "") for tool in (tools or [])
            ]
            if self.calls == 1:
                payload = self._read_ingest_payload(messages)
                self.trace_id = str(payload.get("trace_id", ""))
                self.data_source_count = int(
                    payload.get("data_source_count", 0)
                )
                return ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": "metadata-1",
                            "name": "metadata",
                            "input": {},
                        }
                    ],
                    stop_reason="tool_use",
                )
            if self.calls == 2:
                self.detector_result_seen = self._has_detector_result(
                    messages
                )
                return ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": "list-data-1",
                            "name": "list_data_sources",
                            "input": {
                                "trace_id": self.trace_id,
                            },
                        }
                    ],
                    stop_reason="tool_use",
                )
            if self.calls == 3:
                self.data_source_table_id = (
                    self._read_table_id_from_list_data_sources(messages)
                )
                return ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": "read-data-1",
                            "name": "read_data_source",
                            "input": {
                                "trace_id": self.trace_id,
                                "table_id": self.data_source_table_id,
                                "max_rows": 10,
                            },
                        }
                    ],
                    stop_reason="tool_use",
                )
            if self.calls == 4:
                self.data_source_read_seen = (
                    self._has_read_data_source_result(messages)
                )
                return ChatResponse(
                    content_blocks=[
                        {
                            "type": "tool_use",
                            "id": "render-1",
                            "name": "render_report",
                            "input": {
                                "trace_id": self.trace_id,
                                "include_pdf": False,
                                "markdown": (
                                    "# ManuSift HTML Report\n\n"
                                    "The Textual chat input ingested "
                                    "the PDF and companion data.\n\n"
                                    "Metadata detector ran before "
                                    "report rendering.\n\n"
                                    "Original CSV data was listed "
                                    "and read before report rendering.\n"
                                ),
                            },
                        }
                    ],
                    stop_reason="tool_use",
                )
            return ChatResponse(
                content_blocks=[
                    {
                        "type": "text",
                        "text": "HTML report generated.",
                    }
                ],
                stop_reason="end_turn",
            )

    workspace = tmp_path / "workspace"
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    case_dir = tmp_path / "case folder"
    raw_data_dir = tmp_path / "raw data"
    case_dir.mkdir()
    raw_data_dir.mkdir()
    pdf_path = case_dir / "main paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Synthetic paper with raw data.")
    doc.save(str(pdf_path))
    doc.close()
    (raw_data_dir / "source_data.csv").write_text(
        "group,value\nA,1\nB,2\nB,2\n",
        encoding="utf-8",
    )

    llm = _HtmlReportLLM()
    app = ChatApp(llm_client=llm)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from textual.widgets import Input, TextArea

        inp = app.query_one("#input", TextArea)
        inp.text = (
            f"review {pdf_path} with original data "
            f"{raw_data_dir} and generate an HTML report"
        )
        await pilot.press("ctrl+j")
        for _ in range(120):
            await pilot.pause(0.05)
            if llm.trace_id:
                report = workspace / llm.trace_id / "report.html"
                joined = "\n".join(_all_history_text(app))
                if (
                    report.exists()
                    and "HTML report generated." in joined
                ):
                    break

        assert llm.trace_id
        assert llm.data_source_count >= 1
        assert llm.detector_result_seen is True
        assert llm.data_source_table_id
        assert llm.data_source_read_seen is True
        expected_tool_names = {
            tool.name for tool in iter_registered_tools()
        }
        assert set(llm.tool_names) == expected_tool_names
        report = workspace / llm.trace_id / "report.html"
        assert report.exists()
        html = report.read_text(encoding="utf-8")
        assert "ManuSift HTML Report" in html
        assert "companion data" in html
        assert "Metadata detector ran before report rendering" in html
        assert "Original CSV data was listed and read" in html
        joined = "\n".join(_all_history_text(app))
        assert "HTML report generated." in joined

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unknown_command_writes_system_message() -> None:
    """``/garbage`` produces a system message in the log
    rather than being silently swallowed. Slash command
    outputs are user-explicit, so they render as chat
    bubbles (only *agent-loop* system messages go to the
    status line in R-audit 2026-06-10).
    """
    app = ChatApp(llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from textual.widgets import Input, TextArea
        inp = app.query_one("#input", TextArea)
        inp.text = "/garbage"
        await pilot.press("ctrl+j")
        await pilot.pause()
        msgs = _all_history_text(app)
        assert any("unknown command" in m for m in msgs)


# ---------- 6. Persistence: messages.jsonl round-trip ----------

@pytest.mark.asyncio
async def test_history_persists_to_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A message appended via the TUI lands in
    messages.jsonl. A second app instance with the same
    session_id replays it on mount."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    sid = "test-session-1"
    app = ChatApp(session_id=sid, llm_client=MockLLM())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._append_message(
            ChatMessage(role="user", content="first message")
        )
        await pilot.pause()
        app._append_message(
            ChatMessage(role="assistant", content="first reply")
        )
        await pilot.pause()

    # The file should exist.
    p = _chat_dir(sid) / "messages.jsonl"
    assert p.exists()
    # Reload from disk into a fresh app.
    app2 = ChatApp(session_id=sid, llm_client=MockLLM())
    history = _load_history(_chat_dir(sid))
    # Three messages: the MockLLM warning emitted at
    # app start (R-audit 2026-06-10), plus the user
    # "first message" and the assistant "first reply".
    assert len(history) == 3
    assert history[0].role == "system"
    assert "MockLLM" in history[0].content
    assert history[1].content == "first message"
    assert history[2].content == "first reply"


# ---------- 7. main() entry point ----------

@pytest.mark.asyncio
async def test_main_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()`` is the console-script entry point. It
    constructs a ChatApp and calls ``app.run()``. We
    replace ``app.run`` with a no-op so the test exits
    immediately without trying to take over a real
    terminal."""
    from manusift.tui import chat_app

    called = {"ran": False}

    class FakeApp:
        def run(self) -> None:
            called["ran"] = True

    monkeypatch.setattr(chat_app, "ChatApp", FakeApp)
    main()
    assert called["ran"]
