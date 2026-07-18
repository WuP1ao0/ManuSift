"""Tests for the Crossref citation-network detector (P2-D1).

P2-D1 hits ``api.crossref.org/works`` once per
candidate citation and reports a ``medium``
finding when the Crossref match score is below
2/3 (severity capped at ``medium`` since P2.1 —
top-1-only retrieval cannot separate fabrication
from retrieval noise). We
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
     not match returns a ``medium`` finding.
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
    ``medium`` finding is raised (P2.1: the
    score<2 branch is capped at ``medium``;
    top-1-only evidence cannot distinguish
    fabrication from retrieval noise)."""
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
        f.severity == "medium" for f in res.findings
    )
    assert not any(
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
    ``<workspace_dir.parent>/cache/crossref_cache.json``.
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


# ---------- 9. offline replay mode (P2.1) ----------

def _seed_cache(tmp_path: Path, entries: dict) -> Path:
    """Write a ``crossref_cache.json`` in the shared cache
    dir the way ``_save_cache`` does, so the detector sees it
    as a pre-populated cache."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "crossref_cache.json"
    cache_file.write_text(
        json.dumps(entries, ensure_ascii=False), encoding="utf-8"
    )
    return cache_file


class _NoNetworkClient:
    """Any HTTP attempt in offline mode is a bug."""
    def get(self, *a, **kw):  # type: ignore[no-untyped-def]
        raise AssertionError("offline mode must not touch the network")
    def close(self) -> None:
        pass


def test_offline_cache_miss_is_not_testable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MANUSIFT_CROSSREF_OFFLINE=1`` + cache miss:
    no network call, and the citation is recorded as
    an ``info`` finding with ``kind == 'not_testable'``
    (never ``high``) so CI stays reproducible."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_CROSSREF_OFFLINE", "1")
    monkeypatch.setattr(httpx, "Client", lambda timeout: _NoNetworkClient())
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020] for context"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.severity == "info"
    assert f.raw.get("kind") == "not_testable"
    assert f.raw.get("offline") is True
    assert f.raw.get("cache_hit") is False


def test_offline_cache_hit_scores_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline mode with a cache hit: the cached
    Crossref item is scored exactly like an online
    hit — here the cached record mismatches the
    citation (score 0/3) so a ``medium`` finding
    is produced with zero network calls."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_CROSSREF_OFFLINE", "1")
    monkeypatch.setattr(httpx, "Client", lambda timeout: _NoNetworkClient())
    _seed_cache(tmp_path, {
        "smith 2020": {
            "item": {
                "title": ["Quantum Computing for Climate Models"],
                "issued": {"date-parts": [[2018]]},
                "author": [{"family": "Garcia"}],
            },
            "ts": 1_700_000_000.0,
        }
    })
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020] for context"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert any(f.severity == "medium" for f in res.findings)
    assert not any(f.severity == "high" for f in res.findings)


def test_offline_cache_hit_clean_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline mode with a cache hit that matches
    the citation (score >= 2) yields no finding."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_CROSSREF_OFFLINE", "1")
    monkeypatch.setattr(httpx, "Client", lambda timeout: _NoNetworkClient())
    _seed_cache(tmp_path, {
        "smith 2020": {
            "item": {
                "title": ["Foundations of Smith 2020 quantum theory"],
                "issued": {"date-parts": [[2020]]},
                "author": [{"family": "Smith"}],
            },
            "ts": 1_700_000_000.0,
        }
    })
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020]"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert res.findings == []


def test_offline_bypasses_cache_ttl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale entry (``ts`` far in the past, TTL=1s)
    is still used in offline mode — replay against a
    pinned cache must be deterministic regardless of
    wall clock. The stale entry would force a network
    re-fetch online; here it must not."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("MANUSIFT_CROSSREF_OFFLINE", "1")
    monkeypatch.setenv("MANUSIFT_CITATION_CACHE_TTL", "1")
    monkeypatch.setattr(httpx, "Client", lambda timeout: _NoNetworkClient())
    _seed_cache(tmp_path, {
        "smith 2020": {
            "item": {
                "title": ["Foundations of Smith 2020 quantum theory"],
                "issued": {"date-parts": [[2020]]},
                "author": [{"family": "Smith"}],
            },
            "ts": 1_000_000.0,  # ancient -> stale under TTL=1s
        }
    })
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020]"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert res.findings == []


def test_online_cache_replay_uses_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plain replay (offline flag OFF) with a fresh
    pre-seeded cache: the detector answers purely
    from the cache and performs zero HTTP calls."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("MANUSIFT_CROSSREF_OFFLINE", raising=False)
    monkeypatch.setattr(httpx, "Client", lambda timeout: _NoNetworkClient())
    import time as _time
    _seed_cache(tmp_path, {
        "smith 2020": {
            "item": {
                "title": ["Foundations of Smith 2020 quantum theory"],
                "issued": {"date-parts": [[2020]]},
                "author": [{"family": "Smith"}],
            },
            "ts": _time.time(),
        }
    })
    d = CitationNetworkDetector()
    res = d.run(
        _doc_with("see [Smith 2020]"),
        settings=_settings(tmp_path),
    )
    assert res.ok
    assert res.findings == []


# ---------- 10. match-score boundary cases ----------

def _boundary_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    crossref_item: dict,
    text: str,
) -> list:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    fake = _FakeClient([
        _FakeResp(200, {"message": {"items": [crossref_item]}})
    ])
    monkeypatch.setattr(httpx, "Client", lambda timeout: fake)
    d = CitationNetworkDetector()
    res = d.run(_doc_with(text), settings=_settings(tmp_path))
    assert res.ok
    return res.findings


def test_match_score_exactly_two_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Score 2/3 (author + year match, no title token
    overlap) is the acceptance threshold — no finding."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Completely Unrelated Title Words Here"],
            "issued": {"date-parts": [[2020]]},
            "author": [{"family": "Smith"}],
        },
        "see [Smith 2020]",
    )
    assert findings == []


def test_match_score_one_flags_medium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Score 1/3 (only the author matches against a
    wrong-work top-1 retrieval; the year is two
    years off so the +/-1 tolerance does not apply)
    stays below the threshold and raises a
    ``medium`` finding — the P2.1 severity cap for
    the undifferentiable fabrication-vs-retrieval-
    noise class."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Completely Unrelated Title Words Here"],
            "issued": {"date-parts": [[2018]]},
            "author": [{"family": "Smith"}],
        },
        "see [Smith 2020]",
    )
    assert any(f.severity == "medium" for f in findings)
    assert not any(f.severity == "high" for f in findings)


def test_grey_literature_institutional_citation_downgraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2.1 FP governance: an all-caps institutional
    author (``(FAO1998)``) is grey literature that
    Crossref does not index. Even when Crossref
    returns a low-scoring unrelated top hit, the
    verdict is ``info`` (``kind='grey_literature'``),
    never ``high`` — legitimate papers cite such
    reports routinely."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Classifying paleosols of the world"],
            "issued": {"date-parts": [[1998]]},
            "author": [{"family": "Smith"}],
        },
        "as classified by (FAO1998) previously",
    )
    assert findings, "expected an info finding"
    assert not any(f.severity == "high" for f in findings)
    assert any(
        f.severity == "info" and f.raw.get("kind") == "grey_literature"
        for f in findings
    )


def test_personal_surname_not_treated_as_grey_literature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A normal surname citation with a low score
    still raises the standard score<2 ``medium``
    finding — the grey-literature info downgrade
    only applies to all-caps institutional author
    tokens."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Quantum Computing for Climate Models"],
            "issued": {"date-parts": [[2018]]},
            "author": [{"family": "Garcia"}],
        },
        "see [Smith 2020] for context",
    )
    assert any(f.severity == "medium" for f in findings)
    assert not any(f.severity == "high" for f in findings)


def test_year_tolerance_absorbs_preprint_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2.1: the year check tolerates +/- 1 to absorb
    preprint-vs-version-of-record drift. Citation
    year 2020 against a 2019 Crossref record with a
    matching author scores 2/3 -> no finding."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Completely Unrelated Title Words Here"],
            "issued": {"date-parts": [[2019]]},
            "author": [{"family": "Smith"}],
        },
        "see [Smith 2020]",
    )
    assert findings == []


def test_author_match_is_case_insensitive_all_authors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2.1 FP fix: ``(Goodwin-gill and Mcadam, 2017)``
    must match Crossref family name ``Goodwin-Gill``
    even when it is not the first listed author —
    case-insensitive comparison across all authors."""
    findings = _boundary_run(
        tmp_path,
        monkeypatch,
        {
            "title": ["Completely Unrelated Title Words Here"],
            "issued": {"date-parts": [[2017]]},
            "author": [
                {"family": "McAdam"},
                {"family": "Goodwin-Gill"},
            ],
        },
        "see (Goodwin-gill and Mcadam, 2017)",
    )
    assert findings == []
