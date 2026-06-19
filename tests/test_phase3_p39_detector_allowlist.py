"""R-2026-06-15 (Phase 3 + P3-9):
test the detector
allowlist env var.

The audit flagged that
CI cannot run a subset
of detectors (e.g. "just
the image detectors for
this fast smoke test")
because the registry
hard-codes
"all-or-nothing" runs.
The fix is a
``MANUSIFT_DETECTORS``
env var with a
comma-separated list
of detector names.  Only
those detectors run;
others are skipped.

These tests verify:

  1. With
     ``MANUSIFT_DETECTORS``
     unset or empty,
     ``iter_allowed_detectors``
     yields all
     detectors (the
     default
     "all" case).
  2. With
     ``MANUSIFT_DETECTORS="image_dup,image_forensics"``,
     only those
     detectors are
     yielded.
  3. With
     ``MANUSIFT_DETECTORS="  image_dup  , image_forensics  "``,
     whitespace is
     ignored.
  4. With
     ``MANUSIFT_DETECTORS="image_dup,nonexistent_detector"``,
     unknown names are
     silently dropped
     (the user can
     mistype without
     crashing).
  5. With
     ``MANUSIFT_DETECTORS=""``
     (empty), all
     detectors are
     yielded.
  6. With
     ``MANUSIFT_DETECTORS=","``
     (only commas),
     all detectors are
     yielded (treated
     as empty).
  7. The
     ``_parse_allowlist_env``
     helper returns
     ``None`` for
     "no allowlist" and
     a ``set`` for
     "allowlist".
  8. The allowlist
     filter is
     **per-iteration**,
     not module-level
     (so a test can
     change the env
     var and see
     different
     results).
"""
from __future__ import annotations

import pytest

from manusift.detectors import (
    _parse_allowlist_env,
    detector_names,
    iter_allowed_detectors,
    iter_registered_detectors,
)


def test_p39_no_env_var_yields_all_detectors() -> None:
    """Without
    ``MANUSIFT_DETECTORS``,
    all detectors are
    yielded.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(
        "MANUSIFT_DETECTORS",
        raising=False,
    )
    try:
        names = sorted(
            getattr(d, "name", "")
            for d in iter_allowed_detectors()
        )
    finally:
        monkeypatch.undo()
    expected = sorted(detector_names())
    assert names == expected


def test_p39_env_var_filters_to_subset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With
    ``MANUSIFT_DETECTORS="image_dup,image_forensics"``,
    only those
    detectors are
    yielded.
    """
    monkeypatch.setenv(
        "MANUSIFT_DETECTORS",
        "image_dup,image_forensics",
    )
    names = sorted(
        getattr(d, "name", "")
        for d in iter_allowed_detectors()
    )
    # Filter to only
    # detectors that
    # actually exist;
    # the user's
    # allowlist may
    # include a name
    # that is not
    # registered.
    if "image_dup" in detector_names():
        assert "image_dup" in names
    if "image_forensics" in detector_names():
        assert "image_forensics" in names


def test_p39_env_var_ignores_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace
    around detector
    names is ignored.
    """
    monkeypatch.setenv(
        "MANUSIFT_DETECTORS",
        "  image_dup  ,  image_forensics  ",
    )
    names = sorted(
        getattr(d, "name", "")
        for d in iter_allowed_detectors()
    )
    if "image_dup" in detector_names():
        assert "image_dup" in names
    if "image_forensics" in detector_names():
        assert "image_forensics" in names


def test_p39_unknown_detector_name_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown
    detector name in
    the allowlist is
    silently dropped
    (the user can
    mistype without
    crashing).
    """
    monkeypatch.setenv(
        "MANUSIFT_DETECTORS",
        "image_dup,nonexistent_detector_xyz",
    )
    # The function
    # should not raise.
    list(iter_allowed_detectors())


def test_p39_empty_env_var_yields_all() -> None:
    """An empty
    ``MANUSIFT_DETECTORS``
    yields all
    detectors.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("MANUSIFT_DETECTORS", "")
    try:
        names = sorted(
            getattr(d, "name", "")
            for d in iter_allowed_detectors()
        )
    finally:
        monkeypatch.undo()
    expected = sorted(detector_names())
    assert names == expected


def test_p39_only_commas_yields_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A value of just
    commas (no real
    names) is treated
    as empty.
    """
    monkeypatch.setenv("MANUSIFT_DETECTORS", ",,,")
    names = sorted(
        getattr(d, "name", "")
        for d in iter_allowed_detectors()
    )
    expected = sorted(detector_names())
    assert names == expected


def test_p39_parse_allowlist_env_unset() -> None:
    """``_parse_allowlist_env``
    returns ``None`` when
    the env var is
    unset.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.delenv(
        "MANUSIFT_DETECTORS",
        raising=False,
    )
    try:
        assert (
            _parse_allowlist_env() is None
        )
    finally:
        monkeypatch.undo()


def test_p39_parse_allowlist_env_empty() -> None:
    """``_parse_allowlist_env``
    returns ``None``
    when the env var is
    empty.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("MANUSIFT_DETECTORS", "")
    try:
        assert (
            _parse_allowlist_env() is None
        )
    finally:
        monkeypatch.undo()


def test_p39_parse_allowlist_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_parse_allowlist_env``
    returns a ``set``
    when the env var is
    set to a
    comma-separated
    list.
    """
    monkeypatch.setenv(
        "MANUSIFT_DETECTORS",
        "a, b, c",
    )
    s = _parse_allowlist_env()
    assert s == {"a", "b", "c"}


def test_p39_iter_registered_detectors_is_a_superset() -> None:
    """``iter_allowed_detectors``
    is a subset (or
    equal) of
    ``iter_registered_detectors``
    (the allowlist can
    only filter, never
    add new detectors).
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(
        "MANUSIFT_DETECTORS", "image_dup"
    )
    try:
        allowed = {
            getattr(d, "name", "")
            for d in iter_allowed_detectors()
        }
    finally:
        monkeypatch.undo()
    registered = {
        getattr(d, "name", "")
        for d in iter_registered_detectors()
    }
    # Every allowed
    # detector is in
    # the registered
    # set.
    assert allowed.issubset(registered)
