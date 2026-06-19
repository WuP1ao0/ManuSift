"""R-2026-06-19 (P2-B4):
``/diff``
slash command.

P2-B5 added the
``DiffTool``
(``manusift.tools.agent_tools.diff.DiffTool``).
P2-B4 wires it
as a
``/diff``
slash command
via
``manusift.tui.diff_cmd._diff_handler``.

The handler
parses three
arg forms:

  1. ``/diff
     <path_a>
     <path_b>``
     -- two
     files.
  2. ``/diff
     <path>
     new_content=<content>``
     -- file
     vs
     string.
  3. ``/diff`` (no
     arg) --
     usage
     hint.

Tests:

  * ``_parse_diff_arg``
    correctly
    parses
    the
    three
    arg
    forms.
  * The
    ``/diff``
    command
    is
    registered
    on
    import.
  * The
    handler
    gracefully
    surfaces
    errors
    (no
    crash)
    when
    the
    tool
    returns
    ``ok: False``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui import diff_cmd  # noqa: E402
from manusift.tui.diff_cmd import (  # noqa: E402
    _diff_handler,
    _parse_diff_arg,
)


# ---------------------------------------------------------------------------
# _parse_diff_arg
# ---------------------------------------------------------------------------


class TestParseDiffArg:
    def test_empty_arg_returns_empty_dict(self):
        assert _parse_diff_arg("") == {}
        assert _parse_diff_arg("   ") == {}

    def test_two_paths(self):
        out = _parse_diff_arg("a.txt b.txt")
        assert out == {"path_a": "a.txt", "path_b": "b.txt"}

    def test_single_path(self):
        out = _parse_diff_arg("only.txt")
        assert out == {"path": "only.txt"}

    def test_path_with_new_content_inline(self):
        out = _parse_diff_arg(
            "src.py new_content=line1\nline2\nline3"
        )
        assert out == {
            "path": "src.py",
            "new_content": "line1\nline2\nline3",
        }

    def test_path_with_new_content_quoted(self):
        out = _parse_diff_arg(
            'src.py new_content="line1\\nline2"'
        )
        # Quoted
        # form
        # strips
        # the
        # surrounding
        # quotes.
        assert out["path"] == "src.py"
        assert out["new_content"] == "line1\\nline2"

    def test_path_with_spaces(self):
        # Path
        # with
        # spaces
        # is
        # not
        # supported
        # in
        # the
        # simple
        # parser;
        # the
        # first
        # token
        # is
        # taken
        # as
        # path_a
        # and
        # the
        # rest
        # as
        # path_b
        # (a
        # limitation).
        out = _parse_diff_arg("a b c")
        # 3 tokens
        # → 2
        # (path_a,
        # path_b
        # = "b
        # c"
        # which
        # is
        # a
        # weird
        # but
        # valid
        # invocation).
        assert "path_a" in out
        assert "path_b" in out


# ---------------------------------------------------------------------------
# /diff command registration
# ---------------------------------------------------------------------------


class TestSlashRegistration:
    def test_diff_command_registered(self):
        from manusift.tui.slash_registry import find

        cmd = find("diff")
        assert cmd is not None
        assert cmd.name == "diff"
        assert cmd.category == "Diagnostics"
        # Alias ``d``
        # is also
        # registered.
        assert "d" in cmd.aliases


# ---------------------------------------------------------------------------
# _diff_handler
# ---------------------------------------------------------------------------


class TestDiffHandler:
    def test_handler_does_not_crash_on_empty_arg(
        self,
    ):
        app = MagicMock()
        _diff_handler(app, "")
        # The handler
        # must surface
        # the usage
        # hint.
        assert app._append_status_line.call_count >= 1
        assert any(
            "usage" in str(c.args[0]).lower()
            for c in app._append_status_line.call_args_list
        )

    def test_handler_calls_diff_tool_for_two_paths(
        self, tmp_path, monkeypatch
    ):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("line1\n")
        b.write_text("line1\nline2\n")
        # Capture
        # the
        # tool
        # call.
        from manusift.tools.agent_tools import diff as diff_tool_mod

        captured: dict = {}

        def fake_execute(self, input, ctx):
            captured["input"] = input
            return json.dumps(
                {
                    "ok": True,
                    "diff": "--- a\n+++ b\n@@\n-line1\n+line2\n",
                    "fromfile": "a",
                    "tofile": "b",
                    "is_empty": False,
                    "n_added": 1,
                    "n_removed": 1,
                }
            )

        monkeypatch.setattr(
            diff_tool_mod.DiffTool, "execute", fake_execute
        )
        app = MagicMock()
        _diff_handler(app, f"{a} {b}")
        assert captured.get("input", {}).get("path_a") == str(a)
        assert captured.get("input", {}).get("path_b") == str(b)
        # The diff
        # lines
        # are
        # appended
        # to the
        # status
        # line.
        assert app._append_status_line.call_count >= 2

    def test_handler_surfaces_tool_error(self, monkeypatch):
        from manusift.tools.agent_tools import diff as diff_tool_mod

        def fake_execute(self, input, ctx):
            return json.dumps(
                {
                    "ok": False,
                    "error_kind": "argument_invalid",
                    "error": "missing args",
                }
            )

        monkeypatch.setattr(
            diff_tool_mod.DiffTool, "execute", fake_execute
        )
        app = MagicMock()
        # Pass a
        # non-empty
        # arg so
        # the handler
        # reaches
        # the tool
        # call.
        _diff_handler(app, "a.txt b.txt")
        # The error
        # message
        # appears
        # in
        # the
        # status
        # line.
        assert any(
            "missing args" in str(c.args[0])
            for c in app._append_status_line.call_args_list
        )
