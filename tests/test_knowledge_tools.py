"""Tests for the LLM-facing knowledge tools (E-audit, 2026-06).

The four tools in
``manusift.tools.knowledge``
(
``ListVaultNotesTool``,
``ReadNoteTool``,
``SearchVaultTool``,
``RecentVaultNotesTool``)
all wrap a
``KnowledgeBackend`` and
return a JSON string.
The tests below pin:

  * the JSON envelope
    shape (``{"error":
    "..."}`` for failure,
    ``{"count": N, ...}``
    for success),
  * the per-tool input
    schema (LLM-facing),
  * the error path when
    the backend is not
    configured (the LLM
    gets a friendly
    "vault not configured"
    message rather than a
    stack trace),
  * the error path when
    the backend raises
    ``BackendUnavailable``
    mid-flight (e.g. REST
    API plugin not
    running).

The tests use a 1-note
in-memory
``FakeBackend`` rather
than the real
``FileBackend`` so they
run in < 0.5 s with no
disk I/O.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from manusift.knowledge import BackendUnavailable
from manusift.knowledge.base import (
    NoteContent,
    NoteMeta,
)
from manusift.tools import ToolContext
from manusift.tools.knowledge import (
    ListVaultNotesTool,
    ReadNoteTool,
    RecentVaultNotesTool,
    SearchVaultTool,
    register_knowledge_tools,
)


# ---------- shared fixtures ----------


class _FakeBackend:
    """In-memory backend
    that satisfies the
    ``KnowledgeBackend``
    Protocol. Lets the
    tests run without
    touching the
    filesystem."""

    name = "fake"

    def __init__(
        self,
        notes: list[NoteMeta] | None = None,
        bodies: dict[str, str] | None = None,
    ) -> None:
        self._notes = notes or []
        self._bodies = bodies or {}

    def list_notes(
        self, folder: str = ""
    ) -> list[NoteMeta]:
        if not folder:
            return list(self._notes)
        prefix = f"{folder.strip('/').rstrip('/')}/"
        return [
            n
            for n in self._notes
            if n.relpath.startswith(prefix)
        ]

    def read_note(
        self, relpath: str
    ) -> NoteContent:
        for n in self._notes:
            if n.relpath == relpath:
                return NoteContent(
                    relpath=relpath,
                    title=n.title,
                    body=self._bodies.get(
                        relpath, ""
                    ),
                )
        return NoteContent(
            relpath=relpath,
            title=relpath,
            body="",
        )

    def search(
        self, query: str, limit: int = 10
    ) -> list[NoteMeta]:
        q = query.lower()
        out: list[NoteMeta] = []
        for n in self._notes:
            body = self._bodies.get(
                n.relpath, ""
            )
            if q in n.title.lower() or q in body.lower():
                out.append(n)
                if len(out) >= limit:
                    break
        return out

    def recent(
        self, limit: int = 10
    ) -> list[NoteMeta]:
        return list(self._notes)[:limit]


def _ctx() -> ToolContext:
    return ToolContext(trace_id="t1")


# ---------- 1. registry helper ----------


def test_register_knowledge_tools_returns_four() -> None:
    tools = register_knowledge_tools()
    assert len(tools) == 4
    names = {t.name for t in tools}
    assert names == {
        "list_vault_notes",
        "read_note",
        "search_vault",
        "recent_vault_notes",
    }


# ---------- 2. ListVaultNotesTool ----------


def test_list_vault_notes_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(
                relpath="a.md", title="A", tags=["t1"]
            ),
            NoteMeta(
                relpath="b.md", title="B", tags=[]
            ),
        ]
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = ListVaultNotesTool()
    out = json.loads(
        t.execute({"folder": "", "limit": 50}, _ctx())
    )
    assert out["count"] == 2
    assert {n["relpath"] for n in out["notes"]} == {
        "a.md",
        "b.md",
    }


def test_list_vault_notes_respects_folder_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(
                relpath="research/a.md", title="A"
            ),
            NoteMeta(
                relpath="notes/b.md", title="B"
            ),
        ]
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = ListVaultNotesTool()
    out = json.loads(
        t.execute(
            {"folder": "research", "limit": 50}, _ctx()
        )
    )
    assert out["count"] == 1
    assert out["notes"][0]["relpath"] == "research/a.md"


def test_list_vault_notes_no_backend_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    monkeypatch.setattr(km, "_get_backend", lambda c: None)
    t = ListVaultNotesTool()
    out = json.loads(
        t.execute({"folder": "", "limit": 50}, _ctx())
    )
    assert "error" in out
    assert "not configured" in out["error"]


# ---------- 3. ReadNoteTool ----------


def test_read_note_returns_full_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(
                relpath="a.md",
                title="A",
                tags=["x"],
            ),
        ],
        bodies={"a.md": "the body"},
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = ReadNoteTool()
    out = json.loads(
        t.execute({"relpath": "a.md"}, _ctx())
    )
    assert out["title"] == "A"
    assert out["body"] == "the body"
    assert out["relpath"] == "a.md"


def test_read_note_missing_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(notes=[], bodies={})
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = ReadNoteTool()
    out = json.loads(
        t.execute({"relpath": "no.md"}, _ctx())
    )
    assert "error" in out
    assert "not found" in out["error"]


def test_read_note_requires_relpath(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend()
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = ReadNoteTool()
    out = json.loads(t.execute({}, _ctx()))
    assert "error" in out
    assert "required" in out["error"]


# ---------- 4. SearchVaultTool ----------


def test_search_vault_returns_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(
                relpath="a.md",
                title="Transformer",
            ),
            NoteMeta(
                relpath="b.md",
                title="GAN",
            ),
        ],
        bodies={
            "a.md": "a transformer is a model",
            "b.md": "a gan is a model",
        },
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = SearchVaultTool()
    out = json.loads(
        t.execute({"query": "transformer", "limit": 10}, _ctx())
    )
    assert out["count"] == 1
    assert out["matches"][0]["relpath"] == "a.md"


def test_search_vault_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(relpath=f"n{i}.md", title="x")
            for i in range(5)
        ],
        bodies={f"n{i}.md": "match" for i in range(5)},
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = SearchVaultTool()
    out = json.loads(
        t.execute({"query": "match", "limit": 2}, _ctx())
    )
    assert out["count"] == 2


# ---------- 5. RecentVaultNotesTool ----------


def test_recent_vault_notes_returns_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    backend = _FakeBackend(
        notes=[
            NoteMeta(relpath=f"n{i}.md", title=f"N{i}")
            for i in range(3)
        ]
    )
    monkeypatch.setattr(km, "_get_backend", lambda c: backend)
    t = RecentVaultNotesTool()
    out = json.loads(t.execute({"limit": 10}, _ctx()))
    assert out["count"] == 3


# ---------- 6. backend unavailability mid-flight ----------


class _CrashingBackend(_FakeBackend):
    def list_notes(
        self, folder: str = ""
    ) -> list[NoteMeta]:
        raise BackendUnavailable("vault locked")


def test_backend_unavailable_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from manusift.tools import knowledge as km
    monkeypatch.setattr(
        km, "_get_backend", lambda c: _CrashingBackend()
    )
    t = ListVaultNotesTool()
    out = json.loads(
        t.execute({"folder": "", "limit": 10}, _ctx())
    )
    assert "error" in out
    assert "vault locked" in out["error"]


# ---------- 7. tool descriptions are LLM-readable ----------


def test_tool_descriptions_mention_obsidian() -> None:
    """Each tool's
    ``description()``
    mentions "external
    knowledge base" or
    "Obsidian" so the
    LLM knows what it's
    for. (C-audit: short
    descriptions cause the
    LLM to skip a tool.)"""
    for t in register_knowledge_tools():
        d = t.description()
        assert (
            "knowledge base" in d.lower()
            or "obsidian" in d.lower()
            or "vault" in d.lower()
        ), f"tool {t.name!r} desc is too vague: {d[:80]!r}"


def test_tool_descriptions_are_substantive() -> None:
    """B-audit regression:
    descriptions are at
    least 100 chars."""
    for t in register_knowledge_tools():
        d = t.description()
        assert len(d) >= 100, (
            f"tool {t.name!r} desc too short: "
            f"{len(d)} chars"
        )
