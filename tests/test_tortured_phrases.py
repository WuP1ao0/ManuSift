"""Tests for the tortured-phrases detector (P1.1).

The detector scans
``doc.text_blocks`` for
known tortured phrases and
emits a single finding with
the matched phrases and
their likely intended
wording. The tests build
small documents in memory
and assert on the
findings.
"""
from __future__ import annotations

import json

import pytest


class FakeDoc:
    def __init__(self, text=""):
        self.trace_id = "t-tort"
        self.source_path = ""
        self.text_blocks = (
            [type("B", (), {"text": text})()] if text else []
        )
        self.images = []
        self.metadata = {}


# ---------- 1. detector name ----------

def test_tortured_detector_name() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    assert (
        TorturedPhrasesDetector().name
        == "text_tortured_phrases"
    )


# ---------- 2. clean text produces no findings ----------

def test_clean_text_produces_no_findings() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "This study uses deep learning to classify "
            "tumour histology images. The Cox "
            "proportional hazards model was fit to the "
            "Kaplan-Meier survival data."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert result.findings == []


# ---------- 3. single tortured phrase produces a finding ----------

def test_single_phrase_produces_finding() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "The method is unpresidented in its "
            "ability to detect novel viruses."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert len(result.findings) == 1
    f = result.findings[0]
    # The evidence lists the
    # distinct phrases.
    ev = json.loads(f.evidence)
    assert "unpresidented" in [
        p["phrase"] for p in ev["distinct_phrases"]
    ]
    # And the likely-intended
    # wording.
    entry = ev["distinct_phrases"][0]
    assert entry["likely_intended"] == "unprecedented"


# ---------- 4. multiple distinct phrases ----------

def test_multiple_distinct_phrases() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "This unpresidented study uses deeply "
            "learning to analyse the neural community "
            "architecture. The u-internet backbone "
            "was trained from scratch."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    phrases = {p["phrase"] for p in ev["distinct_phrases"]}
    # Four distinct
    # tortured phrases.
    assert "unpresidented" in phrases
    assert "deeply learning" in phrases
    assert "neural community" in phrases
    assert "u-internet" in phrases


# ---------- 5. high severity for many matches ----------

def test_high_severity_for_many_matches() -> None:
    """3+ matches is
    'high' severity per
    the threshold defined
    in the detector."""
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "The unpresidented result used deeply "
            "learning. The neural community model "
            "outperformed the u-internet baseline."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"


def test_medium_severity_for_few_matches() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "This unpresidented result is "
            "discussed below."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert result.findings[0].severity == "medium"


# ---------- 6. empty document is silent ----------

def test_empty_document_is_silent() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc()
    result = TorturedPhrasesDetector().run(doc)
    assert result.findings == []


# ---------- 7. case insensitivity ----------

def test_case_insensitive_match() -> None:
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(text="The result is UNPRESIDENTED.")
    result = TorturedPhrasesDetector().run(doc)
    assert len(result.findings) == 1


# ---------- 8. word boundary prevents false matches ----------

def test_word_boundary_prevents_false_match() -> None:
    """The word "pcr" is in
    the dictionary; the
    detector must NOT flag
    the substring inside
    "pcr-tests" or other
    longer words. Wait --
    "pcr" is *not* in our
    curated subset (we
    removed it because it
    matches too aggressively).
    The test uses
    "unpresidented" inside
    "unpresidentedness" --
    the word boundary
    prevents a match."""
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(text="This is unpresidentedness.")
    result = TorturedPhrasesDetector().run(doc)
    assert result.findings == []


# ---------- 9. helpers ----------

def test_normalise_phrase_helper() -> None:
    from manusift.detectors.tortured_phrases import (
        _normalise_phrase,
    )
    assert _normalise_phrase("Hello   World") == "hello world"
    assert _normalise_phrase("  P < 0.05  ") == "p < 0.05"


def test_curated_dictionary_has_verified_entries() -> None:
    """The merged dictionary
    (hand-curated core + the
    verified Cabanac-derived
    external data file) must
    be large enough to be
    useful."""
    from manusift.detectors.tortured_phrases import _TORTURED
    assert len(_TORTURED) >= 1000


# ---------- 10. precision: ordinary scientific English is silent ----------

def test_normal_boilerplate_produces_no_findings() -> None:
    """2026-07 precision overhaul: ordinary
    scientific boilerplate (data availability,
    author contributions, p-values, cell
    viability, ...) must NOT be flagged --
    the old hand-written dictionary fired on
    every legitimate paper."""
    from manusift.detectors import TorturedPhrasesDetector
    doc = FakeDoc(
        text=(
            "Data availability: the datasets are "
            "available on request. Author "
            "contributions: all authors approved "
            "the manuscript. Cell viability was "
            "measured with an MTT assay; p < 0.05 "
            "was considered significant. The "
            "randomized controlled trial used "
            "standard deviation and confidence "
            "interval reporting."
        )
    )
    result = TorturedPhrasesDetector().run(doc)
    assert result.findings == []
