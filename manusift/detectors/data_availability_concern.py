"""R-2026-06-12: Data-availability-statement concern detector.

The official retractions behind cases 002, 004, and 008 in the
benchmark all cite "raw data no longer available" or "authors
unresponsive to raw data requests" as a contributor to the
decision. None of ManuSift's existing detector surface catches
this directly:

  * ``compliance`` only checks for the *presence* of a
    data-availability statement, not its content.
  * ``supplementary`` only fires when an actual XLSX/CSV
    companion file is uploaded, which is rare for retracted
    papers.
  * ``image_dup`` / ``image_forensics`` are about figures,
    not raw data.

This detector fills the gap by reading the data-availability
section of the paper and flagging when the statement uses a
**red-flag phrase** that is associated with poor data-sharing
practices in the published literature.

The list of red-flag phrases comes from a cross-check of:

  * Gabelica et al. (Nature Scientific Data, 2022) — "Data
    sharing practices and data availability upon request…"
    which concludes that "available upon reasonable request"
    statements are inefficient and should not be allowed.
  * COPE / ICMJE guidelines (2024-2025 revisions) which
    explicitly call out "available upon reasonable request"
    and "available from the corresponding author on request"
    as problematic.
  * The Retraction Watch category "data unavailable /
    authors unresponsive" — present in the benchmark's
    case_002, case_004, and case_008.

The detector emits one finding per red-flag phrase found in
the data-availability section. The finding severity is
``medium`` for vague-but-cited phrases and ``high`` for the
"raw data not available" + "unresponsive authors" combination
that appeared in the benchmark's three relevant retractions.
"""
from __future__ import annotations

import re

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# Red-flag phrases seen in the data-availability statements of
# the retracted cases in this benchmark AND in the published
# data-sharing literature. The order is intentional: more
# specific patterns first so the regex doesn't prematurely
# match a generic one.
#
# (regex, severity, evidence category)
_RED_FLAGS: list[tuple[re.Pattern[str], str, str]] = [
    # HIGH: raw data not available / removed
    (re.compile(
        r"\b(raw data (?:are|is|were) (?:no longer|not) "
        r"(?:longer\s+)?available|raw data (?:are|is|were) "
        r"(?:not|no longer) accessible|raw data (?:have|has) "
        r"been (?:removed|lost|destroyed)|source data (?:are|is) "
        r"not available|underlying data (?:are|is) not available)\b",
        re.IGNORECASE,
    ), "high", "raw_data_unavailable"),
    # HIGH: authors unresponsive
    (re.compile(
        r"\b(authors? (?:have been |were )?unresponsive|"
        r"authors? (?:failed|did not respond) to (?:provide|"
        r"share) (?:the )?raw data|authors? (?:have |has )?"
        r"not responded to (?:multiple )?requests? for "
        r"(?:the )?raw data|authors? did not provide "
        r"(?:the )?raw data)\b",
        re.IGNORECASE,
    ), "high", "authors_unresponsive"),
    # MEDIUM: vague / hedged
    (re.compile(
        r"\b(available (?:from |upon )?reasonable request|"
        r"available (?:from |upon )?request|available from the "
        r"corresponding author|are available from the "
        r"corresponding author on request|available on "
        r"request from the (?:corresponding )?author|"
        r"data (?:are|is) available (?:on|upon) (?:a )?"
        r"reasonable request)\b",
        re.IGNORECASE,
    ), "medium", "vague_availability"),
    # MEDIUM: restrictions / legal / confidentiality
    (re.compile(
        r"\b(available (?:subject|with) (?:ethical|legal|"
        r"privacy|confidentiality) (?:approval|restrictions|"
        r"constraints)|not publicly available due to "
        r"(?:ethical|legal|privacy|confidentiality) "
        r"(?:reasons|concerns|restrictions)|access (?:is )?"
        r"restricted (?:by|due to) (?:ethical|legal|privacy) "
        r"(?:approval|reasons|restrictions))\b",
        re.IGNORECASE,
    ), "medium", "restricted_availability"),
]


# Phrases that indicate the paper has NO data-availability
# statement at all (i.e. the section is missing). This is
# weaker evidence than a red flag but worth flagging.
_MISSING_PHRASES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(data availability|data sharing|raw data "
        r"availability|data deposition|accession number)\b",
        re.IGNORECASE,
    ),
)


