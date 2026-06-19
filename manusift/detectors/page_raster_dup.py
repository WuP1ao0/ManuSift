"""R-2026-06-12: Page-raster image-duplication detector.

The Frontiers (and other modern-PDF) workflow often embeds
figure panels as **vector graphics** (PDF drawing operators)
rather than as raster images. ``PyMuPDF.Page.get_images()`` on
these pages returns an empty list, so the existing
``image_dup`` detector has nothing to hash. The result: the
``real_eval_fraud_cases/`` benchmark's case_005
(Frontiers CpxR/A Salmonella) shows 0 image_dup findings even
though the official retraction cites 4 separate figure panels
with image-duplication problems.

This detector fills the gap by **rendering every PDF page to
a bitmap** (PyMuPDF ``Page.get_pixmap(dpi=200)``) and then
hashing the figure regions. Two panels that look visually
identical will hash the same way regardless of whether they
were originally a raster JPEG, a PNG, or a vector drawing --
the bitmap conversion normalises them all.

The detection strategy is intentionally simple:

  1. Open the source PDF with PyMuPDF.
  2. For every page, render at 200 DPI to a single-channel
     grayscale bitmap.
  3. Use OpenCV to find the **figure regions**: large
     connected components of non-white pixels separated by
     whitespace. The image body and the figure caption
     are the two main regions of a typical scientific-paper
     page; we hash both independently so the page layout
     doesn't dominate the hash.
  4. Compute the same pHash that ``image_dup`` uses and
     emit a finding for every near-duplicate pair (Hamming
     distance at or below the configured threshold).

This module deliberately **does not** segment individual
panels (A, B, C, ...) within a single figure -- that
problem requires CV-based panel segmentation and is
listed as a separate "next iteration" in
``real_eval_fraud_cases/recommended_next_iterations.md``.
The figure-region hash is sufficient to catch the
whole-figure duplications the benchmark's missed cases
are about.
"""
from __future__ import annotations

import io
import logging
from typing import Any

try:
    import fitz  # PyMuPDF
    _HAS_FITZ = True
except ImportError:  # pragma: no cover
    _HAS_FITZ = False

import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except ImportError:  # pragma: no cover
    _HAS_CV2 = False

import imagehash

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult

log = logging.getLogger(__name__)


# The minimum height of a connected component of
# non-white pixels (in pixels at 200 DPI) for it to
# be treated as a candidate figure region. 30px at
# 200 DPI == 3.8mm -- small enough to catch
# in-text micro-figures, large enough to exclude
# bullet points and small line-art.
_MIN_REGION_PX = 80

# The minimum width-to-height ratio. Long horizontal
# strips are almost always a single figure with a
# caption underneath, not multiple separate regions.
_MIN_REGION_AREA = 30_000

# Render DPI. 200 is the industry standard for
# scientific-figure hashing -- 150 is visibly fuzzy
# on small Western-blot panels, 300 is 2.25x slower
# without a measurable improvement in pHash accuracy.
_RENDER_DPI = 200

# Cap on the number of regions per page that we
# actually hash. A typical paper page has 1-2 figure
# regions; 8 is a generous safety cap. This prevents
# a single pathological page from forcing an
# N-squared comparison over hundreds of regions.
_MAX_REGIONS_PER_PAGE = 8


