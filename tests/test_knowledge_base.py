"""Tests for the knowledge-base subpackage (E-audit, 2026-06).

These tests cover three
things:

  1. ``FileBackend`` --
     offline path, zero
     external dependencies.
     Verifies that
     ``.obsidian/`` and
     ``trash/`` are
     skipped, that
     frontmatter is
     parsed, and that
     search / recent
     return the right
     notes.

  2. ``RestBackend`` --
     REST path, requires
     ``httpx``. We never
     make a real HTTP
     call; we patch
     ``httpx.Client`` to
     return canned
     responses so the
     tests run in < 1
     second.

  3. ``resolve_backend`` --
     the rules that pick
     one backend or the
     other (or ``None``)
     based on settings.

The tests use a tiny
synthesized vault built
in a ``tmp_path`` fixture
so they run in any
environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from manusift.config import Settings
from manusift.knowledge import (
    BackendUnavailable,
    KnowledgeBackend,
    NoteContent,
    NoteMeta,
    resolve_backend,
)
from manusift.knowledge.obsidian_files import (
    FileBackend,
    _extract_tags,
    _extract_title,
    _parse_frontmatter,
)
from manusift.tools import ToolContext


# ---------- shared fixtures ----------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Build a tiny
    5-file Obsidian vault
    in ``tmp_path`` and
    return the path.

    Layout::

        <tmp>/
          .obsidian/
            config.md             # must be skipped
          trash/
            old.md               # must be skipped
          research/
            transformer.md       # has frontmatter + body
            gan.md               # no frontmatter
          notes.md               # top-level
    """
    root = tmp_path
    # ``.obsidian/`` --
    # always skipped
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "config.md").write_text(
        "obsidian config"
    )
    # ``trash/`` --
    # always skipped
    (root / "trash").mkdir()
    (root / "trash" / "old.md").write_text("old")
    # ``research/`` --
    # one note with
    # frontmatter
    (root / "research").mkdir()
    (root / "research" / "transformer.md").write_text(
        "---\n"
        "title: Transformer\n"
        "tags: [ml, paper]\n"
        "---\n"
        "# Transformer\n"
        "This is a note about #ml."
    )
    # one note with no
    # frontmatter
    (root / "research" / "gan.md").write_text(
        "# GAN\nA short note."
    )
    # top-level note
    (root / "notes.md").write_text(
        "## Note\n"
        "free text mentioning transformer"
    )
    return root


# ---------- 1. helpers ----------


def test_parse_frontmatter_full() -> None:
    text = (
        "---\n"
        "title: Foo\n"
        "tags: [a, b, c]\n"
        "author: alice\n"
        "---\n"
        "# Body\nhello"
    )
    fm, body = _parse_frontmatter(text)
    assert fm == {
        "title": "Foo",
        "tags": ["a", "b", "c"],
        "author": "alice",
    }
    assert body.startswith("# Body")


def test_parse_frontmatter_absent() -> None:
    text = "# Body only\nno frontmatter"
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_extract_title_from_frontmatter() -> None:
    fm = {"title": "From FM"}
    body = "# H1 ignored\n..."
    assert _extract_title(fm, body, "x.md") == "From FM"


def test_extract_title_from_h1() -> None:
    fm: dict = {}
    body = "# From H1\n..."
    assert _extract_title(fm, body, "x.md") == "From H1"


def test_extract_title_from_filename() -> None:
    fm: dict = {}
    body = "no heading here"
    assert _extract_title(fm, body, "x.md") == "x"


def test_extract_tags_merges_frontmatter_and_inline() -> None:
    fm = {"tags": ["a", "b"]}
    body = "text with #c and #d tags"
    tags = _extract_tags(fm, body)
    assert set(tags) == {"a", "b", "c", "d"}


# ---------- 2. FileBackend ----------


