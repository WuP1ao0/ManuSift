"""Tests for the data-availability link-resolution step (P2.3).

When ``MANUSIFT_DAS_RESOLUTION_ENABLED`` is on, the
``data_availability_concern`` detector resolves the DOI/URL
links in the data-availability statement against their
repository landing pages. Severity discipline:

  * confirmed dead link (404/410, or a repository soft-404
    page) -> ``medium``;
  * network failure / timeout / bot-blocking -> ``info``;
  * resolvable link -> no finding;
  * statement without links -> no network calls;
  * gate off -> no network calls.

All HTTP is mocked; the tests never touch the network.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from manusift.config import Settings
from manusift.contracts import ParsedDoc, TextBlock
from manusift.detectors.data_availability_concern import (
    DataAvailabilityConcernDetector,
    _extract_statement_links,
)


def _doc_with(text: str) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-p23",
        source_path="x.pdf",
        text_blocks=[
            TextBlock(text=text, page=0, bbox=(0, 0, 0, 0))
        ],
        images=[],
        metadata={},
    )


# A statement with a repository DOI link and no red-flag
# phrasing, so the only possible findings come from link
# resolution.
_STMT_WITH_LINK = (
    "Data Availability Statement The datasets produced in this "
    "study are deposited at https://doi.org/10.5061/dryad.xyz123 "
    "for reuse."
)

# A statement with no link and no red-flag phrasing.
_STMT_NO_LINK = (
    "Data Availability Statement The datasets produced in this "
    "study are stored in the institute archive."
)


class _FakeResp:
    """Tiny stand-in for ``httpx.Response``."""
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Scripts one response per ``.get`` call and records the
    requested URLs."""
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []
    def get(self, url, headers=None):  # type: ignore[no-untyped-def]
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("FakeClient ran out of responses")
        return self._responses.pop(0)
    def close(self) -> None:
        pass


def _settings(tmp_path: Path, *, enabled: bool = True) -> Settings:
    return Settings(
        workspace_dir=tmp_path / "ws",
        das_resolution_enabled=enabled,
    )


def _link_findings(res):  # type: ignore[no-untyped-def]
    """Only the findings produced by the link-resolution step
    (the phrase-based findings have different titles)."""
    return [
        f for f in res.findings
        if "link" in f.title.lower()
    ]


# ---------- link extraction ----------

def test_extract_statement_links_urls_and_dois() -> None:
    """Explicit URLs are kept; a bare DOI is rewritten to a
    doi.org URL; a DOI already covered by a doi.org URL is not
    duplicated; trailing sentence punctuation is stripped."""
    links = _extract_statement_links(
        "Data are at https://doi.org/10.5061/dryad.abc. "
        "See also doi:10.5281/zenodo.12345."
    )
    assert links == [
        "https://doi.org/10.5061/dryad.abc",
        "https://doi.org/10.5281/zenodo.12345",
    ]


def test_extract_statement_links_empty() -> None:
    assert _extract_statement_links("no links here") == []


# ---------- resolvable ----------

def test_resolvable_link_produces_no_link_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient([
        _FakeResp(200, "<html>Dataset landing page with files</html>"),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    assert _link_findings(res) == []
    assert len(fake.calls) == 1


# ---------- confirmed dead ----------

def test_404_link_is_medium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient([_FakeResp(404)])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    link_findings = _link_findings(res)
    assert len(link_findings) == 1
    assert link_findings[0].severity == "medium"


def test_soft_404_landing_page_is_medium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 whose repository landing page explicitly says the
    dataset is gone counts as a confirmed dead link."""
    fake = _FakeClient([
        _FakeResp(200, "<html><h1>Dataset not found</h1></html>"),
    ])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    link_findings = _link_findings(res)
    assert len(link_findings) == 1
    assert link_findings[0].severity == "medium"


# ---------- network failures degrade to info ----------

def test_connection_error_is_info_not_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _ErrClient:
        def __init__(self) -> None:
            self.calls: list[str] = []
        def get(self, url, headers=None):  # type: ignore[no-untyped-def]
            self.calls.append(url)
            raise httpx.ConnectError("simulated network down")
        def close(self) -> None:
            pass
    err = _ErrClient()
    monkeypatch.setattr(httpx, "Client", lambda **kw: err)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    link_findings = _link_findings(res)
    assert len(link_findings) == 1
    assert link_findings[0].severity == "info"
    # A network failure must never escalate.
    assert not any(
        f.severity in ("medium", "high") for f in link_findings
    )


def test_timeout_is_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TimeoutClient:
        def get(self, *a, **kw):  # type: ignore[no-untyped-def]
            raise httpx.ReadTimeout("simulated timeout")
        def close(self) -> None:
            pass
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: _TimeoutClient()
    )
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    link_findings = _link_findings(res)
    assert len(link_findings) == 1
    assert link_findings[0].severity == "info"


# ---------- no links / gate off: zero network ----------

def test_statement_without_links_makes_no_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient([])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_NO_LINK), settings=_settings(tmp_path)
    )
    assert res.ok
    assert fake.calls == []


def test_gate_off_makes_no_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeClient([])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    res = d.run(
        _doc_with(_STMT_WITH_LINK),
        settings=_settings(tmp_path, enabled=False),
    )
    assert res.ok
    assert _link_findings(res) == []
    assert fake.calls == []


# ---------- cache ----------

def test_link_verdict_is_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first run resolves the link; the second run is
    served from ``link_check_cache.json`` and does not touch
    the network."""
    fake = _FakeClient([_FakeResp(404)])
    monkeypatch.setattr(httpx, "Client", lambda **kw: fake)
    d = DataAvailabilityConcernDetector()
    settings = _settings(tmp_path)
    res1 = d.run(_doc_with(_STMT_WITH_LINK), settings=settings)
    assert len(fake.calls) == 1
    res2 = d.run(_doc_with(_STMT_WITH_LINK), settings=settings)
    assert len(fake.calls) == 1, (
        "cache should have prevented a second HTTP call"
    )
    assert any(
        f.severity == "medium" for f in _link_findings(res1)
    )
    assert any(
        f.severity == "medium" for f in _link_findings(res2)
    )
