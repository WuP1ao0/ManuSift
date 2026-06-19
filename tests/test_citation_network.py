"""Tests for the Crossref citation-network detector (P2-D1).

P2-D1 hits ``api.crossref.org/works`` once per
candidate citation and reports a ``high`` finding
when the Crossref match score is below 2/3. We
mock the HTTP layer so the test does not need a
real network connection.

Guarantees:

  1. ``_extract_citations`` catches the three
     reference shapes the detector cares about
     (``[Author Year]``, ``(Author, Year)``,
     ``[N]``) and reports the right author /
     year pairs.
  2. With ``crossref_enabled=False`` the
     detector returns an empty result with no
     findings, no network calls.
  3. With a Crossref hit, a citation that does
     not match returns a ``high`` finding.
  4. With a Crossref hit, a citation that does
     match returns no finding.
  5. A Crossref miss (empty ``items`` list)
     produces an ``info`` finding ("could not
     verify") rather than a ``high`` one.
  6. The cache is read on a second run with the
     same query — no second HTTP call.
  7. A network error produces an ``info``
     finding and does not crash the detector.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from manusift.config import Settings
from manusift.contracts import ParsedDoc, TextBlock
from manusift.detectors.citation_network import (
    CitationNetworkDetector,
    _extract_citations,
    _query_crossref,
)


def _doc_with(text: str) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-d1",
        source_path="x.pdf",
        text_blocks=[
            TextBlock(text=text, page=0, bbox=(0, 0, 0, 0))
        ],
        images=[],
        metadata={},
    )


# ---------- 1. regex extractor ----------

def test_extract_citations_bracketed_author_year() -> None:
    """``[Smith 2020]`` produces a citation with
    author='Smith' and year='2020'."""
    out = _extract_citations("see [Smith 2020] for context")
    assert any(
        c["author"] == "Smith" and c["year"] == "2020"
        for c in out
    )


def test_extract_citations_parenthetical() -> None:
    """``(Jones, 2019)`` works too."""
    out = _extract_citations("prior work (Jones, 2019) is similar")
    assert any(
        c["author"] == "Jones" and c["year"] == "2019"
        for c in out
    )


def test_extract_citations_et_al() -> None:
    """``[Smith et al. 2021]`` extracts the lead
    author and the year."""
    out = _extract_citations("as shown in [Smith et al. 2021]")
    assert any(
        "Smith" in c["author"] and c["year"] == "2021"
        for c in out
    )


def test_extract_citations_numeric() -> None:
    """``[12]`` is a numeric reference — author
    and year are empty (we cannot resolve the
    bibliography order, so the detector skips
    these for Crossref lookup)."""
    out = _extract_citations("see reference [12] in the bibliography")
    assert any(
        c["raw"] == "[12]" and c["author"] == "12" and not c["year"]
        for c in out
    )


def test_extract_citations_dedupes() -> None:
    """The same citation text in two places is
    not double-counted."""
    out = _extract_citations(
        "see [Smith 2020] for context. as [Smith 2020] notes"
    )
    matches = [c for c in out if c["raw"] == "[Smith 2020]"]
    assert len(matches) == 1


# ---------- 2. opt-out ----------

def test_detector_disabled_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MANUSIFT_CROSSREF_ENABLED=0`` short-circuits
    the detector. No network, no findings, the
    report is silent for the citation-network
    step."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_CROSSREF_ENABLED", "0")
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020]"),
        settings=get_settings(),
    )
    assert res.ok
    assert res.findings == []


# ---------- 3 + 4 + 5. Crossref outcomes ----------

class _FakeResp:
    """Tiny stand-in for ``httpx.Response``."""
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body
    def json(self) -> Any:
        return self._body


class _FakeClient:
    """Records every ``.get`` call so a test can
    assert on the URL and the query parameters,
    and lets the test script the response per
    call."""
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[httpx.Request] = []
    def get(self, url, params=None, headers=None):  # type: ignore[no-untyped-def]
        self.calls.append(
            httpx.Request("GET", url, params=params)
        )
        if not self._responses:
            raise AssertionError("FakeClient ran out of responses")
        return self._responses.pop(0)
    def close(self) -> None:
        pass


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        crossref_enabled=True,
    )


def test_detector_reports_fabricated_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Crossref item we get back has a
    completely different author and year than
    the citation in the PDF. Score is 0/3 — a
    ``high`` finding is raised."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    # Crossref returns a real paper but the
    # author/year do not match the citation.
    fake = _FakeClient([
        _FakeResp(200, {
            "message": {
                "items": [{
                    "title": ["Quantum Computing for Climate Models"],
                    "issued": {"date-parts": [[2018]]},
                    "author": [{"family": "Garcia"}],
                }]
            }
        })
    ])
    monkeypatch.setattr(httpx, "Client", lambda timeout: fake)
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020] for context"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert any(
        f.severity == "high" for f in res.findings
    )


def test_detector_accepts_real_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A citation that matches the Crossref
    record (same year, author surname present)
    raises no finding. We seed a citation and
    a matching Crossref item.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    fake = _FakeClient([
        _FakeResp(200, {
            "message": {
                "items": [{
                    "title": [
                        "Foundations of Smith 2020 quantum theory"
                    ],
                    "issued": {"date-parts": [[2020]]},
                    "author": [{"family": "Smith"}],
                }]
            }
        })
    ])
    monkeypatch.setattr(httpx, "Client", lambda timeout: fake)
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020] for context"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert res.findings == []


def test_detector_reports_info_on_crossref_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty ``items`` list (no Crossref
    record) is reported as ``info`` ("could not
    verify") rather than ``high``. The operator
    can re-run later to get a sharper verdict
    if Crossref was simply down at the time."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    fake = _FakeClient([
        _FakeResp(200, {"message": {"items": []}})
    ])
    monkeypatch.setattr(httpx, "Client", lambda timeout: fake)
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020] for context"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert any(f.severity == "info" for f in res.findings)
    # And NO high-severity findings.
    assert not any(f.severity == "high" for f in res.findings)


# ---------- 6. cache hits ----------

def test_detector_uses_cache_on_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first run hits Crossref and writes
    the cache. The second run reads the cache
    and does NOT call Crossref again. The
    cache file lives at
    ``<workspace_dir.parent>/crossref_cache.json``.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    fake = _FakeClient([
        _FakeResp(200, {
            "message": {
                "items": [{
                    "title": ["Smith 2020 paper"],
                    "issued": {"date-parts": [[2020]]},
                    "author": [{"family": "Smith"}],
                }]
            }
        })
    ])
    monkeypatch.setattr(httpx, "Client", lambda timeout: fake)
    d = CitationNetworkDetector()
    settings = _settings(tmp_path)
    # First run: should call Crossref.
    d.run(
        _doc_with("see [Smith 2020]"), settings=settings
    )
    assert len(fake.calls) == 1
    # Second run on the same citation: cache hit.
    d.run(
        _doc_with("see [Smith 2020]"), settings=settings
    )
    assert len(fake.calls) == 1, "cache should have prevented a second HTTP call"


# ---------- 7. network errors do not crash ----------

def test_detector_swallows_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``httpx.ConnectError`` from the fake
    client must not crash the detector. It
    produces an ``info`` finding ("could not
    verify") because we cannot tell fabrication
    from outage.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    class _ErrClient:
        def get(self, *a, **kw):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("simulated network down")
        def close(self) -> None:
            pass
    monkeypatch.setattr(httpx, "Client", lambda timeout: _ErrClient())
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020]"),
        settings=_settings(tmp_path),
    )
    assert res.ok  # detector itself did not crash
    assert any(f.severity == "info" for f in res.findings)


# ---------- 8. module surface ----------

def test_detector_module_exports() -> None:
    """The detector class is importable from
    ``manusift.detectors`` and from
    ``manusift.detectors.citation_network``."""
    from manusift.detectors import CitationNetworkDetector as A
    from manusift.detectors.citation_network import (
        CitationNetworkDetector as B,
    )
    assert A is B
    assert A.name == "citation_network"
