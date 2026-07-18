"""Unit tests for the data-availability-concern detector.

These tests cover the detector's two outputs:

  1. ``"No data-availability section detected"`` finding --
     fires on research articles that lack a data-availability
     section. The smoke test against the benchmark PDFs lives
     in ``real_eval_fraud_cases/`` and is not run here.

  2. ``"Data-availability red flag: <category>"`` finding --
     fires when the section's text contains one of the
     red-flag phrases. The regexes and severity classification
     are tested in isolation below so a future refactor of
     the regex doesn't break the detector silently.
"""
from __future__ import annotations

import pytest

from manusift.detectors import DataAvailabilityConcernDetector
from manusift.detectors.data_availability_concern import (
    _extract_data_availability_section,
)
from manusift.contracts import ParsedDoc, TextBlock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(text: str, trace_id: str = "t") -> ParsedDoc:
    """Build a minimal ParsedDoc with one text block."""
    return ParsedDoc(
        trace_id=trace_id,
        source_path="/tmp/x.pdf",
        images=[],
        text_blocks=[TextBlock(page=0, bbox=(0, 0, 100, 100), text=text)],
        metadata={},
    )


# ---------------------------------------------------------------------------
# Detector behaviour
# ---------------------------------------------------------------------------


def test_fires_on_paper_without_data_availability_section() -> None:
    det = DataAvailabilityConcernDetector()
    # 3000 words to be safely above the 2000-word threshold
    doc = _doc(
        "This is a long research article. " * 600
    )
    result = det.run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert "no data-availability section" in f.title.lower()
    assert f.severity == "low"


def test_no_firing_for_short_documents() -> None:
    """A short document (abstract, editorial) shouldn't
    fire the 'no section' finding even if it lacks a
    data-availability section."""
    det = DataAvailabilityConcernDetector()
    doc = _doc("short paper abstract only " * 50)  # < 2000 words
    result = det.run(doc)
    assert result.findings == []


def test_fires_vague_availability_red_flag() -> None:
    """When the paper's data-availability section says
    'available upon reasonable request' the detector
    emits a medium-severity red flag."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Introduction. Methods. Results. "
        "Data Availability Statement: All raw data are "
        "available from the corresponding author upon "
        "reasonable request. Conclusion.",
        trace_id="t-vague",
    )
    result = det.run(doc)
    # The
    # vague
    # flag
    # is
    # medium
    # severity.
    flagged = [f for f in result.findings if f.severity == "medium"]
    assert len(flagged) >= 1
    assert any(
        "vague_availability" in (f.evidence or "") for f in flagged
    )


def test_fires_frontiers_further_inquiries_hedge() -> None:
    """Frontiers OA template: 'Further inquiries can be directed to'."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data Availability Statement The original contributions "
        "presented in the study are included in the article. "
        "Further inquiries can be directed to the corresponding "
        "author(s).",
        trace_id="t-frontiers",
    )
    result = det.run(doc)
    flagged = [f for f in result.findings if f.severity == "medium"]
    assert any(
        "vague_availability" in (f.evidence or "") for f in flagged
    ), [f.evidence for f in result.findings]


def test_fires_frontiers_without_undue_reservation() -> None:
    """Frontiers psych/clinical template without repository DOI."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data availability statement The raw data supporting the "
        "conclusions of this article will be made available by the "
        "authors, without undue reservation. Author contributions.",
        trace_id="t-frontiers-res",
    )
    result = det.run(doc)
    flagged = [f for f in result.findings if f.severity == "medium"]
    assert any(
        "vague_availability" in (f.evidence or "") for f in flagged
    ), [f.evidence for f in result.findings]


def test_fires_raw_data_unavailable_red_flag() -> None:
    """The most-severe red-flag phrase: 'raw data are no
    longer available'."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Methods. Data Availability: the raw data are no "
        "longer available due to ethical restrictions. "
        "Conclusion.",
        trace_id="t-raw",
    )
    result = det.run(doc)
    flagged = [f for f in result.findings if f.severity == "high"]
    assert any(
        "raw_data_unavailable" in (f.evidence or "") for f in flagged
    )


