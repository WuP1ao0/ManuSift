"""Tests for the R-2026-06-14 P1.3 detector
enable/disable.

Contract:

  * ``registry.disable(name)`` and
    ``registry.enable(name)`` are idempotent
    and operate on a per-process set.
  * ``iter_registered_tools()`` skips
    disabled tools; ``tool_names()`` and
    the LLM-facing tool list therefore
    also skip them.
  * ``get_tool(name)`` (the explicit
    accessor) still returns the
    unfiltered instance, so a power user
    can still call a disabled tool.
  * ``reset_disabled()`` is a test hook
    that drops every disable.
  * The doctor /tools reg check
    (already in place) reports the
    disabled count.

Pattern follows the
``agent-infra-iteration-engineer``
skill rule I.5: "any settings field
that affects what the offline pipeline
runs automatically must NOT affect
what tools the LLM can call on
demand." Here the LLM cannot
auto-suggest a disabled tool, but
explicit ``registry.get_tool`` and
``registry.iter_registered_tools
(include_disabled=True)`` are the
escape hatches.
"""
from __future__ import annotations

import pytest

from manusift.tools import (
    iter_registered_tools,
    registry,
    tool_names,
)


@pytest.fixture(autouse=True)
def _clean_disabled():
    registry.reset_disabled()
    yield
    registry.reset_disabled()


# --------------------------------------------------------------------
# disable / enable / is_disabled
# --------------------------------------------------------------------


def test_disable_is_idempotent():
    registry.disable("foo")
    registry.disable("foo")
    assert registry.list_disabled() == ("foo",)


def test_enable_is_idempotent():
    registry.enable("foo")
    registry.enable("foo")
    assert "foo" not in registry.list_disabled()


def test_disable_then_enable_clears():
    registry.disable("foo")
    assert registry.is_disabled("foo")
    registry.enable("foo")
    assert not registry.is_disabled("foo")


def test_list_disabled_is_sorted():
    registry.disable("z")
    registry.disable("a")
    registry.disable("m")
    assert registry.list_disabled() == ("a", "m", "z")


# --------------------------------------------------------------------
# iter_registered_tools filters
# --------------------------------------------------------------------


def test_iter_registered_tools_skips_disabled():
    """If we disable a real tool that
    ships in the registry, it should
    not appear in the iteration.
    """
    all_names = set(tool_names())
    assert "bash" in all_names  # sanity
    registry.disable("bash")
    new_names = set(tool_names())
    assert "bash" not in new_names
    # Total count drops by 1 (no other side
    # effects).
    assert len(all_names) - len(new_names) == 1


def test_iter_registered_tools_with_no_disables_is_unfiltered():
    """Sanity check: with no disables,
    the iteration returns the full set.
    """
    names = set(tool_names())
    assert "bash" in names
    assert "image_dup" in names
    assert "stat_grim" in names


def test_disabling_unknown_name_does_not_raise():
    """``disable`` is purely additive;
    it does not validate that the
    name exists. (Power users may
    pre-disable a not-yet-registered
    third-party plugin.)
    """
    registry.disable("not_a_real_tool_xyz")
    assert registry.is_disabled("not_a_real_tool_xyz")


# --------------------------------------------------------------------
# Doctor / tool_reg observes the disabled set
# --------------------------------------------------------------------


def test_doctor_reports_disable_count():
    """The doctor ``tool_reg`` check
    details dict carries
    ``budget_caps`` and a count; the
    registry_disable_count is read
    separately by the doctor. Verify
    the registry's count.
    """
    from manusift.tui.doctor import (
        _check_tool_registry,
    )
    initial = _check_tool_registry()
    initial_count = initial.details.get(
        "registry_disable_count", 0
    )
    registry.disable("bash")
    after = _check_tool_registry()
    after_count = after.details.get(
        "registry_disable_count", 0
    )
    assert after_count == initial_count + 1


# --------------------------------------------------------------------
# reset_disabled test hook
# --------------------------------------------------------------------


def test_reset_disabled_drops_every_disable():
    registry.disable("a")
    registry.disable("b")
    assert len(registry.list_disabled()) == 2
    registry.reset_disabled()
    assert registry.list_disabled() == ()


# --------------------------------------------------------------------
# Tool count consistency
# --------------------------------------------------------------------


def test_disable_then_enable_restores_count():
    """Disabling then re-enabling a
    tool restores the original
    count.
    """
    before = len(tool_names())
    registry.disable("bash")
    assert len(tool_names()) == before - 1
    registry.enable("bash")
    assert len(tool_names()) == before
