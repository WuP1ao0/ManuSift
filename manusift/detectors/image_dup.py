"""Image duplicate detector.

Compares every pair of images by perceptual-hash Hamming distance.
Pairs below the configured threshold are flagged. Step 1 keeps it
simple — N^2 over images. With typical figures (5-30) the cost is
trivial; Step 2 can index larger archives if needed.
"""
from __future__ import annotations

from ..config import get_settings
from ..contracts import ExtractedImage, Finding, ParsedDoc
from .base import DetectorResult


def _hamming(a: str, b: str) -> int:
    """Hex-string Hamming distance."""
    if len(a) != len(b):
        # Different pHash lengths cannot be compared meaningfully.
        return len(a) * 4 + len(b) * 4
    ai = int(a, 16)
    bi = int(b, 16)
    return bin(ai ^ bi).count("1")


class ImageDuplicateDetector:
    """Detect near-duplicate images inside the PDF using a
    perceptual hash (pHash) and Hamming distance. Surfaces
    cases where the same figure was reused across pages or
    paper mills inserted the same stock image across many
    submissions. Every pair of images is compared; pairs whose
    Hamming distance is at or below the configured threshold
    (a project-wide setting, default 8 bits of 64) are flagged
    as a single high-severity finding. The detector returns an
    empty ``DetectorResult.findings`` list when the document
    has zero or one image, or when all images have distinct
    pHashes. With typical figures (5-30 images per paper) the
    N-squared comparison is fast; for a million-image archive
    swap in faiss.
    """

    name = "image_dup"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        settings = get_settings()
        threshold = settings.image_duplicate_hamming_threshold
        images: list[ExtractedImage] = doc.images
        findings: list[Finding] = []

        # R-2026-06-19
        # (P0-A1/C3):
        # classify
        # images by
        # size BEFORE
        # the N^2
        # pair loop so
        # we can (a)
        # skip pairs
        # where EITHER
        # image is too
        # small (no
        # false-dup
        # signal from
        # blank
        # icons) and
        # (b) surface
        # the skip
        # count in
        # the stats
        # dict for
        # the report
        # renderer.
        from ._image_size import summarize_image_sizes

        size_stats = summarize_image_sizes(images)
        # R-2026-06-21 (CDE-DETER):
        # explicit
        # sorted list
        # (not a set)
        # so iteration
        # order is
        # deterministic
        # across
        # Python
        # versions /
        # PYTHONHASHSEED
        # settings.
        # Previously a
        # set literal
        # was used,
        # which
        # depended on
        # hash() of
        # the int keys
        # (mostly stable
        # but NOT a
        # contractual
        # guarantee).
        # See
        # tests/test_cde_deter_image_dup.py
        # for the
        # determinism
        # regression
        # test.
        eligible_indexes = sorted(
            i
            for i, img in enumerate(images)
            if img.width >= 64
            and img.height >= 64
            and img.bytes_size >= 5 * 1024
        )

        for i in eligible_indexes:
            for j in eligible_indexes:
                if j <= i:
                    continue
                a, b = images[i], images[j]
                # Skip degenerate
                # images whose pHash
                # could not be
                # computed (small
                # icons / solid
                # colour / decode
                # error). Comparing
                # two None-valued
                # phashes as 0
                # Hamming distance
                # would mark every
                # blank icon as a
                # duplicate of
                # every other blank
                # icon -- exactly
                # the bug fixed in
                # this detector's
                # companion
                # change in
                # ``_compute_phash``.
                pa = a.phash
                pb = b.phash
                if not pa or not pb:
                    continue
                d = _hamming(pa, pb)
                if d <= threshold:
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=self.name,
                            severity="high",
                            title="Near-duplicate image detected",
                            evidence=(
                                f"Image p{i} (page {a.page + 1}) and p{j} "
                                f"(page {b.page + 1}) share pHash distance "
                                f"{d} (≤{threshold})."
                            ),
                            location=(
                                f"Page {a.page + 1} / image {a.index}  ↔  "
                                f"Page {b.page + 1} / image {b.index}"
                            ),
                            raw={
                                "image_a": {"page": a.page, "index": a.index, "phash": pa},
                                "image_b": {"page": b.page, "index": b.index, "phash": pb},
                                "hamming": d,
                            },
                        )
                    )
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=findings,
            stats=size_stats.to_stats_dict(),
        )
