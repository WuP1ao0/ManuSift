"""Tests for the detector entry-points plugin registry (Step H4).

Borrowed design from OpenHands' plugin model: third-party
detectors are discovered through the standard Python
``importlib.metadata.entry_points`` API. To test this without
actually installing a real third-party package we use
``monkeypatch.setattr(metadata, \"entry_points\", ...)`` to
inject a fake entry-point table. This is the standard testing
pattern (used by pytest itself, pluggy, etc.).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from manusift.contracts import Finding, ParsedDoc
from manusift.detectors.base import DetectorResult
from manusift.detectors.registry import (
    ENTRY_POINT_GROUP,
    entry_point_names,
    iter_entrypoint_detectors,
)


# ---------- helpers ----------

def _doc() -> ParsedDoc:
    return ParsedDoc(
        trace_id="t",
        source_path="dummy.pdf",
        text_blocks=[],
        images=[],
        metadata={},
    )


def _finding(title: str = "t") -> Finding:
    return Finding.make(
        trace_id="t",
        detector="x",
        severity="low",
        title=title,
        evidence="",
        location="",
    )


class _FakeCitationDetector:
    """A pretend third-party detector. Mirrors the contract a
    real plugin author would implement."""
    name = "citation_network"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=[_finding("fake-citation")],
            duration_ms=42,
        )


def _ep(cls):
    """Wrap a class as a fake EntryPoint."""
    return SimpleNamespace(name=cls.name, value=cls.__module__ + ":" + cls.__name__, load=lambda: cls)


# ---------- 1. no entry points installed -> empty iter ----------

def test_no_entry_points_yields_nothing(monkeypatch) -> None:
    """An environment with no plugins returns no detectors."""
    import importlib.metadata as md

    def fake_entry_points(*, group: str) -> list:
        return []

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    assert list(iter_entrypoint_detectors()) == []


# ---------- 2. one fake entry point is yielded ----------

def test_fake_entry_point_is_loaded(monkeypatch) -> None:
    """Inject one fake entry point, confirm it is instantiated
    and yielded in the right order."""
    import importlib.metadata as md

    def fake_entry_points(*, group: str) -> list:
        assert group == ENTRY_POINT_GROUP
        return [_ep(_FakeCitationDetector)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    detectors = list(iter_entrypoint_detectors())
    assert len(detectors) == 1
    assert isinstance(detectors[0], _FakeCitationDetector)
    assert detectors[0].name == "citation_network"


# ---------- 3. broken entry point is logged and skipped ----------

def test_broken_entry_point_does_not_crash(monkeypatch, caplog) -> None:
    """A plugin whose .load() raises must be skipped, never
    crash the pipeline."""
    import importlib.metadata as md
    import logging

    def fake_entry_points(*, group: str) -> list:
        bad = SimpleNamespace(
            name="bad_plugin",
            value="doesnt:exist",
            load=lambda: (_ for _ in ()).throw(ImportError("not installed")),
        )
        return [bad]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    with caplog.at_level(logging.WARNING):
        detectors = list(iter_entrypoint_detectors())
    assert detectors == []
    # The failure is recorded so a user can see what went wrong.
    # caplog does not see structured 'extra' fields, so we look
    # at the message ("could not load entry point") which is the
    # signal that *something* was rejected.
    assert any(
        "could not load entry point" in r.getMessage()
        for r in caplog.records
    )


# ---------- 4. entry_point_names() returns names only ----------

def test_entry_point_names_returns_strings(monkeypatch) -> None:
    import importlib.metadata as md

    def fake_entry_points(*, group: str) -> list:
        return [_ep(_FakeCitationDetector)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    assert entry_point_names() == ["citation_network"]


# ---------- 5. end-to-end: a plugin detector runs inside the pipeline ----------

def test_plugin_detector_runs_inside_pipeline(tmp_path: Path, monkeypatch) -> None:
    """Install a fake plugin, then run the real pipeline. The
    plugin detector must execute and its findings must end up in
    findings.json. This is the contract a third-party author
    relies on."""
    import importlib.metadata as md
    from manusift.pipeline import run_pipeline
    from manusift.contracts import JobState

    def fake_entry_points(*, group: str) -> list:
        return [_ep(_FakeCitationDetector)]

    monkeypatch.setattr(md, "entry_points", fake_entry_points)
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(
        "manusift.pipeline._BUILTIN_DETECTOR_CLASS_NAMES",
        [],
    )
    (tmp_path / "jobs").mkdir()

    import fitz  # type: ignore[import-not-found]
    pdf_path = tmp_path / "tiny.pdf"
    pdf = fitz.open()
    pdf.new_page(width=400, height=200)
    pdf[0].insert_text((40, 40), "Hello")
    pdf.save(str(pdf_path))
    pdf.close()

    from manusift.workspace import JobPaths
    tid = "t-plugin"
    paths = JobPaths.for_trace(tid, tmp_path / "jobs")
    paths.ensure()
    state = JobState(trace_id=tid, status="queued", source_filename="tiny.pdf")
    run_pipeline(pdf_path, paths, state)

    import json
    payload = json.loads(paths.findings_json.read_text(encoding="utf-8"))
    detectors_run = payload.get("detectors_run", [])
    # The plugin detector was discovered and ran.
    assert "citation_network" in detectors_run
    titles = [f["title"] for f in payload["findings"]]
    assert "fake-citation" in titles