def test_file_backend_skips_obsidian_dir(
    vault: Path,
) -> None:
    backend = FileBackend(
        vault_path=vault,
        glob="**/*.md",
        ignore=".obsidian/**,trash/**",
    )
    rels = [
        m.relpath for m in backend.list_notes()
    ]
    assert "notes.md" in rels
    assert "research/transformer.md" in rels
    assert "research/gan.md" in rels
    # ``.obsidian/`` and
    # ``trash/`` are
    # gone.
    assert not any(
        r.startswith(".obsidian/") for r in rels
    )
    assert not any(
        r.startswith("trash/") for r in rels
    )


def test_file_backend_read_note_parses_frontmatter(
    vault: Path,
) -> None:
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    note = backend.read_note(
        "research/transformer.md"
    )
    assert note.title == "Transformer"
    assert note.frontmatter["tags"] == ["ml", "paper"]
    assert "Transformer" in note.body
    assert "tags:" not in note.body  # stripped


def test_file_backend_read_note_missing(vault: Path) -> None:
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    note = backend.read_note("does/not/exist.md")
    assert note.body == ""


def test_file_backend_search_substring(
    vault: Path,
) -> None:
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    matches = backend.search("transformer", limit=10)
    rels = [m.relpath for m in matches]
    # Two files mention
    # ``transformer``.
    assert "research/transformer.md" in rels
    assert "notes.md" in rels


def test_file_backend_search_no_match(
    vault: Path,
) -> None:
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    assert backend.search("nonsense-xyz") == []


def test_file_backend_recent_returns_newest_first(
    vault: Path,
) -> None:
    import time as _time
    # Bump ``notes.md`` to
    # be the newest file.
    path = vault / "notes.md"
    new_time = _time.time() + 100
    os.utime(path, (new_time, new_time))
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    recent = backend.recent(limit=3)
    assert recent[0].relpath == "notes.md"


def test_file_backend_empty_path_raises() -> None:
    with pytest.raises(BackendUnavailable):
        FileBackend(
            vault_path=Path(""),
            glob="**/*.md",
            ignore="",
        )


def test_file_backend_bad_path_raises() -> None:
    with pytest.raises(BackendUnavailable):
        FileBackend(
            vault_path=Path(
                "C:/this/does/not/exist"
            ),
            glob="**/*.md",
            ignore="",
        )


def test_file_backend_folder_filter(
    vault: Path,
) -> None:
    backend = FileBackend(
        vault_path=vault, glob="**/*.md", ignore=""
    )
    rels = [
        m.relpath
        for m in backend.list_notes(folder="research")
    ]
    assert all(r.startswith("research/") for r in rels)
    assert "notes.md" not in rels


# ---------- 3. RestBackend (with mocked httpx) ----------


class _MockResponse:
    def __init__(
        self,
        status_code: int,
        body: str = "",
        json_data: Any = None,
        content_type: str = "text/plain; charset=utf-8",
    ) -> None:
        self.status_code = status_code
        self.text = body
        self._json = json_data
        self.headers = {"content-type": content_type}

    def json(self) -> Any:
        return self._json


class _MockClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, url: str) -> _MockResponse:
        self.calls.append(("GET", url, None))
        if url.endswith("/vault/"):
            return _MockResponse(
                200,
                json_data=[
                    "research/transformer.md",
                    "notes.md",
                ],
            )
        if "transformer" in url:
            return _MockResponse(
                200,
                body=(
                    "---\n"
                    "title: Transformer\n"
                    "tags: [ml]\n"
                    "---\n"
                    "# Body\n"
                    "transformer is a model."
                ),
            )
        return _MockResponse(404, body="not found")

    def post(
        self, url: str, json: Any = None
    ) -> _MockResponse:
        self.calls.append(("POST", url, json))
        if url.endswith("/search/simple/"):
            return _MockResponse(
                200,
                json_data=["research/transformer.md"],
            )
        return _MockResponse(404, body="not found")


def _patched_rest_backend(
    mock: _MockClient,
):
    """Build a ``RestBackend``
    whose internal
    ``httpx.Client`` is a
    ``_MockClient``. The
    patch is in scope only
    for the duration of
    the test."""
    from manusift.knowledge.obsidian_rest import (
        RestBackend,
    )
    with patch(
        "manusift.knowledge.obsidian_rest.httpx.Client",
        return_value=mock,
    ):
        return RestBackend(
            api_url="https://localhost:27124",
            api_key="test-key",
            verify_tls=False,
        )


