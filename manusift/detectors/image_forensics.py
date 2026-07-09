"""Image forensics detector: Error Level Analysis + copy-move.

Two classic paper-integrity checks, both running per image:

1. **Error Level Analysis (ELA)** — re-save the raster at a known
   JPEG quality, diff against the original, and measure the
   std-deviation of the per-pixel error. A composite region (e.g.
   an image spliced in from another source) tends to show a
   noticeably higher local error than the untouched background.
   This implementation is deliberately the textbook version; it is
   good enough to *flag candidates* for human review, not to
   *prove* forgery.

2. **Copy-move** — split the image into an N×N grid, perceptual-hash
   each cell, and report pairs whose Hamming distance is below a
   threshold. A common forgery pattern is to clone a small region
   to cover something up; the cloned region often ends up looking
   near-identical to the original under cell-level pHash.

Both checks need pixel access, so the detector reads
``ExtractedImage.image_path`` (written by :mod:`manusift.ingest.pdf`).
Images without a path are silently skipped — the rest of the
pipeline keeps going.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import Settings, get_settings
from ..contracts import ExtractedImage, Finding, ParsedDoc
from ..trace import get_logger
from .base import DetectorResult

log = get_logger(__name__)


# R-2026-06-19 (P1-C1):
# the long-side cap
# for ELA analysis.
# A 1024-px long
# side keeps the
# working set under
# ~6 MB per image
# (1024 * 1024 *
# 3 channels * 2
# numpy copies *
# int16 / 1e6 ~=
# 12 MB peak for
# the reencoded
# image + 6 MB for
# the original =
# 18 MB).  Increase
# via
# ``MANUSIFT_ELA_MAX_PIXELS``
# env var if the
# user's papers
# have tiny fonts
# that need more
# detail.
_MAX_ELA_PIXELS = int(
    os.environ.get("MANUSIFT_ELA_MAX_PIXELS", "1024")
)


# ---------------------------------------------------------------------------
# ELA
# ---------------------------------------------------------------------------

def _ela_std(path: Path, quality: int) -> tuple[float, float]:
    """Return ``(global_std, max_local_block_std)`` of the per-pixel ELA error.

    A small pasted patch only changes a few percent of the pixels, so
    the *global* std is often tiny even when the patch region itself
    is very different. We also compute the per-block std on an
    eight-by-eight grid of blocks and return the maximum. The maximum
    is the discriminant that catches splices: a uniform re-encoded
    image has small local block std; an image with a high-frequency
    spliced region has at least one block with notably larger std.

    R-2026-06-19 (P1-C1):
    the previous
    implementation held
    two full PIL images
    (original + reencoded)
    and two numpy int16
    arrays in memory
    simultaneously. For a
    50 MB JPEG (e.g.
    8000x6000 px), that's
    4 copies ~= 800 MB per
    image -> 24 GB for 30
    images -> OOM. The
    fix: downscale images
    larger than
    ``_MAX_ELA_PIXELS`` on
    the long side BEFORE
    re-encoding so the
    working set stays
    under 50 MB / image.
    ELA statistics are
    scale-invariant (re-
    encoding at JPEG
    q=N produces a
    similar local/global
    std ratio at any
    resolution) so the
    downscale does not
    change the
    discriminative power.

    Returns ``(nan, nan)`` if the image cannot be opened.
    """
    try:
        with Image.open(path) as original_raw:
            # Downscale *before* ``.convert("RGB")``
            # so the convert pipeline also
            # runs on the smaller image.
            # PIL's ``thumbnail`` is in-place
            # and preserves aspect ratio.
            if max(original_raw.size) > _MAX_ELA_PIXELS:
                original_raw.thumbnail(
                    (_MAX_ELA_PIXELS, _MAX_ELA_PIXELS),
                    Image.Resampling.LANCZOS,
                )
            original = original_raw.convert("RGB")
            # Release the raw PIL image so
            # only one RGB image is in memory.
            del original_raw
            buf = io.BytesIO()
            original.save(buf, format="JPEG", quality=quality)
            buf.seek(0)
            reencoded = Image.open(buf).convert("RGB")
            # The buffer's JPEG is small
            # (~50 KB), so we can close it
            # now to free the bytes.
            buf.close()
    except Exception as exc:  # noqa: BLE001
        log.warning("ELA decode failed", extra={"path": str(path), "err": str(exc)})
        return float("nan"), float("nan")

    a = np.asarray(original, dtype=np.int16)
    # Free the original PIL image; the
    # numpy copy is the only one we need
    # for the diff computation.
    del original
    b = np.asarray(reencoded, dtype=np.int16)
    del reencoded
    diff = a - b
    del a, b
    global_std = float(diff.std())

    # Eight-by-eight block grid max-std.
    h, w = diff.shape[0], diff.shape[1]
    bh, bw = max(1, h // 8), max(1, w // 8)
    max_local = 0.0
    for r in range(8):
        for c in range(8):
            block = diff[
                r * bh : (r + 1) * bh,
                c * bw : (c + 1) * bw,
            ]
            if block.size == 0:
                continue
            s = float(block.std())
            if s > max_local:
                max_local = s
    return global_std, max_local


def _ela_check(
    img: ExtractedImage,
    settings: Settings,
) -> tuple[str, str, str, str, dict] | None:
    """Compute ELA. Returns ``(severity, title, evidence, location, raw)`` or
    ``None`` if the image should be skipped."""
    if img.image_path is None:
        return None
    path = Path(img.image_path)
    if not path.exists():
        return None
    if img.bytes_size < 64:
        # Too tiny to produce a meaningful ELA signal (icons, separators).
        return None

    std, max_local = _ela_std(path, settings.ela_quality)
    if np.isnan(std):
        return None

    # Use max-local-block-std as the trigger. A uniformly-edited
    # image has both stds low; a spliced image has max_local much
    # higher than global.
    if max_local < settings.ela_std_threshold:
        return None

    severity = (
        # R-2026-06-15 (Phase 6 + #6):
        # the ELA severity threshold
        # was previously
        # ``max_local >= threshold * 1.5``
        # => high, else medium.  A
        # *slight* exceedance over
        # the threshold (e.g.
        # ``max_local = 3.5`` with
        # ``threshold = 3.0``)
        # triggered medium severity
        # and inflated the count.
        # The v2 30-case benchmark
        # shows 120 "Image has
        # anomalously high JPEG
        # re-encoding error"
        # findings, all high.
        # New thresholds (more
        # conservative, biased
        # toward false-negatives
        # because ELA is a noisy
        # detector):
        #   >= threshold * 2.5 => high
        #   >= threshold * 1.5 => medium
        #   >= threshold       => low
        "high"
        if max_local
        >= settings.ela_std_threshold * 2.5
        else "medium"
        if max_local
        >= settings.ela_std_threshold * 1.5
        else "low"
    )
    title = "Image has anomalously high JPEG re-encoding error"
    evidence = (
        f"ELA global std = {std:.2f}; max local block std = {max_local:.2f} "
        f"(threshold {settings.ela_std_threshold:.1f}). A small pasted or "
        "spliced region usually only moves a few percent of pixels, so the "
        "global std can stay low; the *max local* std is the more reliable "
        "discriminator. Inspect the high-error block manually before drawing "
        "conclusions."
    )
    location = f"Page {img.page + 1} / image {img.index}"
    raw = {
        "kind": "ela",
        "page": img.page,
        "index": img.index,
        "ela_global_std": std,
        "ela_max_local_std": max_local,
        "ela_quality": settings.ela_quality,
        "threshold": settings.ela_std_threshold,
        "image_path": str(path),
    }
    return severity, title, evidence, location, raw


# ---------------------------------------------------------------------------
# Copy-move
# ---------------------------------------------------------------------------

def _cell_phash(cell: Image.Image) -> str:
    """Eight-by-eight average-hash on a single cell, 16-hex-char output."""
    g = cell.convert("L").resize((8, 8))
    get_flattened_data = getattr(g, "get_flattened_data", None)
    pixels = tuple(
        get_flattened_data()
        if get_flattened_data is not None
        else g.getdata()
    )
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p > avg else "0" for p in pixels)
    return f"{int(bits, 2):016x}"


def _copy_move_pairs(
    img: ExtractedImage,
    settings: Settings,
) -> list[tuple[int, int, int, int, int]]:
    """Return list of ``(row_a, col_a, row_b, col_b, hamming)`` matches."""
    if img.image_path is None:
        return []
    path = Path(img.image_path)
    if not path.exists():
        return []
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w < 32 or h < 32:
                return []
            grid = settings.copy_move_grid
            cell_w = w // grid
            cell_h = h // grid
            if cell_w < 8 or cell_h < 8:
                return []
            hashes: list[tuple[int, int, str]] = []
            for r in range(grid):
                for c in range(grid):
                    box = (c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h)
                    cell = im.crop(box)
                    hashes.append((r, c, _cell_phash(cell)))
    except Exception as exc:  # noqa: BLE001
        log.warning("copy-move decode failed", extra={"path": str(path), "err": str(exc)})
        return []

    matches: list[tuple[int, int, int, int, int]] = []
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            r1, c1, h1 = hashes[i]
            r2, c2, h2 = hashes[j]
            # Only flag *spatially separated* cells — adjacent cells match
            # trivially because they share content. We require either
            # different row or a column gap of >= 2.
            if abs(r1 - r2) < 1 and abs(c1 - c2) < 2:
                continue
            ai = int(h1, 16)
            bi = int(h2, 16)
            d = bin(ai ^ bi).count("1")
            if d <= settings.copy_move_hamming_threshold:
                matches.append((r1, c1, r2, c2, d))
    return matches


def _copy_move_check(
    img: ExtractedImage,
    settings: Settings,
) -> tuple[str, str, str, str, dict] | None:
    """Run copy-move. Returns ``(severity, title, evidence, location, raw)``
    or ``None`` if no match."""
    matches = _copy_move_pairs(img, settings)
    if not matches:
        return None

    matches.sort(key=lambda m: m[4])
    best = matches[0]
    # R-2026-06-15 (Phase 6 + #6):
    # the copy-move severity
    # threshold was previously
    # 3+ matches => high, 2 =>
    # medium, 1 => low.  The
    # v2 30-case benchmark shows
    # 177 "Possible copy-move
    # region" findings -- 60% of
    # all 297 image_forensics
    # findings -- most of them on
    # benign images.  With
    # ``copy_move_grid=8`` and
    # ~64 cells per image, the
    # grid produces ~2016 pairs to
    # compare and a pHash
    # hamming <= 6 / 64 bits is a
    # *very* loose threshold
    # (3 bits per cell off).  A
    # real spliced image typically
    # produces dozens of matches
    # in a localised area; a
    # clean image produces 0-3
    # random matches.  The new
    # thresholds are:
    #   >= 15 matches => high
    #   >=  5 matches => medium
    #   >=  1 match   => low
    if len(matches) >= 15:
        severity = "high"
    elif len(matches) >= 5:
        severity = "medium"
    else:
        severity = "low"

    title = "Possible copy-move region inside this image"
    evidence = (
        f"Found {len(matches)} near-duplicate grid-cell pair(s) "
        f"within the same image. The strongest match (hamming="
        f"{best[4]}) is between cell ({best[0]},{best[1]}) and "
        f"cell ({best[2]},{best[3]}). Often indicates a small "
        "region was cloned to cover something up."
    )
    location = f"Page {img.page + 1} / image {img.index}"
    raw = {
        "kind": "copy_move",
        "page": img.page,
        "index": img.index,
        "grid": settings.copy_move_grid,
        "match_count": len(matches),
        "best": {
            "cell_a": [best[0], best[1]],
            "cell_b": [best[2], best[3]],
            "hamming": best[4],
        },
        "image_path": img.image_path,
    }
    return severity, title, evidence, location, raw


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

_TEXTURE_GRID = 4
_TEXTURE_CELL_SIDE = 32
_TEXTURE_MIN_STD = 12.0
_TEXTURE_MAX_FINDINGS = 20
_TEXTURE_NEAR_HASH_DISTANCE = 4


def _rotated_cell_hashes(cell: Image.Image) -> dict[int, str]:
    """Average-hash variants for right-angle rotations of a texture cell."""
    # ponytail: right-angle rotations cover common copied-panel rotation
    # mistakes; upgrade path is keypoint matching for arbitrary angles/scale.
    return {
        degrees: _cell_phash(cell.rotate(degrees))
        for degrees in (90, 180, 270)
    }


def _texture_cells(
    img: ExtractedImage,
) -> list[tuple[int, int, bytes, str, dict[int, str], float]]:
    """Return high-information grid-cell fingerprints for one image."""
    if img.image_path is None:
        return []
    path = Path(img.image_path)
    if not path.exists():
        return []
    try:
        with Image.open(path) as im:
            im = im.convert("L").resize((256, 256))
            w, h = im.size
            cell_w = w // _TEXTURE_GRID
            cell_h = h // _TEXTURE_GRID
            cells: list[tuple[int, int, bytes, str, dict[int, str], float]] = []
            for r in range(_TEXTURE_GRID):
                for c in range(_TEXTURE_GRID):
                    cell = im.crop(
                        (
                            c * cell_w,
                            r * cell_h,
                            (c + 1) * cell_w,
                            (r + 1) * cell_h,
                        )
                    ).resize(
                        (
                            _TEXTURE_CELL_SIDE,
                            _TEXTURE_CELL_SIDE,
                        )
                    )
                    arr = np.asarray(cell, dtype=np.uint8)
                    std = float(arr.std())
                    if std < _TEXTURE_MIN_STD:
                        continue
                    cells.append(
                        (
                            r,
                            c,
                            arr.tobytes(),
                            _cell_phash(cell),
                            _rotated_cell_hashes(cell),
                            std,
                        )
                    )
            return cells
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "texture-overlap decode failed",
            extra={"path": str(path), "err": str(exc)},
        )
        return []


def _texture_overlap_findings(
    doc: ParsedDoc,
) -> list[Finding]:
    """Find exact high-texture cell reuse across different images."""
    seen: dict[bytes, tuple[ExtractedImage, int, int, str, dict[int, str], float]] = {}
    near_seen: list[tuple[ExtractedImage, int, int, str, dict[int, str], float]] = []
    findings: list[Finding] = []
    for img in doc.images:
        for row, col, fp, ahash, rotated_hashes, std in _texture_cells(img):
            prev = seen.get(fp)
            if prev is None:
                seen[fp] = (img, row, col, ahash, rotated_hashes, std)
            else:
                other, other_row, other_col, _other_hash, _other_rotated_hashes, other_std = prev
                if (other.page, other.index) == (img.page, img.index):
                    continue
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=ImageForensicsDetector.name,
                        severity="high",
                        title=(
                            "Near-identical local image texture reused "
                            "across images"
                        ),
                        evidence=(
                            "Two different extracted images contain an "
                            "identical high-variance local texture block. "
                            "This is consistent with reused gel/band, "
                            "shadow, or defect texture and warrants manual "
                            "inspection of the source panels."
                        ),
                        location=(
                            f"Page {other.page + 1} / image {other.index} "
                            f"cell ({other_row},{other_col}) -> "
                            f"Page {img.page + 1} / image {img.index} "
                            f"cell ({row},{col})"
                        ),
                        raw={
                            "kind": "texture_overlap",
                            "image_a": {
                                "page": other.page,
                                "index": other.index,
                                "image_path": other.image_path,
                            },
                            "image_b": {
                                "page": img.page,
                                "index": img.index,
                                "image_path": img.image_path,
                            },
                            "cell_a": [other_row, other_col],
                            "cell_b": [row, col],
                            "grid": _TEXTURE_GRID,
                            "cell_side": _TEXTURE_CELL_SIDE,
                            "std_a": other_std,
                            "std_b": std,
                        },
                    )
                )
                if len(findings) >= _TEXTURE_MAX_FINDINGS:
                    return findings
                continue
            for (
                other,
                other_row,
                other_col,
                other_hash,
                other_rotated_hashes,
                other_std,
            ) in near_seen:
                if (other.page, other.index) == (img.page, img.index):
                    continue
                rotation_match = next(
                    (
                        degrees
                        for degrees, rotated_hash in other_rotated_hashes.items()
                        if rotated_hash == ahash
                    ),
                    None,
                )
                if rotation_match is None:
                    rotation_match = next(
                        (
                            degrees
                            for degrees, rotated_hash in rotated_hashes.items()
                            if rotated_hash == other_hash
                        ),
                        None,
                    )
                if rotation_match is not None:
                    findings.append(
                        Finding.make(
                            trace_id=doc.trace_id,
                            detector=ImageForensicsDetector.name,
                            severity="medium",
                            title=(
                                "Rotated local image texture reused across images"
                            ),
                            evidence=(
                                "Two different extracted images contain a "
                                "matching high-variance local texture block "
                                "after a right-angle rotation. This can match "
                                "reused gel/band, shadow, or defect texture "
                                "and warrants manual inspection."
                            ),
                            location=(
                                f"Page {other.page + 1} / image {other.index} "
                                f"cell ({other_row},{other_col}) -> "
                                f"Page {img.page + 1} / image {img.index} "
                                f"cell ({row},{col})"
                            ),
                            raw={
                                "kind": "rotated_texture_overlap",
                                "image_a": {
                                    "page": other.page,
                                    "index": other.index,
                                    "image_path": other.image_path,
                                },
                                "image_b": {
                                    "page": img.page,
                                    "index": img.index,
                                    "image_path": img.image_path,
                                },
                                "cell_a": [other_row, other_col],
                                "cell_b": [row, col],
                                "grid": _TEXTURE_GRID,
                                "cell_side": _TEXTURE_CELL_SIDE,
                                "rotation_degrees": rotation_match,
                                "std_a": other_std,
                                "std_b": std,
                            },
                        )
                    )
                    if len(findings) >= _TEXTURE_MAX_FINDINGS:
                        return findings
                    break
                distance = bin(int(ahash, 16) ^ int(other_hash, 16)).count("1")
                if distance > _TEXTURE_NEAR_HASH_DISTANCE:
                    continue
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=ImageForensicsDetector.name,
                        severity="medium",
                        title=(
                            "Similar local image texture reused across images"
                        ),
                        evidence=(
                            "Two different extracted images contain highly "
                            "similar high-variance local texture. This can "
                            "match reused gel/band, shadow, or defect texture "
                            "after brightness or compression changes and "
                            "warrants manual inspection."
                        ),
                        location=(
                            f"Page {other.page + 1} / image {other.index} "
                            f"cell ({other_row},{other_col}) -> "
                            f"Page {img.page + 1} / image {img.index} "
                            f"cell ({row},{col})"
                        ),
                        raw={
                            "kind": "near_texture_overlap",
                            "image_a": {
                                "page": other.page,
                                "index": other.index,
                                "image_path": other.image_path,
                            },
                            "image_b": {
                                "page": img.page,
                                "index": img.index,
                                "image_path": img.image_path,
                            },
                            "cell_a": [other_row, other_col],
                            "cell_b": [row, col],
                            "grid": _TEXTURE_GRID,
                            "cell_side": _TEXTURE_CELL_SIDE,
                            "hash_distance": distance,
                            "std_a": other_std,
                            "std_b": std,
                        },
                    )
                )
                if len(findings) >= _TEXTURE_MAX_FINDINGS:
                    return findings
                break
            # ponytail: keep a flat list of prior high-texture cells; upgrade
            # path is bucketing by hash prefix if large image sets make this
            # O(n^2) comparison too slow.
            near_seen.append((img, row, col, ahash, rotated_hashes, std))
    return findings

class ImageForensicsDetector:
    """Image-forensics analysis: Error Level Analysis (ELA) on every
    extracted image, a copy-move check inside each image, and exact
    high-texture block reuse across different images. ELA
    surfaces regions that were re-encoded at a different JPEG quality
    than the surrounding background -- the typical signal of a region
    pasted in from another source. The copy-move check tiles the image
    into a grid and looks for two cells whose pixel histograms are
    nearly identical, which indicates a region was cloned within the
    same image to cover something up. The cross-image check flags
    identical high-variance local texture blocks, such as reused
    protein-band texture, repeated shadows, or copied defects. Images
    that lack a file path on disk (synthetic test fixtures, for
    example) are skipped; this detector never produces a finding for
    an image it cannot decode. Returns one ``DetectorResult`` carrying
    zero or more findings.
    """

    name = "image_forensics"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        settings = get_settings()
        findings: list[Finding] = []
        for img in doc.images:
            ela = _ela_check(img, settings)
            if ela is not None:
                sev, title, ev, loc, raw = ela
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity=sev,
                        title=title,
                        evidence=ev,
                        location=loc,
                        raw=raw,
                    )
                )
            cm = _copy_move_check(img, settings)
            if cm is not None:
                sev, title, ev, loc, raw = cm
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity=sev,
                        title=title,
                        evidence=ev,
                        location=loc,
                        raw=raw,
                    )
                )
        findings.extend(_texture_overlap_findings(doc))
        return DetectorResult(detector=self.name, ok=True, findings=findings)
