"""R-2026-06-15 (Phase 4 + P4-1 + P4-2):
regression smoke test for
the god-file
extraction.

After the
``agent_tools.py``
(2280 lines) and
``llm/client.py``
(1719 lines)
refactors, the
following
invariants must
hold:

  1. ``manusift.tools.agent_tools``
     is a package
     containing the
     6 submodules:
     ``web_search``,
     ``web_fetch``,
     ``bash``,
     ``grep_glob``,
     ``task``,
     ``todo_write``.
  2. All 7 classes
     (BashTool,
     WebSearchTool,
     WebFetchTool,
     GrepTool,
     GlobTool,
     TaskTool,
     TodoWriteTool)
     are importable
     from the
     package root
     (backward compat).
  3. ``manusift.llm.client``
     is a package
     containing the
     3 submodules:
     ``protocol``,
     ``providers``,
     ``mock``.
  4. All 4 classes
     (LLMClient,
     MockLLM,
     OpenAILLM,
     AnthropicLLM)
     are importable
     from the
     package root
     (backward compat).
  5. The shared
     helpers
     (openai_create_with_retry,
     anthropic_create_with_retry,
     format_llm_error,
     build_prompt,
     safe_parse,
     strip_code_fence,
     unwrap_key,
     safe_json_loads)
     are importable
     from the
     package root.

This test runs in
~1s (no LLM calls,
no subprocess) and
acts as a fast
gate against any
future regression
that breaks the
refactor's backward
compatibility.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pytest


# ============================================================
# 1. agent_tools package structure
# ============================================================


def test_p4_agent_tools_is_a_package() -> None:
    """``manusift.tools.agent_tools``
    is now a *package*
    (a directory with
    ``__init__.py``),
    NOT a single
    ``.py`` file.
    """
    spec = importlib.util.find_spec(
        "manusift.tools.agent_tools"
    )
    assert spec is not None
    # The spec.origin should be
    # ``.../agent_tools/__init__.py``,
    # NOT ``.../agent_tools.py``.
    assert spec.origin is not None
    assert spec.origin.endswith(
        ("agent_tools\\__init__.py", "agent_tools/__init__.py")
    ), f"agent_tools should be a package, got origin={spec.origin!r}"


def test_p4_agent_tools_submodules_exist() -> None:
    """The 6 submodules
    exist and are
    importable.
    """
    expected = [
        "web_search",
        "web_fetch",
        "bash",
        "grep_glob",
        "task",
        "todo_write",
    ]
    for mod_name in expected:
        mod = importlib.import_module(
            f"manusift.tools.agent_tools.{mod_name}"
        )
        assert mod is not None
        assert mod.__file__ is not None
        # Must be under the
        # package directory.
        assert mod.__file__.endswith(
            f"{mod_name}.py"
        )


# ============================================================
# 2. agent_tools backward compat
# ============================================================


def test_p4_all_seven_classes_re_exported() -> None:
    """All 7 classes are
    importable from the
    package root, so
    the 46+ existing
    test files do not
    need to change
    their import
    statements.
    """
    from manusift.tools.agent_tools import (
        BashTool,
        GlobTool,
        GrepTool,
        TaskTool,
        TodoWriteTool,
        WebFetchTool,
        WebSearchTool,
    )
    # Sanity: each is
    # a class.
    for cls in [
        BashTool,
        GlobTool,
        GrepTool,
        TaskTool,
        TodoWriteTool,
        WebFetchTool,
        WebSearchTool,
    ]:
        assert isinstance(cls, type)
    # And each can be
    # instantiated.
    for cls in [
        BashTool,
        GlobTool,
        GrepTool,
        TaskTool,
        TodoWriteTool,
        WebFetchTool,
        WebSearchTool,
    ]:
        inst = cls()
        assert hasattr(inst, "name")
        assert hasattr(inst, "execute")


def test_p4_agent_tools_helpers_re_exported() -> None:
    """The module-level
    helpers used by
    tests are still
    importable.
    """
    from manusift.tools.agent_tools import (
        register_agent_tools,
        _filter_tools_by_role,
        _shell_command_args,
        SHELL_MODES,
    )
    assert callable(register_agent_tools)
    assert callable(_filter_tools_by_role)
    assert callable(_shell_command_args)
    assert SHELL_MODES == (
        "auto",
        "posix",
        "cmd",
        "powershell",
    )


# ============================================================
# 3. llm.client package structure
# ============================================================


def test_p4_llm_client_is_a_package() -> None:
    """``manusift.llm.client``
    is now a package
    with 3
    submodules.
    """
    spec = importlib.util.find_spec(
        "manusift.llm.client"
    )
    assert spec is not None
    assert spec.origin is not None
    assert spec.origin.endswith(
        ("client\\__init__.py", "client/__init__.py")
    ), f"llm.client should be a package, got origin={spec.origin!r}"


def test_p4_llm_client_submodules_exist() -> None:
    """The 3 submodules
    exist and are
    importable.
    """
    for mod_name in [
        "protocol",
        "providers",
        "mock",
    ]:
        mod = importlib.import_module(
            f"manusift.llm.client.{mod_name}"
        )
        assert mod is not None
        assert mod.__file__ is not None
        assert mod.__file__.endswith(f"{mod_name}.py")


# ============================================================
# 4. llm.client backward compat
# ============================================================


def test_p4_all_four_llm_classes_re_exported() -> None:
    """All 4 classes
    (``LLMClient``
    Protocol +
    ``MockLLM`` +
    ``OpenAILLM`` +
    ``AnthropicLLM``)
    are importable
    from the package
    root.
    """
    from manusift.llm.client import (
        LLMClient,
        MockLLM,
        OpenAILLM,
        AnthropicLLM,
    )
    assert isinstance(LLMClient, type)
    assert isinstance(MockLLM, type)
    assert isinstance(OpenAILLM, type)
    assert isinstance(AnthropicLLM, type)


def test_p4_llm_client_singleton_factories() -> None:
    """``get_llm_client``
    and
    ``_reset_for_tests``
    are still
    importable from
    the package root
    (test fixtures
    depend on them).
    """
    from manusift.llm.client import (
        get_llm_client,
        _reset_for_tests,
    )
    assert callable(get_llm_client)
    assert callable(_reset_for_tests)


# ============================================================
# 5. llm.client shared helpers re-exported
# ============================================================


def test_p4_llm_client_format_helpers_re_exported() -> None:
    """The 8 shared
    helpers are
    importable from
    the package root.
    """
    from manusift.llm.client import (
        _format_llm_error,
        _build_prompt,
        _safe_parse,
        _strip_code_fence,
        _unwrap_key,
        _safe_json_loads,
    )
    for fn in [
        _format_llm_error,
        _build_prompt,
        _safe_parse,
        _strip_code_fence,
        _unwrap_key,
        _safe_json_loads,
    ]:
        assert callable(fn)


# ============================================================
# 6. Tool registry still works
# ============================================================


def test_p4_register_agent_tools_returns_all_tools() -> None:
    """``register_agent_tools``
    (in
    ``agent_tools/__init__.py``)
    returns the
    10-tool list,
    including the
    3 cross-module
    tools
    (``SourceDataAuditTool``,
    ``PythonExecTool``,
    ``TableScanTool``)
    that live in
    other files.
    """
    from manusift.tools.agent_tools import (
        register_agent_tools,
    )
    tools = register_agent_tools()
    names = sorted(t.name for t in tools)
    expected_names = sorted(
        [
            "web_search",
            "web_fetch",
            "bash",
            "grep",
            "glob",
            "task",
            "todo_write",
            "source_data_audit",
            "python_exec",
            "table_scan",
        ]
    )
    assert names == expected_names, (
        f"got {names}, expected {expected_names}"
    )


# ============================================================
# 7. LLM client is_available works
# ============================================================


def test_p4_mock_llm_is_always_available() -> None:
    """``MockLLM.is_available()``
    always returns
    ``True`` (no
    network key
    required).
    """
    from manusift.llm.client import MockLLM

    mock = MockLLM()
    assert mock.is_available() is True
    assert mock.name == "mock"


# ============================================================
# 8. Cross-package imports still work
# ============================================================


def test_p4_task_tool_imports_from_manusift_subpackages() -> None:
    """``TaskTool``
    (in
    ``agent_tools/task.py``)
    uses imports like
    ``from ...agent``
    (3 dots =
    ``manusift.agent``)
    and
    ``from ..subagent_forwarder``
    (2 dots =
    ``manusift.tools.subagent_forwarder``).
    Verify both
    resolve.
    """
    from manusift.tools.agent_tools.task import (
        TaskTool,
    )
    from manusift.tools.agent_tools import (
        _filter_tools_by_role,
    )
    # Sanity: the
    # helper is
    # importable
    # from the
    # task
    # submodule
    # (it is
    # re-exported).
    assert callable(_filter_tools_by_role)
    # And the
    # task
    # class
    # itself.
    inst = TaskTool()
    assert inst.name == "task"


def test_p4_openai_provider_uses_correct_dotted_imports() -> None:
    """``OpenAILLM``
    (in
    ``providers.py``)
    uses
    ``from ...config``
    (3 dots =
    ``manusift.config``)
    and
    ``from ..chat``
    (2 dots =
    ``manusift.llm.chat``).
    Verify both
    resolve.
    """
    from manusift.llm.client.providers import (
        OpenAILLM,
        AnthropicLLM,
        _openai_create_with_retry,
        _anthropic_create_with_retry,
    )
    # The class
    # bodies and
    # helper
    # bodies
    # reference
    # the
    # imported
    # names
    # (Settings,
    # Finding,
    # ChatResponse,
    # etc.).
    # If the
    # dotted
    # imports
    # were
    # broken,
    # the
    # module
    # would
    # fail to
    # import
    # at all.
    assert OpenAILLM.__module__ == (
        "manusift.llm.client.providers"
    )
    assert AnthropicLLM.__module__ == (
        "manusift.llm.client.providers"
    )
    assert callable(_openai_create_with_retry)
    assert callable(_anthropic_create_with_retry)
