"""R-2026-06-19 (P2-B5):
``DiffTool``
(read-only
unified
diff viewer).

Borrowed from
Claude Code's
inline-diff
rendering in
the ``Edit``
tool.
ManuSift's
``DiffTool``
is a
read-only
preview: it
shows what a
proposed
change would
look like
without ever
mutating the
user's files.

Tests:

  * Two-file
    mode
    (``path_a``
    +
    ``path_b``):
    returns a
    unified
    diff with
    ``---`` /
    ``+++``
    headers
    and ``+`` /
    ``-`` body
    lines.
  * File-vs-string
    mode
    (``path``
    +
    ``new_content``):
    returns
    the same
    shape, with
    the
    proposed
    new content
    as the
    right side.
  * Empty
    diff
    (identical
    files):
    returns
    ``is_empty: True``
    and a
    blank
    ``diff``
    field.
  * Invalid
    args:
    returns
    ``ok: False``
    + a clear
    error
    message.
  * Binary
    file
    gracefully
    falls
    through
    via
    ``errors="replace"``
    (UTF-8
    decode
    failures
    don't
    crash the
    tool).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tools.tool import ToolContext  # noqa: E402
from manusift.tools.agent_tools.diff import DiffTool  # noqa: E402


@pytest.fixture
def tool():
    return DiffTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(
        trace_id="trace_b5",
        current_pdf="",
        metadata={"workspace_dir": str(tmp_path)},
    )


# ---------------------------------------------------------------------------
# Two-file mode
# ---------------------------------------------------------------------------


class TestTwoFileMode:
    def test_basic_diff(self, tool, ctx, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("line 1\nline 2\nline 3\n")
        b.write_text("line 1\nLINE TWO\nline 3\n")
        out = json.loads(
            tool.execute(
                {"path_a": str(a), "path_b": str(b)}, ctx
            )
        )
        assert out["ok"] is True
        assert "---" in out["diff"]
        assert "+++" in out["diff"]
        assert "-line 2" in out["diff"]
        assert "+LINE TWO" in out["diff"]
        assert out["is_empty"] is False
        assert out["n_removed"] == 1
        assert out["n_added"] == 1

    def test_identical_files_returns_empty_diff(
        self, tool, ctx, tmp_path
    ):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same\n")
        b.write_text("same\n")
        out = json.loads(
            tool.execute(
                {"path_a": str(a), "path_b": str(b)}, ctx
            )
        )
        assert out["ok"] is True
        assert out["diff"] == ""
        assert out["is_empty"] is True
        assert out["n_added"] == 0
        assert out["n_removed"] == 0


# ---------------------------------------------------------------------------
# File-vs-string mode
# ---------------------------------------------------------------------------


class TestFileVsStringMode:
    def test_proposed_edit(self, tool, ctx, tmp_path):
        p = tmp_path / "src.py"
        p.write_text("def hello():\n    return 'old'\n")
        proposed = (
            "def hello():\n"
            "    return 'new'\n"
        )
        out = json.loads(
            tool.execute(
                {"path": str(p), "new_content": proposed}, ctx
            )
        )
        assert out["ok"] is True
        assert "-    return 'old'" in out["diff"]
        assert "+    return 'new'" in out["diff"]
        assert out["n_added"] == 1
        assert out["n_removed"] == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrors:
    def test_missing_args_returns_error(
        self, tool, ctx
    ):
        out = json.loads(tool.execute({}, ctx))
        assert out["ok"] is False
        assert out["error_kind"] == "argument_invalid"

    def test_path_a_nonexistent_returns_error(
        self, tool, ctx, tmp_path
    ):
        out = json.loads(
            tool.execute(
                {
                    "path_a": str(tmp_path / "missing.txt"),
                    "path_b": str(tmp_path / "x.txt"),
                },
                ctx,
            )
        )
        assert out["ok"] is False
        assert out["error_kind"] == "argument_invalid"

    def test_path_b_nonexistent_returns_error(
        self, tool, ctx, tmp_path
    ):
        a = tmp_path / "a.txt"
        a.write_text("x")
        out = json.loads(
            tool.execute(
                {
                    "path_a": str(a),
                    "path_b": str(tmp_path / "missing.txt"),
                },
                ctx,
            )
        )
        assert out["ok"] is False
        assert out["error_kind"] == "argument_invalid"

    def test_binary_file_falls_through(
        self, tool, ctx, tmp_path
    ):
        # A file with invalid UTF-8 bytes
        # should NOT crash the tool.
        a = tmp_path / "a.txt"
        a.write_bytes(b"\xff\xfe binary garbage \x00\x01")
        b = tmp_path / "b.txt"
        b.write_text("plain text")
        out = json.loads(
            tool.execute(
                {"path_a": str(a), "path_b": str(b)}, ctx
            )
        )
        # The tool uses
        # ``errors="replace"``
        # so the read
        # succeeds (with
        # replacement
        # characters).
        # The diff may
        # be empty or
        # contain ``\ufffd``
        # chars but the
        # tool returns
        # ``ok: True``.
        assert out["ok"] is True
        assert "diff" in out