class DataAvailabilityConcernDetector:
    """Scan the data-availability section for red-flag phrases.

    The detector name (``data_availability_concern``) is short
    enough to fit the tool-list's 32-char name limit, descriptive
    of the category, and matches the existing pattern
    (e.g. ``image_dup``, ``image_forensics``).
    """

    name = "data_availability_concern"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        text = " ".join(
            getattr(b, "text", "") for b in doc.text_blocks
        )
        if not text:
            return DetectorResult(
                detector=self.name, findings=[], ok=True,
            )

        # Restrict the search to the data-availability section
        # when possible: look for the heading and grab the
        # following 500 words. If we can't find the section,
        # fall back to scanning the whole document.
        section = _extract_data_availability_section(text)
        section_found = section is not None
        if section is None:
            section = text

        findings: list[Finding] = []
        seen_substring: set[str] = set()
        for pat, severity, category in _RED_FLAGS:
            for m in pat.finditer(section):
                snippet = section[max(0, m.start() - 40): m.end() + 40]
                # De-dupe
                # overlapping
                # matches
                # of
                # the
                # same
                # category.
                key = f"{category}::{m.start() // 80}"
                if key in seen_substring:
                    continue
                seen_substring.add(key)
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity=severity,
                        title=(
                            f"Data-availability red flag: {category}"
                        ),
                        location=(
                            "data-availability section"
                            if section is not text
                            else "text"
                        ),
                        evidence=_format_evidence(
                            snippet, category, severity,
                        ),
                    )
                )

        # If the document has NO data-availability section
        # at all and is a research article (has at least
        # 2000 words), emit one low-severity finding.
        if not section_found and len(text.split()) > 2000:
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity="low",
                    title=(
                        "No data-availability section detected"
                    ),
                    location="text",
                    evidence=(
                        "Document does not appear to contain a "
                        "data-availability statement. Many "
                        "biomedical journals (PLOS, Nature, "
                        "Frontiers) require this section."
                    ),
                )
            )

        return DetectorResult(
            detector=self.name,
            findings=findings,
            ok=True,
        )


def _extract_data_availability_section(
    text: str,
) -> str | None:
    """Try to extract just the data-availability section.

    The detection is intentionally permissive: any of the
    following headings count as the start of a data-availability
    section:

      * "Data Availability"
      * "Data Availability Statement"
      * "Data Sharing"
      * "Data deposition"
      * "Availability of data"
      * "Data and materials availability"

    We then take 800 words from that point (or up to the next
    section heading) as the section. If no heading is found,
    we return None and the caller falls back to scanning the
    full document.
    """
    # Section-heading patterns: 1-2 line headings with optional
    # numbering ("1.", "1.1", etc.). Word-boundary aware.
    #
    # The leading boundary is permissive: a section heading can
    # be either at the start of a line OR follow a sentence-
    # ending punctuation (".", "?"). This is needed because
    # some PDFs put the data-availability section in the same
    # paragraph as the rest of the paper, separated only by
    # a period.
    #
    # We also accept a single space or 2+ spaces before the
    # heading, because ``manusift.ingest.pdf`` joins text
    # blocks with spaces rather than preserving newlines.
    # This is a real edge case for PLOS papers where the
    # data-availability section appears as a separate
    # paragraph but loses its leading newline when the
    # text_blocks are joined.
    #
    # The trailing boundary is also permissive: a heading can
    # be followed by ":", ".", "\n", " " (mid-sentence case
    # like "Data availability statement The original..."), or
    # even end-of-string. Word-boundary rules apply to the
    # heading itself so we don't match a sub-string of a longer
    # phrase like "data-availability-statement" with a hyphen.
    heading = re.compile(
        r"(?:^|\n|\.\s+|\?\s+| {1,})(?<![A-Za-z0-9])"
        r"(?:\d+(?:\.\d+)?\.?\s+)?"
        r"(data availability(?:\s+statement)?|data "
        r"sharing|data deposition|availability of data|"
        r"data and materials availability|availability "
        r"of materials|raw data availability)(?=[:\.\n\s]|$)",
        re.IGNORECASE,
    )
    m = heading.search(text)
    if not m:
        return None
    start = m.end()
    # Take the next 800 words or until the next all-caps / numbered
    # section heading.
    chunk = text[start:start + 8000]
    # Stop at a section boundary that looks like a major heading.
    next_heading = re.search(
        r"\n\s*(?:[A-Z][A-Z\s]{4,}|\d+\.\s+[A-Z][a-z]+)",
        chunk,
    )
    if next_heading:
        chunk = chunk[:next_heading.start()]
    # Trim to 800 words.
    words = chunk.split()
    if len(words) > 800:
        words = words[:800]
    return " ".join(words)


def _format_evidence(
    snippet: str, category: str, severity: str,
) -> str:
    """Format the JSON evidence block for the finding."""
    return (
        '{'
        f'"category": "{category}", '
        f'"severity_class": "{severity}", '
        f'"snippet": {repr(snippet.strip())[:400]}'
        '}'
    )
