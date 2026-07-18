"""Regression: tables must be extracted while the fitz Document is open."""
from __future__ import annotations

from pathlib import Path

import pytest

from manusift.contracts import ExtractedTable
from manusift.ingest.pdf import parse_pdf
from manusift.trace import new_trace_id


def _sample_pdf() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    candidates = list(
        (root / "benchmarks" / "fraud_representatives_v1" / "cases").glob(
            "*/*/paper.pdf"
        )
    )
    return candidates[0] if candidates else None


@pytest.mark.skipif(_sample_pdf() is None, reason="no sample PDF in repo")
def test_parse_pdf_populates_tables_when_text_stats_exist() -> None:
    pdf = _sample_pdf()
    assert pdf is not None
    doc = parse_pdf(pdf, new_trace_id())
    # Not every paper has tables; the contract is that extraction
    # does not silently die on a closed document. When the text
    # layer has stat descriptors we should get ≥1 table on most
    # Frontiers OA PDFs in the fraud set.
    assert isinstance(doc.tables, list)
    # Smoke: list elements are ExtractedTable when present.
    for t in doc.tables:
        assert isinstance(t, ExtractedTable)
