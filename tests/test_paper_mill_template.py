"""Tests for the paper-mill template detector (P2.4).

The detector extracts
section headings from the
document text and flags
those that match a curated
list of non-standard
headings commonly seen in
paper-mill output. The
tests build small documents
in memory.
"""
from __future__ import annotations

import json

import pytest


class FakeDoc:
    def __init__(self, text=""):
        self.trace_id = "t-mill"
        self.source_path = ""
        self.text_blocks = (
            [type("B", (), {"text": text})()] if text else []
        )
        self.images = []
        self.metadata = {}


# ---------- 1. detector name ----------

def test_paper_mill_detector_name() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    assert (
        PaperMillTemplateDetector().name
        == "paper_mill_template"
    )


# ---------- 2. standard headings produce no findings ----------

def test_standard_headings_clean() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    text = """
    1. Introduction
    2. Methods
    3. Results
    4. Discussion
    5. Conclusion
    6. References
    """
    doc = FakeDoc(text=text)
    result = PaperMillTemplateDetector().run(doc)
    assert result.findings == []


# ---------- 3. single non-standard heading ----------

def test_single_non_standard_flagged() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    text = """
    1. Introduction and Background
    2. Materials and Methods
    3. Results
    4. Conclusion
    """
    doc = FakeDoc(text=text)
    result = PaperMillTemplateDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    # Two non-standard
    # headings.
    assert len(ev["flagged_headings"]) == 2


# ---------- 4. many non-standard headings is high severity ----------

def test_many_headings_high_severity() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    text = """
    1. Introduction and Background
    2. Materials and Methods
    3. Results and Discussion
    4. Conclusion and Discussion
    """
    doc = FakeDoc(text=text)
    result = PaperMillTemplateDetector().run(doc)
    assert len(result.findings) == 1
    assert result.findings[0].severity == "high"


# ---------- 5. empty document is silent ----------

def test_empty_doc_silent() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    doc = FakeDoc()
    result = PaperMillTemplateDetector().run(doc)
    assert result.findings == []


# ---------- 6. helpers ----------

def test_extract_headings_basic() -> None:
    from manusift.detectors.paper_mill_template import (
        _extract_headings,
    )
    text = (
        "1. Introduction\n"
        "2. Methods\n"
        "3. Results and Discussion\n"
    )
    headings = _extract_headings(text)
    # We expect the three
    # headings; only "Results
    # and Discussion" is
    # non-standard.
    assert any(
        h.lower() == "results and discussion" for h in headings
    )


def test_normalise_heading_helper() -> None:
    from manusift.detectors.paper_mill_template import (
        _normalise_heading,
    )
    assert (
        _normalise_heading("Materials and Methods:")
        == "materials and methods"
    )
    assert (
        _normalise_heading("  Introduction  ")
        == "introduction"
    )


# ---------- 2026-07 regression: headings in separate text blocks ----------

class _Block:
    def __init__(self, text):
        self.text = text


class MultiBlockDoc:
    """Mimics the real pipeline's ParsedDoc where each
    paragraph/heading is its own text block (PLOS layout).
    The detector must NOT space-join blocks onto one line --
    that hides block-per-line headings (fraud_web_v1
    web_plos_02 regression)."""

    def __init__(self, blocks):
        self.trace_id = "t-mill-multi"
        self.source_path = ""
        self.text_blocks = [_Block(b) for b in blocks]
        self.images = []
        self.metadata = {}


def test_heading_in_own_text_block_is_found() -> None:
    from manusift.detectors import PaperMillTemplateDetector
    doc = MultiBlockDoc(
        [
            "Yu Zhang1, Yongjun Zhu2, Baolin Yao3*",
            "1. Introduction",
            "Some introductory paragraph text that is long.",
            "2. Material and methods\n2.1. Experiment design",
            "More body text about soil salinity experiments.",
            "3. Results",
            "4. Discussion",
        ]
    )
    result = PaperMillTemplateDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    flagged = {h["heading"].lower() for h in ev["flagged_headings"]}
    assert "material and methods" in flagged


def test_associated_works_cs_heading_flagged() -> None:
    """CS paper-mill heading from the retracted Swin
    transformer paper (fraud_web_v1 web_sci_01)."""
    from manusift.detectors import PaperMillTemplateDetector
    doc = MultiBlockDoc(
        [
            "1. Introduction",
            "2. Associated works",
            "3. Proposed method",
            "4. Experiments",
            "5. Conclusion",
        ]
    )
    result = PaperMillTemplateDetector().run(doc)
    assert len(result.findings) == 1
    ev = json.loads(result.findings[0].evidence)
    flagged = {h["heading"].lower() for h in ev["flagged_headings"]}
    assert "associated works" in flagged