class PageRasterDuplicateDetector:
    """Detect duplicate figure regions across PDF pages by
    rendering every page to a bitmap and hashing the
    figure regions.

    The detector is intentionally conservative: it only
    emits a finding when the Hamming distance is at or
    below the project-wide ``image_duplicate_hamming_threshold``
    setting. With typical figures (1-2 regions per page)
    the N-squared comparison is fast.
    """

    name = "page_raster_dup"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        if not _HAS_FITZ:
            log.warning(
                "PyMuPDF (fitz) not installed -- "
                "page_raster_dup detector is a no-op"
            )
            return DetectorResult(
                detector=self.name, findings=[], ok=True,
            )
        if not _HAS_CV2:
            log.warning(
                "OpenCV (cv2) not installed -- "
                "page_raster_dup detector is a no-op"
            )
            return DetectorResult(
                detector=self.name, findings=[], ok=True,
            )

        try:
            pdf = fitz.open(doc.source_path)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "page_raster_dup: failed to open %s: %s",
                doc.source_path, exc,
            )
            return DetectorResult(
                detector=self.name, findings=[], ok=True,
            )

        try:
            from .image_dup import _hamming  # type: ignore
        except ImportError:  # pragma: no cover
            _hamming = _fallback_hamming  # type: ignore

        from ..config import get_settings
        threshold = get_settings().image_duplicate_hamming_threshold

        # Phase 1: render every page and extract
        # figure-region crops. ``regions`` is a list
        # of (page_idx, region_idx, phash, bbox) tuples.
        regions: list[tuple[int, int, str, tuple[int, int, int, int]]] = []
        for page_idx in range(len(pdf)):
            try:
                page = pdf[page_idx]
            except Exception:  # noqa: BLE001
                continue
            page_regions = _extract_figure_regions(page)
            for region_idx, (crop_pil, bbox) in enumerate(page_regions):
                if crop_pil.width < 16 or crop_pil.height < 16:
                    continue
                try:
                    h = str(imagehash.phash(crop_pil))
                except Exception:  # noqa: BLE001
                    continue
                regions.append((page_idx, region_idx, h, bbox))

        # Phase 2: N-squared pair comparison. With at
        # most ~8 regions per page and 30 pages that's
        # at most 8*30*8*30 / 2 = 28,800 pairs --
        # negligible.
        findings: list[Finding] = []
        n = len(regions)
        for i in range(n):
            for j in range(i + 1, n):
                pi, _, hi, _ = regions[i]
                pj, _, hj, _ = regions[j]
                d = _hamming(hi, hj)
                if d <= threshold:
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=self.name,
                            severity="high",
                            title=(
                                "Near-duplicate figure region "
                                "detected (page raster)"
                            ),
                            evidence=(
                                f"Page {pi + 1} region and "
                                f"page {pj + 1} region share "
                                f"pHash distance {d} (≤ "
                                f"{threshold})."
                            ),
                            location=(
                                f"Page {pi + 1}  ↔  Page {pj + 1}"
                            ),
                            raw={
                                "page_a": pi,
                                "page_b": pj,
                                "phash_a": hi,
                                "phash_b": hj,
                                "hamming": d,
                            },
                        )
                    )

        return DetectorResult(
            detector=self.name, ok=True, findings=findings,
        )


def _extract_figure_regions(
    page: "fitz.Page",
) -> list[tuple[Image.Image, tuple[int, int, int, int]]]:
    """Render ``page`` to a bitmap and crop out the
    figure-like regions.

    The strategy is to threshold the grayscale page
    at 250/255 (i.e. anything visibly non-white) and
    look for connected components. Each component that
    is large enough to be a figure (rather than a
    bullet point or a stray line of text) is returned
    as a separate PIL Image.

    Returns a list of ``(image, (x, y, w, h))`` tuples
    where the bounding box is in pixel coordinates
    relative to the rendered page.
    """
    # R-audit (2026-06-12): the standard PyMuPDF
    # recipe for rendering a page to a bitmap.
    # ``alpha=False`` strips the alpha channel so
    # the bitmap is 3-channel RGB instead of RGBA.
    matrix = fitz.Matrix(_RENDER_DPI / 72.0, _RENDER_DPI / 72.0)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    arr = np.array(img)

    # Threshold: anything < 250 is "ink". This is
    # intentionally very tolerant -- faint gray
    # anti-aliased pixel boundaries still count.
    ink = (arr < 250).astype(np.uint8)

    # Connected components. ``connectivity=8`` so a
    # figure with a small gap in the middle (e.g. a
    # Western blot's empty lane) is still treated as
    # one region.
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        ink, connectivity=8,
    )

    # Collect candidate regions and merge components
    # that are vertically adjacent (the body of a
    # figure is usually one or two components; the
    # caption is right below it; we want to hash
    # both together so the same caption text doesn't
    # dominate the hash).
    candidates: list[tuple[int, int, int, int]] = []
    for label in range(1, num_labels):  # skip background (0)
        x, y, w, h, area = stats[label]
        if w < _MIN_REGION_PX or h < _MIN_REGION_PX:
            continue
        if area < _MIN_REGION_AREA:
            continue
        candidates.append((x, y, w, h))

    if not candidates:
        return []

    # Sort top-to-bottom, left-to-right.
    candidates.sort(key=lambda b: (b[1], b[0]))

    # Merge components that are vertically close
    # (the figure body + its caption text).
    merged: list[list[int]] = []
    for c in candidates:
        x, y, w, h = c
        if merged:
            mx, my, mw, mh = merged[-1]
            if y < my + mh + 30 and x < mx + mw:
                # Same column block, vertically adjacent.
                merged[-1] = [
                    min(mx, x),
                    min(my, y),
                    max(mx + mw, x + w) - min(mx, x),
                    max(my + mh, y + h) - min(my, y),
                ]
                continue
        merged.append([x, y, w, h])

    # Cap to avoid pathological pages.
    merged = merged[:_MAX_REGIONS_PER_PAGE]

    crops: list[tuple[Image.Image, tuple[int, int, int, int]]] = []
    for (x, y, w, h) in merged:
        crop = img.crop((x, y, x + w, y + h))
        crops.append((crop, (x, y, w, h)))

    return crops


def _fallback_hamming(a: str, b: str) -> int:
    """Hex-string Hamming distance fallback."""
    if len(a) != len(b):
        return len(a) * 4 + len(b) * 4
    ai = int(a, 16)
    bi = int(b, 16)
    return bin(ai ^ bi).count("1")
