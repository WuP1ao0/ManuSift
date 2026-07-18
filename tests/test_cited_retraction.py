"""Tests for the OpenAlex cited-retraction detector (P2.2).

The detector queries ``api.openalex.org/works/doi:<doi>`` for
every DOI in the reference list and emits a ``high`` finding
when OpenAlex reports ``is_retracted: true``. We mock the HTTP
layer so the tests never touch the network.

Guarantees:

  1. ``_extract_dois`` pulls normalized DOIs out of
     reference-shaped lines and dedupes them.
  2. With ``openalex_enabled=False`` the detector returns an
     empty result and makes zero network calls.
  3. A reference whose DOI resolves to a retracted work
     produces a ``high`` finding.
  4. A reference whose DOI resolves to a non-retracted work
     produces no finding.
  5. A network error produces no finding and does not crash
     the detector (a flaky network must not manufacture a
     retraction signal).
  6. An OpenAlex 404 (DOI not indexed) produces no finding.
  7. The on-disk cache prevents a second HTTP call for a DOI
     seen before.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from manusift.config import Settings
from manusift.contracts import ParsedDoc, TextBlock
from manusift.detectors.cited_retraction import (
    CitedRetractionDetector,
    _extract_dois,
)


def _doc_with(text: str) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-p22",
        source_path="x.pdf",
        text_blocks=[
            TextBlock(text=text, page=0, bbox=(0, 0, 0, 0))
        ],
        images=[],
        metadata={},
    )


_REFS = (
    "References\n"
    "[1] Smith J. Fraudulent results. J Imaginary Sci. 2019. "
    "doi:10.1234/retracted.paper\n"
    "[2] Jones K. Solid work. J Real Sci. 2020. "
    "doi:10.5678/fine.paper\n"
)


class _FakeResp:
    """Tiny stand-in for ``httpx.Response``."""
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body
    def json(self) -> Any:
        return self._body


class _FakeClient:
    """Scripts one response per ``.get`` call and records every
    call so tests can assert on the HTTP-call count."""
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []
    def get(self, url, params=None, headers=None):  # type: ignore[no-untyped-def]
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("FakeClient ran out of responses")
        return self._responses.pop(0)
    def close(self) -> None:
        pass


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        openalex_enabled=enabled,
    )


# ---------- 1. DOI extraction ----------

def test_extract_dois_normalizes_and_dedupes() -> None:
    """DOIs are lowercased, trailing sentence punctuation is
    stripped, and duplicates collapse to one entry."""
    text = (
        "References\n"
        "[1] Smith J. Paper A. J X. 2019. doi:10.1234/ABC.Def\n"
        "[2] Jones K. Paper B. J Y. 2020. 10.1234/abc.def.\n"
    )
    assert _extract_dois(text) == ["10.1234/abc.def"]


def test_extract_dois_ignores_text_without_references() -> None:
    """No reference-shaped lines -> no DOIs, no lookups."""
    assert _extract_dois("just a paragraph of prose") == []


# ---------- 2. opt-in gate ----------

def test_detector_disabled_makes_no_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default-off gate: zero findings, zero HTTP calls even
    when the reference list is full of DOIs."""
    fake = _FakeClient([])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = CitedRetractionDetector()
    res = d.run(
        _doc_with(_REFS),
        settings=_settings(tmp_path, enabled=False),
    )
    assert res.ok
    assert res.findings == []
    assert fake.calls == []


# ---------- 3 + 4. retracted / clean ----------

def test_detector_flags_retracted_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OpenAlex says is_retracted=true for the first DOI ->
    one ``high`` finding naming that DOI; the clean DOI stays
    silent."""
    fake = _FakeClient([
        _FakeResp(200, {
            "id": "https://openalex.org/W1",
            "title": "Fraudulent results",
            "is_retracted": True,
        }),
        _FakeResp(200, {
            "id": "https://openalex.org/W2",
            "title": "Solid work",
            "is_retracted": False,
        }),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = CitedRetractionDetector()
    res = d.run(_doc_with(_REFS), settings=_settings(tmp_path))
    assert res.ok
    highs = [f for f in res.findings if f.severity == "high"]
    assert len(highs) == 1
    assert "10.1234/retracted.paper" in highs[0].title
    assert len(fake.calls) == 2


def test_detector_clean_reference_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No retracted works -> no findings at all."""
    fake = _FakeClient([
        _FakeResp(200, {"is_retracted": False, "title": "A"}),
        _FakeResp(200, {"is_retracted": False, "title": "B"}),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = CitedRetractionDetector()
    res = d.run(_doc_with(_REFS), settings=_settings(tmp_path))
    assert res.ok
    assert res.findings == []


# ---------- 5. network errors ----------

def test_detector_swallows_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection failure must not crash the detector and
    must not produce any finding -- we cannot tell a retracted
    paper from an unreachable API."""
    class _ErrClient:
        def get(self, *a, **kw):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("simulated network down")
        def close(self) -> None:
            pass
    monkeypatch.setattr(httpx, "Client", lambda **kw: _ErrClient())
    d = CitedRetractionDetector()
    res = d.run(_doc_with(_REFS), settings=_settings(tmp_path))
    assert res.ok
    assert res.findings == []


# ---------- 6. OpenAlex 404 ----------

def test_detector_ignores_unindexed_doi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 404 from OpenAlex means the DOI is not indexed there.
    That is not a finding (citation_network already covers
    "reference does not exist" via Crossref)."""
    fake = _FakeClient([
        _FakeResp(404),
        _FakeResp(200, {"is_retracted": False, "title": "B"}),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = CitedRetractionDetector()
    res = d.run(_doc_with(_REFS), settings=_settings(tmp_path))
    assert res.ok
    assert res.findings == []


# ---------- 7. cache ----------

def test_detector_uses_cache_on_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First run hits OpenAlex per DOI; the second run over the
    same reference list is served entirely from
    ``openalex_cache.json`` and makes no HTTP calls."""
    fake = _FakeClient([
        _FakeResp(200, {
            "id": "https://openalex.org/W1",
            "title": "Fraudulent results",
            "is_retracted": True,
        }),
        _FakeResp(200, {"is_retracted": False, "title": "B"}),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = CitedRetractionDetector()
    settings = _settings(tmp_path)
    res1 = d.run(_doc_with(_REFS), settings=settings)
    assert len(fake.calls) == 2
    res2 = d.run(_doc_with(_REFS), settings=settings)
    assert len(fake.calls) == 2, (
        "cache should have prevented further HTTP calls"
    )
    # The cached run still reports the retracted citation.
    assert any(f.severity == "high" for f in res1.findings)
    assert any(f.severity == "high" for f in res2.findings)


# ---------- 8. module surface ----------

def test_detector_module_exports() -> None:
    """The detector class is importable from
    ``manusift.detectors`` and from
    ``manusift.detectors.cited_retraction``."""
    from manusift.detectors import CitedRetractionDetector as A
    from manusift.detectors.cited_retraction import (
        CitedRetractionDetector as B,
    )
    assert A is B
    assert A.name == "cited_retraction"
