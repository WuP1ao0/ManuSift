"""Tests for the supplementary-file detector (P2.3).

The detector reads the
PDF's embedded-file list
through ``pikepdf``. The
tests build small PDFs in
a temp directory and
attach the path to a
``ParsedDoc``.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz
import pikepdf

import pytest


def _new_pdf_with_attachment(
    path: str, attachments: list[tuple[str, bytes]] | None = None
) -> None:
    """Write a minimal PDF
    that optionally has
    attached files. We use
    ``pikepdf`` to add the
    attachments because
    ``fitz`` does not expose
    a high-level API for
    that."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello World")
    doc.save(path)
    doc.close()
    if attachments:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            for name, data in attachments:
                pdf.attachments[name] = data
            pdf.save(path)


def _doc_with_pdf(path: str, text: str = ""):
    from manusift.contracts import ParsedDoc
    blocks = (
        [type("B", (), {"text": text})()] if text else []
    )
    return ParsedDoc(
        trace_id="t-sup",
        source_path=path,
        text_blocks=blocks,
        images=[],
        metadata={},
    )


# ---------- 1. detector name ----------

def test_supplementary_detector_name() -> None:
    from manusift.detectors import SupplementaryFileDetector
    assert (
        SupplementaryFileDetector().name
        == "supplementary"
    )


# ---------- 2. PDF without attachments ----------

def test_pdf_without_attachments_silent() -> None:
    """A PDF without
    attachments produces no
    findings if the paper
    does not claim to have
    supplementary
    material."""
    from manusift.detectors import SupplementaryFileDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "no-att.pdf")
        _new_pdf_with_attachment(path)
        result = SupplementaryFileDetector().run(
            _doc_with_pdf(path, text="Methods. Results.")
        )
        # No "supplementary"
        # word in the text,
        # so no finding even
        # though no
        # attachments.
        assert result.findings == []


# ---------- 3. PDF that claims supplementary but has none ----------

def test_claims_supplementary_but_none_flagged() -> None:
    from manusift.detectors import SupplementaryFileDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "no-att.pdf")
        _new_pdf_with_attachment(path)
        result = SupplementaryFileDetector().run(
            _doc_with_pdf(
                path,
                text=(
                    "Data are available in "
                    "Supplementary Material."
                ),
            )
        )
        assert len(result.findings) == 1
        assert result.findings[0].severity == "medium"
        assert "no embedded files" in result.findings[0].title


# ---------- 4. PDF with attachments ----------

def test_pdf_with_attachments_reports_files() -> None:
    from manusift.detectors import SupplementaryFileDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "with-att.pdf")
        _new_pdf_with_attachment(
            path,
            [
                ("data.csv", b"a,b,c\n1,2,3\n"),
                ("readme.txt", b"hello"),
            ],
        )
        result = SupplementaryFileDetector().run(
            _doc_with_pdf(path)
        )
        # We expect at least
        # one finding (the
        # "info" finding) with
        # the file names.
        assert len(result.findings) >= 1
        ev = json.loads(result.findings[-1].evidence)
        assert "data.csv" in ev["files"]
        assert "readme.txt" in ev["files"]


# ---------- 5. suspicious file types are flagged ----------

def test_suspicious_file_flagged() -> None:
    from manusift.detectors import SupplementaryFileDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "suspect.pdf")
        _new_pdf_with_attachment(
            path,
            [("malware.exe", b"MZ\x90\x00")],
        )
        result = SupplementaryFileDetector().run(
            _doc_with_pdf(path)
        )
        # The "high" severity
        # finding is emitted
        # before the "low"
        # info finding.
        assert any(
            f.severity == "high" for f in result.findings
        )


# ---------- 6. nonexistent file is silent ----------

def test_nonexistent_file_silent() -> None:
    from manusift.detectors import SupplementaryFileDetector
    result = SupplementaryFileDetector().run(
        _doc_with_pdf("/no/such/file.pdf")
    )
    assert result.findings == []


# ---------- 7. empty source path is silent ----------

def test_empty_path_silent() -> None:
    from manusift.detectors import SupplementaryFileDetector
    result = SupplementaryFileDetector().run(
        _doc_with_pdf("")
    )
    assert result.findings == []


# ---------- 8. evidence is JSON serialisable ----------

def test_evidence_is_json() -> None:
    from manusift.detectors import SupplementaryFileDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "evid.pdf")
        _new_pdf_with_attachment(
            path, [("notes.txt", b"abc")]
        )
        result = SupplementaryFileDetector().run(
            _doc_with_pdf(path)
        )
        for f in result.findings:
            json.loads(f.evidence)


# ---------- 9. helpers ----------

def test_claims_supplementary_helper() -> None:
    from manusift.detectors.supplementary import (
        _claims_supplementary,
    )
    assert _claims_supplementary(
        "Data are in the supplementary material."
    )
    # Text without the
    # "supplementary" word
    # must NOT trigger.
    assert not _claims_supplementary(
        "Methods. Results."
    )
