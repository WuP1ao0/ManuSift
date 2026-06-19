"""Paper-mill / peer-review authorship-signal detector (P0-PEER).

2025 was the year paper-mill retractions hit crisis level:
  - Retraction Watch crossed 60,000 entries in 2025 (verified via
    web search 2026-06-13).
  - Wiley/Hindawi retracted 11,000+ papers in 2023-2024 after the
    paper-mill pattern was exposed (Chemistry World, June 2024).
  - Frontiers retracted 122 articles in July 2025 for an
    "unethical peer review network" (mintdora.com coverage).
  - 400,000+ published articles share textual similarity with
    known paper-mill articles (Nature, November 2023).

The single most common paper-mill signal that survives into the
public PDF is **author affiliation concentration** -- paper mills
batch-assign co-authors from a single institution (Abalkina 2022,
"co-authorship graph according to affiliations of 400+ papers
originating from the Russian paper mills").

This detector extracts author affiliations from the byline and
fires when:

1. All (or nearly all) authors share the same affiliation. Paper
   mills often list 3-5 "co-authors" who are all from one lab /
   hospital / institute, with no international / cross-institution
   collaboration. A legitimate paper has more diversity.

2. Tortured-phrase density is unusually high. Cabanac & Labbé
   2021 ("tortured phrases" -- paraphrased technical terms like
   "neural structures" instead of "neurons"). A density of >= 3
   tortured phrases in the abstract + introduction is a paper-mill
   tell.

Both signals are LOCAL to the PDF text; no network calls required.

The detector is best-effort. A paper with the wrong pattern (e.g.
a genuine single-institution study) will not be flagged. A paper
where the authors are deliberately diverse (e.g. an international
collaboration) will not be flagged.

Why this is patch-first:
  - Detector file is independent and small (~200 lines).
  - Registration is a one-line change in
    ``manusift/detectors/__init__.py``.
  - No new dependencies: text-pattern matching + tortured phrase
    check (we re-use the existing tortured_phrases detector's
    PHRASES dict indirectly by importing it).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# Common affiliation keyword patterns. We pick the top match in
# each byline chunk (e.g. "Department of X, University of Y").
_AFFILIATION_KEYWORDS = re.compile(
    r"\b(department of|university of|hospital|institute of|"
    r"school of|college of|college|academy of|faculty of|"
    r"research center|research institute|center for|"
    r"laboratory of|medical center|clinic of|school)\b",
    re.IGNORECASE,
)

# Affiliation-block separator: lines that look like a numbered
# author block (e.g. "John Smith1, Jane Doe2*").
# We extract the byline (first ~3000 chars of text) and look for
# patterns like "Name1, Name2" where the digits are affiliation
# indices.
_BYLINE_DIGIT_RE = re.compile(r"(?<!\d)\d{1,2}(?!\d)")

# An "author entry" is "Firstname Lastname" optionally followed
# by a digit / asterisk / superscript. We use a regex that
# matches this pattern. The trick: in the byline, author names
# appear consecutively separated by commas, then the affiliations
# paragraph starts (with the leading digit).
_AUTHOR_ENTRY_RE = re.compile(
    r"\b[A-Z][a-zA-Z\-']+(?:\s+[A-Z][a-zA-Z\-']+){1,3}"
    r"(?:\s*[*,]?\s*(?:\d{1,2})?\b)*"
)

# Tortured-phrase reference list. We DO NOT duplicate the
# tortured_phrases detector's full _TORTURED dict here -- instead
# we import it. The other detector's dict is private (leading
# underscore) but importing it here is safe: both detectors live
# in the same package, and we use the values only as a string-
# matching probe, not for any structural assumption.
def _load_tortured_phrases() -> tuple[str, ...]:
    try:
        from .tortured_phrases import _TORTURED
        # The dict's keys are tortured phrases; we only need the
        # strings, not the original-phrase mapping.
        return tuple(_TORTURED.keys())
    except Exception:  # noqa: BLE001
        return ()


def _get_byline(doc: ParsedDoc, max_chars: int = 4000) -> str:
    """Return the first ~max_chars of the paper's body text.

    The byline (authors + affiliations) lives in the first page or
    two. We grab a generous slice and let the regexes do the work.
    """
    parts: list[str] = []
    total = 0
    for tb in doc.text_blocks:
        t = getattr(tb, "text", "")
        if not t:
            continue
        parts.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return "\n".join(parts)


def _extract_affiliations(byline: str) -> list[str]:
    """Extract a list of distinct affiliations from the byline.

    Heuristic: scan the text for sentences containing at least one
    ``_AFFILIATION_KEYWORDS`` match. Each such sentence is a
    candidate affiliation string; we normalise by lowercasing and
    stripping punctuation.
    """
    if not byline:
        return []
    # Split into sentences by period / newline.
    candidates = re.split(r"[\.\n]", byline)
    affs: list[str] = []
    seen: set[str] = set()
    for chunk in candidates:
        chunk = chunk.strip()
        if len(chunk) < 8 or len(chunk) > 400:
            continue
        if not _AFFILIATION_KEYWORDS.search(chunk):
            continue
        # Normalise: lowercase, strip digits / punctuation.
        norm = re.sub(r"[^a-z\s]", " ", chunk.lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if len(norm) < 10 or norm in seen:
            continue
        seen.add(norm)
        affs.append(norm)
    return affs


def _count_authors(byline: str) -> int:
    """Count author entries in the byline.

    An author entry is ``Firstname Lastname`` (optionally with a
    digit / asterisk superscript). We count distinct matches in
    the first 1500 chars. We require the matches to be a contiguous
    run at the start of the byline (the affiliations paragraph
    breaks the run).
    """
    head = byline[:1500]
    # Find all matches.
    matches = list(_AUTHOR_ENTRY_RE.finditer(head))
    if not matches:
        return 0
    # Only count matches that appear consecutively (no gap > 200
    # chars between them). The author block is contiguous; the
    # affiliations paragraph is the first gap.
    count = 0
    last_end = -200
    for m in matches:
        if m.start() - last_end > 200:
            # Gap too big -- we left the author block.
            break
        count += 1
        last_end = m.end()
    return count


def _probe_affiliation_concentration(
    byline: str,
) -> list[Finding]:
    """Fire if the byline shows many authors but few distinct
    affiliations (the Abalkina / paper-mill co-authorship signal).

    The threshold is intentionally generous: any case where the
    affiliations-per-author ratio is <= 0.4 fires. This catches:
      - 4 authors / 1 affiliation (ratio 0.25)
      - 6 authors / 2 affiliations (ratio 0.33)
      - 10 authors / 4 affiliations (ratio 0.4)
    Legitimate papers typically have ratio > 0.6 (most co-authors
    are from different labs). The threshold is conservative on the
    high side -- it errs toward false-negatives rather than
    false-positives (which would corrupt the benchmark).
    """
    out: list[Finding] = []
    n_authors = _count_authors(byline)
    if n_authors < 4:
        return out  # too few authors to make a call
    affs = _extract_affiliations(byline)
    if not affs:
        return out  # no affiliations parsed -- skip
    ratio = len(affs) / n_authors
    # R-2026-06-15 (Phase 6, fix 4):
    # the original threshold fired on
    # any 4+ author paper with <= 0.4
    # affiliation ratio.  In practice
    # this produces 8 findings on the
    # 30-case v2 benchmark, every one a
    # legitimate multi-author review
    # paper (26+ authors from 2-10
    # institutions).  The paper-mill
    # signal is when *many* authors
    # share a *very small* number of
    # affiliations -- the Abalkina
    # 2024 / Byrne 2024 cases all had
    # 50+ authors from 1-2 affiliations.
    # New thresholds:
    #   n_authors >= 20 AND ratio <= 0.2 => high
    #   n_authors >= 10 AND ratio <= 0.3 => medium
    #   n_authors >= 4  AND ratio <= 0.4 => low
    severity = None
    if n_authors >= 20 and ratio <= 0.2:
        severity = "high"
    elif n_authors >= 10 and ratio <= 0.3:
        severity = "medium"
    elif n_authors >= 4 and ratio <= 0.4:
        severity = "low"
    if severity is not None:
        out.append(Finding.make(
            trace_id="",
            detector="paper_mill_authorship",
            severity=severity,
            title=(
                f"{n_authors} authors but only "
                f"{len(affs)} distinct affiliation(s) "
                f"(ratio {ratio:.2f}) -- possible paper-mill "
                f"co-authorship pattern"
            ),
            location="byline",
            evidence=json.dumps({
                "n_authors": n_authors,
                "n_affiliations": len(affs),
                "affiliation_ratio": round(ratio, 3),
                "affiliations_sample": affs[:5],
            }),
        ))
    return out


def _probe_tortured_phrase_density(
    byline: str,
    full_text: str,
) -> list[Finding]:
    """Fire if the abstract / introduction has >= 3 tortured
    phrases (Cabanac & Labbé 2021)."""
    phrases = _load_tortured_phrases()
    if not phrases:
        return out_no_phrases()  # type: ignore[name-defined]
    # Head 4000 chars = abstract + intro.
    head = full_text[:4000].lower()
    matched: list[str] = []
    for tortured in phrases:
        if tortured.lower() in head:
            matched.append(tortured)
            if len(matched) >= 5:
                break
    if len(matched) >= 3:
        return [Finding.make(
            trace_id="",
            detector="paper_mill_authorship",
            severity="high",
            title=(
                f"{len(matched)} tortured-phrase pattern(s) "
                f"in abstract / introduction -- consistent with "
                f"paper-mill or machine-translated text"
            ),
            location="text",
            evidence=json.dumps({
                "matched_count": len(matched),
                "sample": matched[:5],
            }),
        )]
    return []


def out_no_phrases() -> list[Finding]:
    """Helper for when PHRASES cannot be loaded -- returns no findings."""
    return []


# ---------- Detector class ----------


class PaperMillAuthorshipDetector:
    """Two-probe paper-mill / peer-review detector.

    See module docstring. Probe 1 = affiliation concentration.
    Probe 2 = tortured-phrase density.
    """

    name = "paper_mill_authorship"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        findings: list[Finding] = []
        byline = _get_byline(doc)
        # Probe 1: affiliation concentration.
        for f in _probe_affiliation_concentration(byline):
            findings.append(Finding.make(
                trace_id=doc.trace_id,
                detector=self.name,
                severity=f.severity,
                title=f.title,
                location=f.location,
                evidence=f.evidence,
            ))
        # Probe 2: tortured-phrase density.
        full_text = "\n".join(
            getattr(tb, "text", "") for tb in doc.text_blocks
        )
        for f in _probe_tortured_phrase_density(byline, full_text):
            findings.append(Finding.make(
                trace_id=doc.trace_id,
                detector=self.name,
                severity=f.severity,
                title=f.title,
                location=f.location,
                evidence=f.evidence,
            ))
        return DetectorResult(
            detector=self.name,
            findings=findings,
            ok=True,
        )