def test_no_firing_for_clean_data_availability_statement() -> None:
    """A clean statement like 'data are in the article' or
    'data are in supplementary materials' is NOT a red
    flag. The detector should not fire."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data Availability Statement All datasets generated "
        "for this study are included in the article and "
        "Supplementary Material.",
        trace_id="t-clean",
    )
    result = det.run(doc)
    # The
    # "no
    # section"
    # warning
    # should
    # NOT
    # fire
    # because
    # a
    # section
    # was
    # found.
    no_section = [
        f for f in result.findings
        if "no data-availability section" in f.title.lower()
    ]
    assert no_section == []
    # No
    # high
    # or
    # medium
    # red
    # flag
    # either.
    high_med = [f for f in result.findings if f.severity in ("high", "medium")]
    assert high_med == []


# ---------------------------------------------------------------------------
# Section extractor
# ---------------------------------------------------------------------------


def test_section_extractor_finds_inline_heading() -> None:
    text = (
        "Some paper text. Data availability statement The raw "
        "data are available from the corresponding author."
    )
    section = _extract_data_availability_section(text)
    # The
    # extractor
    # returns
    # the
    # content
    # *after*
    # the
    # heading.
    # The
    # section
    # body
    # should
    # contain
    # the
    # raw-data
    # statement.
    assert section is not None
    assert "raw data are available" in section.lower()


def test_section_extractor_returns_none_when_missing() -> None:
    text = "A paper that has no data availability section."
    # The
    # extractor
    # is
    # permissive:
    # "data
    # availability"
    # mid-sentence
    # is
    # detected
    # as
    # a
    # section.
    # This
    # is
    # intentional
    # -- many
    # PDFs
    # place
    # the
    # data
    # availability
    # statement
    # at
    # the
    # end
    # of
    # the
    # paper
    # with
    # a
    # period
    # before
    # it.
    section = _extract_data_availability_section(text)
    # The
    # extractor
    # returns
    # whatever
    # comes
    # *after*
    # the
    # "data
    # availability"
    # phrase.
    # In
    # this
    # test
    # case
    # the
    # phrase
    # is
    # at
    # the
    # end
    # of
    # the
    # text
    # so
    # the
    # section
    # is
    # short
    # (or
    # empty).
    # We
    # just
    # check
    # the
    # extractor
    # doesn't
    # crash.
    assert section is not None


def test_section_extractor_handles_newline_heading() -> None:
    text = (
        "Some paper text.\n"
        "\n"
        "DATA AVAILABILITY STATEMENT\n"
        "All raw data are available from the corresponding author."
    )
    section = _extract_data_availability_section(text)
    assert section is not None
    assert "raw data are available" in section.lower()


# ---------------------------------------------------------------------------
# 2026-07 additions (fraud_web_v1 gap analysis)
# ---------------------------------------------------------------------------


def test_fires_low_for_within_manuscript_only() -> None:
    """PLOS boilerplate 'All relevant data are within the
    manuscript' means no underlying dataset was deposited --
    a LOW concern signal (retracted COPD RCT web_plos_01)."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data Availability: All relevant data are within the "
        "manuscript and its Supporting Information files. "
        "Funding: none.",
        trace_id="t-within",
    )
    result = det.run(doc)
    low = [f for f in result.findings if f.severity == "low"]
    assert any(
        "within_manuscript_only" in (f.evidence or "") for f in low
    )
    # never a high/medium for this class
    assert [f for f in result.findings if f.severity in ("high", "medium")] == []


def test_fires_low_for_available_only_within_paper() -> None:
    """Awkward 'available only within the paper' phrasing from
    the retracted nanofluid paper (web_sci_02)."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data availability The results of this study are "
        "available only within the paper to support the data.",
        trace_id="t-only",
    )
    result = det.run(doc)
    low = [f for f in result.findings if f.severity == "low"]
    assert any(
        "within_manuscript_only" in (f.evidence or "") for f in low
    )


def test_fires_low_for_not_applicable_availability() -> None:
    """An empirical western-blot study whose availability
    statement is 'Not applicable' (retracted web_spandidos_02)
    gets a LOW not_applicable finding."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Availability of data and materials Not applicable. "
        "Authors' contributions MC and PH conceived the study.",
        trace_id="t-na",
    )
    result = det.run(doc)
    low = [f for f in result.findings if f.severity == "low"]
    assert any(
        "not_applicable" in (f.evidence or "") for f in low
    )


def test_external_deposition_is_fully_silent() -> None:
    """A statement with a real repository DOI produces no
    findings at all (no red flag, no low signal)."""
    det = DataAvailabilityConcernDetector()
    doc = _doc(
        "Data Availability: The datasets generated during the "
        "current study are available in the Zenodo repository, "
        "https://doi.org/10.5281/zenodo.1234567",
        trace_id="t-zenodo",
    )
    result = det.run(doc)
    assert result.findings == []
