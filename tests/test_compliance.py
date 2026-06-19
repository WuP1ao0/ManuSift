"""Tests for the compliance-statement detector (P2.1).

The detector extracts five
categories of compliance
statements from the
document text: data
availability, ethics
approval, funding, conflict
of interest, and trial
registration. The tests
build small documents in
memory and assert on the
findings.
"""
from __future__ import annotations

import json

import pytest


class FakeDoc:
    def __init__(self, text=""):
        self.trace_id = "t-comp"
        self.source_path = ""
        self.text_blocks = (
            [type("B", (), {"text": text})()] if text else []
        )
        self.images = []
        self.metadata = {}


# ---------- 1. detector name ----------

def test_compliance_detector_name() -> None:
    from manusift.detectors import ComplianceStatementDetector
    assert (
        ComplianceStatementDetector().name == "compliance"
    )


# ---------- 2. complete compliance section produces no findings ----------

def test_complete_compliance_silent() -> None:
    from manusift.detectors import ComplianceStatementDetector
    text = """
    Data availability: All data are available from the
    corresponding author on reasonable request.

    Ethics approval: The study was approved by the
    institutional review board of Foo University (IRB-1234).

    Funding: This work was supported by the National
    Science Foundation (grant 1234567).

    Conflict of interest: The authors declare no
    conflicts of interest.

    Trial registration: Registered at
    clinicaltrials.gov (NCT12345678).
    """
    doc = FakeDoc(text=text)
    result = ComplianceStatementDetector().run(doc)
    assert result.findings == []


# ---------- 3. missing data availability ----------

def test_missing_data_availability_flagged() -> None:
    from manusift.detectors import ComplianceStatementDetector
    text = """
    Ethics approval: The study was approved by the
    IRB.

    Funding: Supported by the NSF.

    Conflict of interest: The authors declare no
    conflicts of interest.
    """
    doc = FakeDoc(text=text)
    result = ComplianceStatementDetector().run(doc)
    titles = [f.title for f in result.findings]
    assert any("data availability" in t for t in titles)


# ---------- 4. missing all five ----------

def test_all_missing_flagged() -> None:
    from manusift.detectors import ComplianceStatementDetector
    text = "This is a methods section. No compliance text."
    doc = FakeDoc(text=text)
    result = ComplianceStatementDetector().run(doc)
    # Five findings, one per
    # missing category.
    assert len(result.findings) == 5


# ---------- 5. case-insensitive match ----------

def test_case_insensitive() -> None:
    from manusift.detectors import ComplianceStatementDetector
    text = """
    DATA AVAILABILITY: Available.
    ETHICS APPROVAL: Approved.
    FUNDING: Funded.
    CONFLICT OF INTEREST: None.
    TRIAL REGISTRATION: NCT123.
    """
    doc = FakeDoc(text=text)
    result = ComplianceStatementDetector().run(doc)
    assert result.findings == []


# ---------- 6. empty document is silent ----------

def test_empty_doc_silent() -> None:
    from manusift.detectors import ComplianceStatementDetector
    doc = FakeDoc()
    result = ComplianceStatementDetector().run(doc)
    assert result.findings == []


# ---------- 7. severity is low ----------

def test_finding_severity_is_low() -> None:
    from manusift.detectors import ComplianceStatementDetector
    doc = FakeDoc(text="This is a paper with no compliance text.")
    result = ComplianceStatementDetector().run(doc)
    for f in result.findings:
        assert f.severity == "low"


# ---------- 8. evidence lists missing categories ----------

def test_evidence_lists_missing() -> None:
    from manusift.detectors import ComplianceStatementDetector
    doc = FakeDoc(text="Just some prose. No compliance text.")
    result = ComplianceStatementDetector().run(doc)
    for f in result.findings:
        ev = json.loads(f.evidence)
        assert "category" in ev
        assert "missing" in ev
