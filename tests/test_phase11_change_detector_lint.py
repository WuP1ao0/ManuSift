"""Tests for the R-2026-06-15 (Phase 0.11)
``change_detector_lint`` plugin.

The contract:

  * A test whose name or
    docstring mentions a
    change-detector
    keyword
    (``change_detector`` /
    ``image_dup`` /
    ``stat_grim`` etc.)
    AND whose body does
    NOT call a detector
    is flagged with a
    warning.
  * A test that DOES call a
    detector is not
    flagged.
  * A test that has the
    ``# no-detector-required``
    marker (in the name
    or docstring) is
    never flagged, even
    if it does not call
    a detector.
  * A test whose name /
    docstring does NOT
    mention a detector
    keyword is never
    flagged (no false
    positives).
  * The warning text
    includes the test's
    nodeid and the
    opt-out hint.

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
the plugin is a pure
helper + a thin
``pytest_sessionfinish``
hook.
"""
from __future__ import annotations

import re
from typing import Any

import pytest

from manusift.tests import change_detector_lint
from manusift.tests.change_detector_lint import (
    _is_detector_test,
    _has_no_detector_marker,
    collect_warnings,
)


# --------------------------------------------------------------------
# _is_detector_test
# --------------------------------------------------------------------


def test_is_detector_test_recognizes_image_dup_in_name():
    assert _is_detector_test(
        "test_image_dup_basic", None
    ) is True


def test_is_detector_test_recognizes_stat_grim_in_name():
    assert _is_detector_test(
        "test_stat_grim_threshold", None
    ) is True


def test_is_detector_test_recognizes_change_detector_in_name():
    assert _is_detector_test(
        "test_change_detector_full_pipeline",
        None,
    ) is True


def test_is_detector_test_recognizes_keyword_in_docstring():
    assert _is_detector_test(
        "test_something", (
            "Tests the image_dup "
            "detector on a small PDF."
        ),
    ) is True


def test_is_detector_test_returns_false_for_unrelated():
    assert _is_detector_test(
        "test_bash_window", None
    ) is False
    assert _is_detector_test(
        "test_bash_window",
        "Test the bash tool.",
    ) is False


# --------------------------------------------------------------------
# _has_no_detector_marker
# --------------------------------------------------------------------


def test_has_no_detector_marker_in_name():
    assert _has_no_detector_marker(
        "test_image_dup_basic "
        "# no-detector-required",
        None,
    ) is True


def test_has_no_detector_marker_in_docstring():
    assert _has_no_detector_marker(
        "test_something",
        (
            "Image_dup test.\n"
            "# no-detector-required\n"
            "The detector is not yet wired."
        ),
    ) is True


def test_has_no_detector_marker_returns_false_by_default():
    assert _has_no_detector_marker(
        "test_image_dup_basic", None
    ) is False


# --------------------------------------------------------------------
# collect_warnings
# --------------------------------------------------------------------


class _FakeFunction:
    """Stand-in for a real
    test function. The
    plugin only inspects
    ``__name__`` and
    ``__code__.co_names``.
    """

    def __init__(
        self,
        name: str,
        co_names: tuple[str, ...] = (),
        doc: str | None = None,
    ) -> None:
        self.__name__ = name
        self.__qualname__ = name
        self.__doc__ = doc
        # Build a
        # minimal
        # code-like
        # object that
        # has the
        # attributes
        # the plugin
        # inspects.
        self.__code__ = _FakeCode(co_names)


class _FakeCode:
    def __init__(self, co_names: tuple[str, ...]) -> None:
        self.co_names = co_names


class _FakeItem:
    """Stand-in for a
    ``pytest.Item``.
    """

    def __init__(
        self,
        name: str,
        co_names: tuple[str, ...] = (),
        doc: str | None = None,
    ) -> None:
        self.name = name
        self.nodeid = f"tests/test_x.py::{name}"
        self.function = _FakeFunction(
            name, co_names=co_names, doc=doc
        )


def test_warns_when_detector_keyword_but_no_detector_call():
    items = [
        _FakeItem(
            "test_image_dup_basic",
            co_names=("pytest", "assert"),
        ),
    ]
    warnings = collect_warnings(items)
    assert len(warnings) == 1
    assert "test_image_dup_basic" in warnings[0]
    assert "no-detector-required" in warnings[0]


def test_does_not_warn_when_detector_is_called():
    items = [
        _FakeItem(
            "test_image_dup_basic",
            co_names=("image_dup", "assert"),
        ),
    ]
    assert collect_warnings(items) == []


def test_does_not_warn_for_unrelated_test():
    items = [
        _FakeItem(
            "test_bash_window",
            co_names=("pytest",),
        ),
    ]
    assert collect_warnings(items) == []


def test_opt_out_marker_suppresses_warning():
    items = [
        _FakeItem(
            "test_image_dup_basic "
            "# no-detector-required",
            co_names=("pytest", "assert"),
        ),
    ]
    assert collect_warnings(items) == []


def test_opt_out_marker_in_docstring_suppresses_warning():
    items = [
        _FakeItem(
            "test_image_dup_basic",
            co_names=("pytest", "assert"),
            doc=(
                "Image dup test.\n"
                "# no-detector-required"
            ),
        ),
    ]
    assert collect_warnings(items) == []


def test_warning_lists_nodeid():
    items = [
        _FakeItem(
            "test_change_detector_full_pipeline",
            co_names=("pytest",),
        ),
    ]
    warnings = collect_warnings(items)
    assert len(warnings) == 1
    assert (
        "test_change_detector_full_pipeline"
        in warnings[0]
    )


def test_warning_text_mentions_manusift_lint():
    items = [
        _FakeItem(
            "test_stat_grim_threshold",
            co_names=("pytest",),
        ),
    ]
    warnings = collect_warnings(items)
    assert len(warnings) == 1
    # The prefix
    # ``change_detector_lint:``
    # is the visible
    # marker.
    assert "change_detector_lint" in warnings[0]