def test_rest_backend_list_notes() -> None:
    mock = _MockClient()
    backend = _patched_rest_backend(mock)
    notes = backend.list_notes()
    rels = [m.relpath for m in notes]
    assert "research/transformer.md" in rels
    assert "notes.md" in rels


def test_rest_backend_read_note() -> None:
    mock = _MockClient()
    backend = _patched_rest_backend(mock)
    note = backend.read_note(
        "research/transformer.md"
    )
    assert note.title == "Transformer"
    assert note.frontmatter["tags"] == ["ml"]
    assert "transformer" in note.body


def test_rest_backend_search() -> None:
    mock = _MockClient()
    backend = _patched_rest_backend(mock)
    matches = backend.search("transformer", limit=5)
    rels = [m.relpath for m in matches]
    assert rels == ["research/transformer.md"]


def test_rest_backend_404_returns_empty_note() -> None:
    mock = _MockClient()
    backend = _patched_rest_backend(mock)
    note = backend.read_note("missing.md")
    assert note.body == ""


def test_rest_backend_recent_falls_back_to_alpha() -> None:
    """The REST backend has
    no per-file mtime,
    so ``recent`` returns
    paths in alphabetical
    order."""
    mock = _MockClient()
    backend = _patched_rest_backend(mock)
    notes = backend.recent(limit=5)
    rels = [m.relpath for m in notes]
    # The mock
    # ``/vault/`` returns
    # ``[transformer,
    # notes]`` which is
    # already alpha
    # order.
    assert rels == sorted(rels)


# ---------- 4. resolver ----------


def test_resolver_returns_none_when_unconfigured() -> None:
    s = Settings(
        obsidian_vault_path="",
        obsidian_rest_api_url="",
        obsidian_rest_api_key=None,
    )
    assert resolve_backend(s) is None


def test_resolver_picks_file_when_only_vault_set(
    tmp_path: Path,
) -> None:
    # Build a 1-note
    # vault.
    (tmp_path / "n.md").write_text("hi")
    s = Settings(
        obsidian_vault_path=str(tmp_path),
        obsidian_rest_api_url="",
        obsidian_rest_api_key=None,
    )
    b = resolve_backend(s)
    assert b is not None
    assert b.name == "obsidian_files"


def test_resolver_picks_rest_when_both_set(
    tmp_path: Path,
) -> None:
    from pydantic import SecretStr
    (tmp_path / "n.md").write_text("hi")
    s = Settings(
        obsidian_vault_path=str(tmp_path),
        obsidian_rest_api_url="https://x:27124",
        obsidian_rest_api_key=SecretStr("k"),
    )
    with patch(
        "manusift.knowledge.obsidian_rest.httpx.Client",
    ) as mock_cls:
        mock_cls.return_value = _MockClient()
        b = resolve_backend(s)
    # The REST backend
    # wins because it was
    # configured first.
    assert b is not None
    assert b.name == "obsidian_rest"


def test_resolver_falls_back_to_file_when_rest_unreachable(
    tmp_path: Path,
) -> None:
    from pydantic import SecretStr
    (tmp_path / "n.md").write_text("hi")
    s = Settings(
        obsidian_vault_path=str(tmp_path),
        obsidian_rest_api_url="https://x:27124",
        obsidian_rest_api_key=SecretStr("k"),
    )

    class _BrokenClient:
        def __init__(self, *a: Any, **kw: Any) -> None:
            raise BackendUnavailable(
                "plugin not running"
            )

    with patch(
        "manusift.knowledge.obsidian_rest.httpx.Client",
        side_effect=BackendUnavailable(
            "plugin not running"
        ),
    ):
        b = resolve_backend(s)
    # Fall through to
    # the file backend.
    assert b is not None
    assert b.name == "obsidian_files"


def test_resolver_returns_none_when_path_is_bad() -> None:
    s = Settings(
        obsidian_vault_path="C:/no/such/dir",
        obsidian_rest_api_url="",
        obsidian_rest_api_key=None,
    )
    assert resolve_backend(s) is None
