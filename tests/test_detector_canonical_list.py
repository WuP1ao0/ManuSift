"""Tests for the canonical
``iter_registered_detectors``
list (R3).

The R3 audit found that the
old ``iter_modules +
endswith("Detector")``
heuristic in the TUI's
status bar was fragile:
classes whose name does not
end with ``"Detector"``
(``AuthorEmailAnalyzer``,
``ComplianceStatementDetector``,
etc.) were silently dropped.
The fix is a canonical
``__all__``-based list in
``manusift.detectors`` plus
an ``iter_registered_detectors``
generator. The tests below
pin the contract.
"""
from __future__ import annotations

import inspect

import pytest


# ---------- 1. detector count ----------

def test_at_least_twenty_five_detectors() -> None:
    """R3: the project ships at
    least 25 built-in
    detectors. If the count
    drops below 25 the audit
    has not regressed but a
    new detector has been
    forgotten -- flag it."""
    from manusift.detectors import detector_names
    n = len(detector_names())
    assert n >= 25, (
        f"expected >= 25 detectors, got {n}"
    )


# ---------- 2. every detector in __all__ ----------

def test_every_builtin_detector_is_in_all() -> None:
    """R3: ``__all__`` is the
    canonical list. Any
    detector class that is
    NOT in ``__all__`` is
    missing from the public
    API and should be added.
    """
    import manusift.detectors as pkg
    all_names = set(getattr(pkg, "__all__", []))
    # Each class in the
    # module's globals that
    # is a detector (has
    # ``name`` + ``run``) is
    # listed in ``__all__``.
    for name, obj in vars(pkg).items():
        if not isinstance(obj, type):
            continue
        if not (hasattr(obj, "name") and callable(getattr(obj, "run", None))):
            continue
        mod = getattr(obj, "__module__", "")
        if not (
            mod == pkg.__name__
            or mod.startswith(pkg.__name__ + ".")
        ):
            continue
        assert name in all_names, (
            f"detector {name!r} (in {mod!r}) is "
            "not in manusift.detectors.__all__"
        )


# ---------- 3. iter_registered_detectors returns instances ----------

def test_iter_registered_detectors_yields_instances() -> None:
    """R3: every yielded
    detector must be a
    concrete instance (not a
    class) so the TUI can
    count them without
    manually calling
    ``cls()`` itself."""
    from manusift.detectors import iter_registered_detectors
    for det in iter_registered_detectors():
        assert not isinstance(det, type), (
            f"iter_registered_detectors yielded a class, "
            f"not an instance: {det!r}"
        )
        # The instance must
        # have a ``name`` and
        # ``run``.
        assert hasattr(det, "name")
        assert callable(getattr(det, "run", None))


# ---------- 4. detector_names is sorted ----------

def test_detector_names_are_deterministic() -> None:
    """R3: ``detector_names`` must
    return the same list in
    the same order on every
    call (so the web layer's
    ``/api/detectors``
    endpoint is stable across
    requests). The order is
    determined by the import
    order in
    ``manusift.detectors.__init__``;
    alphabetical is not
    required."""
    from manusift.detectors import detector_names
    first = detector_names()
    second = detector_names()
    third = detector_names()
    assert first == second == third, (
        f"detector_names() is not stable: {first} != {second}"
    )


# ---------- 5. AuthorEmailAnalyzer is counted (regression) ----------

def test_author_email_analyzer_is_counted() -> None:
    """R3 regression: the
    ``AuthorEmailAnalyzer``
    class does NOT end with
    ``"Detector"`` (it ends
    with ``"Analyzer"``). The
    old ``endswith("Detector")``
    heuristic in the TUI
    silently dropped it. The
    new canonical list must
    include its ``name``
    attribute.
    """
    from manusift.detectors import (
        AuthorEmailAnalyzer,
        detector_names,
    )
    names = detector_names()
    assert AuthorEmailAnalyzer.name in names, (
        f"AuthorEmailAnalyzer.name = "
        f"{AuthorEmailAnalyzer.name!r} not in {names!r} -- "
        "R3 regression"
    )


# ---------- 6. The TUI uses the new helper ----------

def test_chat_app_uses_iter_registered_detectors() -> None:
    """R3: the TUI's
    ``_render_detector_count``
    must call
    ``iter_registered_detectors``
    (not the old
    ``iter_modules`` heuristic)
    so the canonical list is
    the single source of truth.
    """
    from manusift.tui.chat_app import ChatApp
    src = inspect.getsource(ChatApp._render_detector_count)
    assert "iter_registered_detectors" in src
    # The old heuristic
    # ``iter_modules`` should
    # not be referenced any
    # more.
    assert "iter_modules" not in src
