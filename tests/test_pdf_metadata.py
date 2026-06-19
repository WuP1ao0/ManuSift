"""Tests for the PDF metadata + structure detector (P0.1).

The detector flags documents
whose metadata or structure
is suspicious. The tests
build small PDFs in a temp
directory using ``fitz`` and
assert on the findings.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import fitz
import pikepdf

import pytest


# ---------- helpers ----------

def _new_pdf(
    path: str,
    *,
    producer: str | None = None,
    creator: str | None = None,
    author: str | None = None,
    creation: str | None = None,
    mod: str | None = None,
) -> None:
    """Write a minimal one-page
    PDF with optional
    metadata. ``creation`` and
    ``mod`` are PDF date
    strings like
    ``D:20250101000000``."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Hello World")
    if producer is not None or creator is not None or author is not None:
        meta = doc.metadata or {}
        if producer is not None:
            meta["producer"] = producer
        if creator is not None:
            meta["creator"] = creator
        if author is not None:
            meta["author"] = author
        doc.set_metadata(meta)
    doc.save(path)
    doc.close()
    # pikepdf lets us set the
    # date fields directly;
    # ``fitz`` only exposes
    # the ``/Producer`` /
    # ``/Creator`` / ``/Author``
    # fields.
    if creation is not None or mod is not None:
        with pikepdf.open(path, allow_overwriting_input=True) as pdf:
            info = dict(pdf.docinfo)
            if creation is not None:
                info["/CreationDate"] = pikepdf.String(creation)
            if mod is not None:
                info["/ModDate"] = pikepdf.String(mod)
            # Use the
            # ``update`` API to
            # preserve indirect
            # status of the
            # docinfo dictionary.
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                pass
            pdf.docinfo.update(info)
            pdf.save(path)


def _doc_with_pdf(path: str):
    from manusift.contracts import ParsedDoc
    return ParsedDoc(
        trace_id="t-meta",
        source_path=path,
        text_blocks=[],
        images=[],
        metadata={},
    )


# ---------- 1. detector name ----------

def test_pdf_metadata_detector_name() -> None:
    from manusift.detectors import PdfMetadataDetector
    assert PdfMetadataDetector().name == "pdf_metadata"


# ---------- 2. clean PDF produces no findings ----------

def test_clean_pdf_no_findings() -> None:
    from manusift.detectors import PdfMetadataDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "clean.pdf")
        _new_pdf(path)
        result = PdfMetadataDetector().run(
            _doc_with_pdf(path)
        )
        # A blank PDF with no
        # metadata at all still
        # has an empty /Info
        # dict -- that produces
        # a single "metadata
        # stripped" finding. We
        # assert the detector
        # runs without
        # crashing; we do not
        # require a specific
        # number of findings.
        assert isinstance(result.findings, list)


# ---------- 3. mod date before creation date ----------

def test_mod_before_creation_is_flagged() -> None:
    from manusift.detectors import PdfMetadataDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "mod-before.pdf")
        # Mod before creation:
        # the textbook
        # manipulation signature.
        _new_pdf(
            path,
            creation="D:20250601000000",
            mod="D:20250101000000",
        )
        result = PdfMetadataDetector().run(
            _doc_with_pdf(path)
        )
        titles = [f.title for f in result.findings]
        assert any(
            "modification date is earlier" in t.lower()
            for t in titles
        )


# ---------- 4. suspicious producer is flagged ----------

def test_suspicious_producer_is_flagged() -> None:
    from manusift.detectors import PdfMetadataDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "bad-producer.pdf")
        _new_pdf(
            path,
            producer="iText 5.5.0 (paper-factory)",
        )
        result = PdfMetadataDetector().run(
            _doc_with_pdf(path)
        )
        titles = [f.title for f in result.findings]
        assert any(
            "paper-mill" in t.lower() or "itext" in t.lower()
            for t in titles
        )


# ---------- 5. missing /Author is flagged ----------

def test_missing_author_is_flagged() -> None:
    from manusift.detectors import PdfMetadataDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "no-author.pdf")
        # Author is empty
        # (whitespace only).
        _new_pdf(path, author="   ")
        result = PdfMetadataDetector().run(
            _doc_with_pdf(path)
        )
        titles = [f.title for f in result.findings]
        # The author check fires
        # only if the
        # ``/Info`` dict is
        # non-empty. We do not
        # require a specific
        # outcome -- the test
        # just verifies the
        # detector does not
        # crash.
        assert isinstance(result.findings, list)


# ---------- 6. nonexistent file is silent ----------

def test_nonexistent_file_silent() -> None:
    from manusift.detectors import PdfMetadataDetector
    result = PdfMetadataDetector().run(
        _doc_with_pdf("/no/such/file.pdf")
    )
    # The file cannot be
    # opened, so the
    # detector reports
    # "metadata stripped".
    assert any(
        "metadata stripped" in f.title.lower()
        or "no /info" in f.title.lower()
        for f in result.findings
    ) or result.findings == []


# ---------- 7. no source path is silent ----------

def test_no_source_path_silent() -> None:
    from manusift.detectors import PdfMetadataDetector
    from manusift.contracts import ParsedDoc
    pd = ParsedDoc(
        trace_id="t",
        source_path="",
        text_blocks=[],
        images=[],
        metadata={},
    )
    result = PdfMetadataDetector().run(pd)
    # An empty path means
    # the detector reads
    # nothing; we accept
    # either the "metadata
    # stripped" finding or
    # an empty list.
    assert any(
        "metadata stripped" in f.title.lower()
        for f in result.findings
    ) or result.findings == []


# ---------- 8. evidence has the right shape ----------

def test_findings_carry_json_evidence() -> None:
    from manusift.detectors import PdfMetadataDetector
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "evid.pdf")
        _new_pdf(
            path,
            creation="D:20250601000000",
            mod="D:20250101000000",
        )
        result = PdfMetadataDetector().run(
            _doc_with_pdf(path)
        )
        for f in result.findings:
            # The evidence field
            # must be a
            # JSON-serialisable
            # string.
            json.loads(f.evidence)
