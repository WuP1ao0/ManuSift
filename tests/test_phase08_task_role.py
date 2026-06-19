"""Tests for the R-2026-06-15 (Phase 0.8)
TaskTool ``role`` parameter
(leaf vs orchestrator).

The contract:

  * A ``role="leaf"`` sub-agent
    does NOT have ``TaskTool``
    in its tool list.
  * A ``role="orchestrator"``
    sub-agent has the full
    tool list.
  * The default is
    ``role="leaf"`` (the safe
    default).
  * An invalid role returns
    ``error_kind=not_applicable``
    before any sub-agent is
    constructed.
  * The ``TaskTool.input_schema``
    includes the ``role``
    property with the
    ``"leaf"`` / ``"orchestrator"``
    enum.

Pattern follows the agent-infra-
iteration-engineer skill rule
I.4: pure-helper + thin wiring,
both tested.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tools import iter_registered_tools
from manusift.tools.agent_tools import (
    TaskTool,
    _filter_tools_by_role,
)


# --------------------------------------------------------------------
# TaskTool schema has the role field
# --------------------------------------------------------------------


def test_task_tool_input_schema_has_role():
    """The ``TaskTool.input_schema``
    includes a ``role``
    property with the
    ``"leaf"`` /
    ``"orchestrator"`` enum.
    """
    schema = TaskTool().input_schema()
    props = schema["properties"]
    assert "role" in props
    assert "leaf" in props["role"]["enum"]
    assert (
        "orchestrator" in props["role"]["enum"]
    )


def test_task_tool_description_mentions_role():
    """The tool description
    explains the role
    semantics so the LLM
    can decide.
    """
    desc = TaskTool().description()
    assert "leaf" in desc
    assert "orchestrator" in desc
    # The default is
    # ``leaf`` (safe).
    assert "default" in desc.lower()


# --------------------------------------------------------------------
# _filter_tools_by_role pure helper
# --------------------------------------------------------------------


def test_filter_tools_strips_task_for_leaf():
    tools = list(iter_registered_tools())
    task_tools = [
        t for t in tools if t.name == "task"
    ]
    if not task_tools:
        pytest.skip(
            "no TaskTool in the registered "
            "tools; cannot test role filter"
        )
    leaf_tools = _filter_tools_by_role(tools, "leaf")
    leaf_names = {t.name for t in leaf_tools}
    assert "task" not in leaf_names


def test_filter_tools_preserves_task_for_orchestrator():
    tools = list(iter_registered_tools())
    task_tools = [
        t for t in tools if t.name == "task"
    ]
    if not task_tools:
        pytest.skip(
            "no TaskTool in the registered "
            "tools; cannot test role filter"
        )
    orch_tools = _filter_tools_by_role(
        tools, "orchestrator"
    )
    orch_names = {t.name for t in orch_tools}
    assert "task" in orch_names
    # The orchestrator
    # tool list is the
    # same as the
    # full list.
    assert len(orch_tools) == len(tools)


def test_filter_tools_default_is_leaf():
    """A ``role=None`` or
    missing role defaults
    to ``"leaf"`` (the safe
    default).
    """
    tools = list(iter_registered_tools())
    task_tools = [
        t for t in tools if t.name == "task"
    ]
    if not task_tools:
        pytest.skip(
            "no TaskTool in the registered "
            "tools; cannot test default"
        )
    none_tools = _filter_tools_by_role(
        tools, role=None
    )
    none_names = {t.name for t in none_tools}
    assert "task" not in none_names


def test_filter_tools_unknown_role_returns_empty():
    """An unknown role
    returns an empty list
    (caller is responsible
    for emitting the
    typed error).
    """
    tools = list(iter_registered_tools())
    unknown = _filter_tools_by_role(
        tools, "unknown-role"
    )
    assert unknown == []
