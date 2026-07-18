"""P4b: PDF-extracted tables vs companion Source Data (XLSX/CSV).

Compares rounded numeric multisets between:

  * PDF-side tables: ``pdf_native``, ``pdf_plumber``, ``pdf_text_stat``
  * Companion tables: ``xlsx``, ``csv``

Flags:
  * PDF values largely missing from Source Data (possible mismatch /
    incomplete SI / transcription error)
  * Source Data values largely missing from PDF tables (informational —
    SI often contains extra panels)

Does not require OCR. Complements ``figure_table_ocr`` which checks
OCR figure numbers against companions.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any, Iterable

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult

_PDF_KINDS = frozenset({"pdf_native", "pdf_plumber", "pdf_text_stat", "ocr"})
_SRC_KINDS = frozenset({"xlsx", "csv"})

_NUM_RE = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?%?$"
)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "off", "no"}


def _parse_number(text: str) -> float | None:
    t = (text or "").strip().replace(",", "")
    if t.endswith("%"):
        t = t[:-1].strip()
    if not t:
        return None
    if t.startswith(".") and re.fullmatch(r"\.\d+", t):
        t = "0" + t
    try:
        if _NUM_RE.match(t) or re.fullmatch(r"[+-]?\d+(?:\.\d+)?", t):
            return float(t)
    except (TypeError, ValueError):
        return None
    try:
        return float(t)
    except (TypeError, ValueError):
        return None


def _round_key(v: float, nd: int = 4) -> float:
    return round(float(v), nd)


def collect_numbers(
    tables: Iterable[Any],
    *,
    kinds: frozenset[str],
) -> tuple[list[float], list[str]]:
    nums: list[float] = []
    labels: list[str] = []
    for t in tables:
        sk = str(getattr(t, "source_kind", "") or "")
        if sk not in kinds:
            continue
        fig = str(getattr(t, "fig_name", "") or "")
        sheet = str(getattr(t, "sheet_name", "") or "")
        tid = str(getattr(t, "table_id", "") or "")
        label = fig or sheet or tid or sk
        labels.append(label)
        headers = getattr(t, "headers", None) or []
        rows = getattr(t, "rows", None) or []
        for cell in list(headers):
            v = _parse_number(str(cell))
            if v is not None:
                nums.append(v)
        for row in rows:
            for cell in row:
                v = _parse_number(str(cell))
                if v is not None:
                    nums.append(v)
    return nums, labels


def multiset_missing_fraction(
    query: list[float],
    reference: list[float],
) -> tuple[float, int, int]:
    """Fraction of query multiset counts not covered by reference."""
    if not query:
        return 0.0, 0, 0
    ref = Counter(_round_key(v) for v in reference)
    q = Counter(_round_key(v) for v in query)
    missing = 0
    total = 0
    for k, c in q.items():
        total += c
        have = ref.get(k, 0)
        if have < c:
            missing += c - have
    return (missing / total if total else 0.0), missing, total


class SourceDataConsistencyDetector:
    """Cross-check PDF table numbers against companion Source Data."""

    name = "source_data_consistency"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        if not _env_flag("MANUSIFT_SOURCE_DATA_CONSISTENCY", True):
            return DetectorResult(detector=self.name, findings=[], ok=True)

        tables = getattr(doc, "tables", None) or []
        pdf_nums, pdf_labels = collect_numbers(tables, kinds=_PDF_KINDS)
        src_nums, src_labels = collect_numbers(tables, kinds=_SRC_KINDS)

        findings: list[Finding] = []

        if not src_nums:
            # Soft signal: paper has PDF tables but no companion numeric data
            if len(pdf_nums) >= 20:
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity="info",
                        title="No companion Source Data numbers to cross-check",
                        evidence=(
                            f"PDF-side tables contributed {len(pdf_nums)} numeric "
                            "cells, but no xlsx/csv companion numbers were attached."
                        ),
                        location="companions",
                        raw={
                            "kind": "no_source_data",
                            "pdf_numeric_cells": len(pdf_nums),
                            "pdf_tables": pdf_labels[:20],
                        },
                    )
                )
            return DetectorResult(detector=self.name, findings=findings, ok=True)

        if len(pdf_nums) < 8:
            return DetectorResult(detector=self.name, findings=findings, ok=True)

        miss_frac, miss_n, total = multiset_missing_fraction(pdf_nums, src_nums)
        # PDF values missing from source
        if miss_frac >= 0.35 and miss_n >= 10:
            sev = "high" if miss_frac >= 0.65 else "medium"
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity=sev,  # type: ignore[arg-type]
                    title="PDF table numbers largely absent from Source Data",
                    evidence=(
                        f"{miss_frac:.0%} of PDF-extracted numeric cells "
                        f"({miss_n}/{total}) have no matching value in companion "
                        f"xlsx/csv (source cells={len(src_nums)}). "
                        "Possible incomplete SI, transcription error, or "
                        "PDF/table extraction noise."
                    ),
                    location="PDF tables ↔ Source Data",
                    raw={
                        "kind": "pdf_missing_in_source",
                        "missing_fraction": round(miss_frac, 4),
                        "missing_count": miss_n,
                        "pdf_total": total,
                        "source_total": len(src_nums),
                        "pdf_tables": pdf_labels[:20],
                        "source_tables": src_labels[:20],
                    },
                )
            )

        # Source values missing from PDF (usually expected extra SI — lower sev)
        inv_frac, inv_n, inv_total = multiset_missing_fraction(src_nums, pdf_nums)
        if inv_frac >= 0.55 and inv_n >= 30 and len(pdf_nums) >= 20:
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="low",
                    title="Source Data contains many numbers not seen in PDF tables",
                    evidence=(
                        f"{inv_frac:.0%} of Source Data numeric cells "
                        f"({inv_n}/{inv_total}) are not present in PDF-extracted "
                        "tables. Often normal for multi-panel SI; review if PDF "
                        "tables claim to fully report the same experiments."
                    ),
                    location="Source Data ↔ PDF tables",
                    raw={
                        "kind": "source_extra_vs_pdf",
                        "missing_fraction": round(inv_frac, 4),
                        "missing_count": inv_n,
                        "source_total": inv_total,
                        "pdf_total": len(pdf_nums),
                    },
                )
            )

        # Overlap summary as info when both sides large and consistent
        if not findings and len(pdf_nums) >= 20 and len(src_nums) >= 20:
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="info",
                    title="PDF tables and Source Data numeric overlap looks plausible",
                    evidence=(
                        f"PDF numeric cells={len(pdf_nums)}, source={len(src_nums)}; "
                        f"PDF→source missing fraction={miss_frac:.0%}."
                    ),
                    location="PDF tables ↔ Source Data",
                    raw={
                        "kind": "overlap_ok",
                        "missing_fraction": round(miss_frac, 4),
                        "pdf_total": len(pdf_nums),
                        "source_total": len(src_nums),
                    },
                )
            )

        return DetectorResult(detector=self.name, findings=findings, ok=True)
