"""Tests for the LaTeX sanitiser / validator tools (T12).

The T12 tools accept a raw
LaTeX expression and return
either a normalised string
(``sanitize_latex``) or a
validity report
(``validate_latex``). The
tests cover:

  1. Both tools follow the
     ``Tool`` Protocol.
  2. ``sanitize_latex`` strips
     comments and collapses
     whitespace.
  3. ``sanitize_latex`` with
     ``strip_display_dollars=True``
     removes the outer ``$$``
     markers.
  4. ``validate_latex`` reports
     ``ok=True`` for a balanced
     expression.
  5. ``validate_latex`` reports
     ``ok=False`` for an
     unbalanced brace or
     unmatched ``\\begin`` /
     ``\\end``.
  6. Both tools are exposed by
     the registry.
  7. The helper functions
     ``sanitize_latex_expression``
     and
     ``validate_latex_expression``
     produce the expected
     results.
"""
from __future__ import annotations

import json

import pytest


# ---------- 1. Tool Protocol conformance ----------

def test_sanitize_latex_is_a_tool() -> None:
    from manusift.tools import Tool
    from manusift.tools.latex import SanitizeLatexTool
    tool = SanitizeLatexTool()
    assert isinstance(tool, Tool)
    assert tool.name == "sanitize_latex"
    assert isinstance(tool.description(), str)
    assert isinstance(tool.input_schema(), dict)


def test_validate_latex_is_a_tool() -> None:
    from manusift.tools import Tool
    from manusift.tools.latex import ValidateLatexTool
    tool = ValidateLatexTool()
    assert isinstance(tool, Tool)
    assert tool.name == "validate_latex"


# ---------- 2. sanitize_latex strips comments and whitespace ----------

def test_sanitize_latex_strips_comments() -> None:
    from manusift.tools.latex import sanitize_latex_expression
    raw = (
        "x = 5  % this is a comment\n"
        "y = 10"
    )
    out = sanitize_latex_expression(raw)
    assert "%" not in out
    assert "x = 5" in out
    assert "y = 10" in out


def test_sanitize_latex_collapses_whitespace() -> None:
    from manusift.tools.latex import sanitize_latex_expression
    raw = "a    b\t\tc"
    out = sanitize_latex_expression(raw)
    # Multiple spaces collapse
    # to one.
    assert "  " not in out
    assert "\t" not in out
    assert "a b c" == out


# ---------- 3. strip_display_dollars removes outer $ ----------

def test_sanitize_latex_strips_outer_dollars() -> None:
    from manusift.tools.latex import sanitize_latex_expression
    raw = "$$E = mc^2$$"
    out = sanitize_latex_expression(
        raw, strip_display_dollars=True
    )
    assert out == "E = mc^2"


def test_sanitize_latex_keeps_outer_dollars_by_default() -> None:
    from manusift.tools.latex import sanitize_latex_expression
    raw = "$$E = mc^2$$"
    out = sanitize_latex_expression(raw)
    # The outer ``$$`` is
    # preserved when the flag
    # is False.
    assert "$$" in out


# ---------- 4. validate_latex reports ok for balanced input ----------

def test_validate_latex_balanced_expression() -> None:
    from manusift.tools.latex import validate_latex_expression
    result = validate_latex_expression(
        "\\begin{equation} x = 5 \\end{equation}"
    )
    assert result["ok"] is True
    assert result["stats"]["env_balance"]["equation"] == 0
    assert result["stats"]["final_brace_depth"] == 0


def test_validate_latex_unbalanced_brace() -> None:
    from manusift.tools.latex import validate_latex_expression
    result = validate_latex_expression("x = {5")
    assert result["ok"] is False
    # The error list mentions
    # the brace depth.
    assert any(
        ("brace" in e or "{" in e) for e in result["errors"]
    )


def test_validate_latex_unmatched_environment() -> None:
    from manusift.tools.latex import validate_latex_expression
    result = validate_latex_expression(
        "\\begin{equation} x = 5"
    )
    assert result["ok"] is False
    # The error list mentions
    # the unbalanced env.
    assert any(
        "equation" in e for e in result["errors"]
    )


def test_validate_latex_unbalanced_dollar() -> None:
    from manusift.tools.latex import validate_latex_expression
    # Three ``$``: not
    # balanced.
    result = validate_latex_expression("a $b$ c $d")
    assert result["ok"] is False
    # An odd dollar count is
    # reported.
    assert any(
        "$" in e for e in result["errors"]
    )


def test_validate_latex_empty_input() -> None:
    from manusift.tools.latex import validate_latex_expression
    result = validate_latex_expression("")
    assert result["ok"] is False
    assert "empty" in result.get("error", "").lower()


# ---------- 5. registry exposes the latex tools ----------

def test_iter_registered_tools_yields_latex_tools() -> None:
    from manusift.tools import iter_registered_tools
    names = {t.name for t in iter_registered_tools()}
    assert "sanitize_latex" in names
    assert "validate_latex" in names


# ---------- 6. tool execute round-trip ----------

def test_sanitize_latex_tool_execute_round_trip() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.latex import SanitizeLatexTool
    ctx = ToolContext(trace_id="t")
    out = SanitizeLatexTool().execute(
        {"expression": "a    b   c"}, ctx
    )
    data = json.loads(out)
    assert "result" in data
    assert "result_length" in data
    assert data["result"] == "a b c"


def test_validate_latex_tool_execute_round_trip() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.latex import ValidateLatexTool
    ctx = ToolContext(trace_id="t")
    out = ValidateLatexTool().execute(
        {"expression": "x = 5"}, ctx
    )
    data = json.loads(out)
    assert data["ok"] is True
