"""Tests for the tool entry-points plugin registry (Step J4).

Mirrors the design of the detector registry (H4) but for
the agent's tool surface. The two are siblings: a third-party
package can ship a Detector (which the pipeline runs) or a
Tool (which the agent can call) or both.

Borrowed design: the leaked Claude Code v2.1.88 source uses
a ``.claude-plugin/plugin.json`` file-system convention. We
re-implement the same idea with Python's
``importlib.metadata.entry_points`` — a third-party package
declares a one-line entry point in its ``pyproject.toml``,
the registry picks it up at runtime.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from manusift.tools import get_tool
from manusift.tools.registry import (
    ENTRY_POINT_GROUP,
    iter_registered_tools,
    tool_names,
)


# ---------- helpers ----------

def _make_ep(name: str, target: Any) -> SimpleNamespace:
    """Build a SimpleNamespace that quacks like an
    ``importlib.metadata.EntryPoint`` for our purposes.
    Real EntryPoint objects have a ``.load()`` method that
    returns the registered object. We use SimpleNamespace
    to keep the test self-contained."""
    return SimpleNamespace(name=name, value="fake:module", load=lambda: target)


# ---------- 1. No third-party tools -> just built-ins ----------

def test_no_third_party_tools_yields_builtins_only() -> None:
    """Without any third-party entry points installed,
    the registry returns the 4 built-in detector tools."""
    names = sorted(t.name for t in iter_registered_tools())
    assert "metadata" in names
    assert "image_dup" in names
    # The count is at least 4 (the built-ins). It might
    # be more if a test-installed fixture is in the env.
    assert len(names) >= 4


# ---------- 2. Fake entry-point loader ----------

def test_fake_entry_point_is_loaded(monkeypatch) -> None:
    """Inject one fake entry point. Confirm it is
    instantiated and yielded in the registry."""
    import importlib.metadata as md

    class FakeCitationTool:
        name = "citation_network"

        def description(self) -> str:
            return "Fake citation-graph tool."

        def input_schema(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}}

        def execute(self, input: dict[str, Any], ctx: Any) -> str:
            return "fake result"

    def fake_entry_points(*, group: str) -> list:
        assert group == ENTRY_POINT_GROUP
        return [_make_ep("citation_network", FakeCitationTool)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    names = sorted(t.name for t in iter_registered_tools())
    assert "citation_network" in names


# ---------- 3. Broken entry point is logged and skipped ----------

def test_broken_entry_point_does_not_crash(
    monkeypatch, caplog
) -> None:
    """A plugin whose load() raises must be skipped, not
    crash the registry."""
    import importlib.metadata as md
    import logging

    def fake_entry_points(*, group: str) -> list:
        def _raise() -> Any:
            raise ImportError("not installed")
        return [_make_ep("bad_tool", _raise())]

    # The lambda pattern above doesn't work for raising
    # on .load(). Use a different shape.
    def fake_entry_points_2(*, group: str) -> list:
        ep = SimpleNamespace(
            name="bad_tool",
            value="doesnt:exist",
            load=lambda: (_ for _ in ()).throw(
                ImportError("not installed")
            ),
        )
        return [ep]

    monkeypatch.setattr(md, "entry_points", fake_entry_points_2)
    with caplog.at_level(logging.WARNING):
        list(iter_registered_tools())
    assert any(
        "could not load tool entry point" in r.getMessage()
        for r in caplog.records
    )


# ---------- 4. Entry point without the Tool protocol is skipped ----------

def test_entry_point_missing_protocol_is_skipped(
    monkeypatch, caplog
) -> None:
    """A class that does not have name/description/
    input_schema/execute must be rejected."""
    import importlib.metadata as md
    import logging

    class NotATool:
        # Missing description / input_schema / execute.
        name = "not_a_tool"

    def fake_entry_points(*, group: str) -> list:
        return [_make_ep("not_a_tool", NotATool)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    with caplog.at_level(logging.WARNING):
        list(iter_registered_tools())
    assert any(
        "does not satisfy Tool protocol" in r.getMessage()
        for r in caplog.records
    )


# ---------- 5. tool_names() returns strings only ----------

def test_tool_names_returns_strings() -> None:
    """The diagnostic helper returns a flat list of names
    — useful for the TUI's tool-picker UI and for /api/tools."""
    names = tool_names()
    assert all(isinstance(n, str) and n for n in names)


# ---------- 6. END-TO-END: a real tool is registered and listed ----------

def test_real_fake_tool_round_trip(monkeypatch) -> None:
    """A tool class that has the full Tool protocol is
    registered, instantiated, and runnable. This is the
    contract every third-party plugin will rely on."""
    import importlib.metadata as md

    call_count = 0

    class GreetingTool:
        name = "greeting"

        def description(self) -> str:
            return "Says hello."

        def input_schema(self) -> dict[str, Any]:
            return {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }

        def execute(self, input: dict[str, Any], ctx: Any) -> str:
            nonlocal call_count
            call_count += 1
            return "hi!"

    def fake_entry_points(*, group: str) -> list:
        return [_make_ep("greeting", GreetingTool)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)

    tool = get_tool("greeting")
    assert tool is not None
    assert tool.name == "greeting"
    out = tool.execute({}, None)  # type: ignore[arg-type]
    assert out == "hi!"
    assert call_count == 1


# ---------- 7. iterator is fresh per call ----------

def test_iter_registered_tools_yields_each_call(monkeypatch) -> None:
    """A second call to iter_registered_tools() re-reads
    the entry_points table. We confirm by injecting a
    different fake ep between two calls."""
    import importlib.metadata as md

    class ToolA:
        name = "a"
        def description(self): return "a"
        def input_schema(self): return {}
        def execute(self, i, c): return "A"

    class ToolB:
        name = "b"
        def description(self): return "b"
        def input_schema(self): return {}
        def execute(self, i, c): return "B"

    # First call: only ToolA.
    monkeypatch.setattr(
        md, "entry_points", lambda *, group: [_make_ep("a", ToolA)]
    )
    names1 = sorted(t.name for t in iter_registered_tools())
    assert "a" in names1
    # Second call: only ToolB.
    monkeypatch.setattr(
        md, "entry_points", lambda *, group: [_make_ep("b", ToolB)]
    )
    names2 = sorted(t.name for t in iter_registered_tools())
    assert "b" in names2
