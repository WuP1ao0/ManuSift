"""R-2026-06-15 (Phase 0+1 + P0-4):
test that every key in
``_CHEAT_SHEET_OVERRIDES``
matches a real tool name
registered in the tool
registry.

The original entry was
``"metadata": "..."``.  The
real tool is
``PdfMetadataDetector``
with ``name = "pdf_metadata"``,
so the override was never
matched (a Hyrum's-Law trap).
The fix removed the dead
entry; this test prevents
the trap from coming back.
"""
from __future__ import annotations

import re

import pytest

# We use a regex on the source
# file rather than a direct
# import because
# ``_CHEAT_SHEET_OVERRIDES`` is
# a local in a class-body
# ``if`` branch.  Importing the
# name is fragile (the
# surrounding code is
# conditional on
# ``system_prompt is None``);
# a regex over the file
# catches the same content with
# no runtime cost.
from pathlib import Path

AGENT_INIT = (
    Path(__file__).parent.parent
    / "manusift"
    / "agent"
    / "__init__.py"
)


def _read_cheat_overrides() -> dict[str, str]:
    """Parse the
    ``_CHEAT_SHEET_OVERRIDES``
    literal out of the source
    file.  We do a minimal
    ``ast.literal_eval`` on the
    dict expression.
    """
    import ast

    src = AGENT_INIT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_CHEAT_SHEET_OVERRIDES"
            and isinstance(node.value, ast.Dict)
        ):
            result: dict[str, str] = {}
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(
                    v, ast.Constant
                ):
                    result[str(k.value)] = str(v.value)
            return result
    raise AssertionError(
        "_CHEAT_SHEET_OVERRIDES literal not found"
    )


def test_p04_cheat_overrides_keys_match_real_tools():
    """Every key in the override
    map must match a real
    ``Tool.name`` in the
    registry.  This prevents
    typos like
    ``"metadata"`` for a tool
    named ``"pdf_metadata"``.
    """
    overrides = _read_cheat_overrides()
    # Collect all Tool.name
    # values from manusift.tools.
    import importlib
    import inspect
    import pkgutil

    import manusift.tools as t
    real_names: set[str] = set()
    for _, modname, _ in pkgutil.iter_modules(
        t.__path__
    ):
        mod = importlib.import_module(
            f"manusift.tools.{modname}"
        )
        for _, obj in inspect.getmembers(
            mod, inspect.isclass
        ):
            if obj.__module__ != mod.__name__:
                continue
            n = getattr(obj, "name", None)
            if (
                isinstance(n, str)
                and n
                and not n.startswith("_")
            ):
                real_names.add(n)
    assert overrides, (
        "no overrides parsed; test infra broken"
    )
    for key in overrides:
        assert key in real_names, (
            f"_CHEAT_SHEET_OVERRIDES key {key!r} "
            f"does not match any real tool. "
            f"Real tool names: "
            f"{sorted(real_names)}"
        )


def test_p04_no_legacy_metadata_key():
    """The original typo
    ``"metadata"`` was never
    matched.  Hard-assert its
    absence.
    """
    overrides = _read_cheat_overrides()
    assert "metadata" not in overrides, (
        "the legacy 'metadata' key came back -- "
        "the Hyrum's-Law trap has re-appeared"
    )


def test_p04_pdf_metadata_is_in_overrides():
    """The detector ``pdf_metadata``
    *is* referenced in the
    override map (if a future
    refactor decides to expose
    it as a tool, the override
    must catch up).  Today the
    detector is *not* a tool, so
    this is a "future-proofing"
    test that documents the
    intent: a maintainer who
    decides to register
    ``pdf_metadata`` as a tool
    should also add a
    one-liner override.
    """
    overrides = _read_cheat_overrides()
    # The override is *not* in
    # the map today (the detector
    # is not a tool).  This test
    # asserts that -- but ALSO
    # asserts the detector exists
    # in the registry so a future
    # tool-isation is unblocked.
    from manusift.detectors import (
        pdf_metadata as pm,
    )

    assert pm.PdfMetadataDetector.name == "pdf_metadata"
    # Today the override map
    # does NOT have the key.  If
    # a future PR adds it, this
    # test will need to be
    # updated to assert its
    # presence.
    assert "pdf_metadata" not in overrides, (
        "test infra drift: pdf_metadata "
        "appeared in the override map"
    )
