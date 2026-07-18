"""Image duplicate detector.

Three-pass comparison of extracted figures:

1. **Primary pHash** — reuse the precomputed ``ExtractedImage.phash``
   and flag pairs at or below the project Hamming threshold
   (default 8 bits of 64). Near-identical pairs (d ≤ 4) are high
   severity; the rest of the primary band is medium.

2. **Secondary multi-hash** — for pairs that missed the primary
   band, recompute aHash + dHash from the on-disk raster. Flag
   when either algorithm is at or below the secondary threshold
   (default 12). Catches crops, re-encodes, and line-drawing
   figures that DCT pHash under-scores.

3. **Region / tile bridge** — for remaining pairs, compare a small
   grid of high-variance cell hashes across different images.
   This bridges the common gap where ``image_forensics`` finds
   local texture reuse (gel bands, blot fragments) but whole-image
   pHash never fires. Severity is medium; findings are capped.

Step 1 keeps N² over images. With typical figures (5–30) the cost
is trivial; Step 2/3 only open rasters when needed.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..contracts import ExtractedImage, Finding, ParsedDoc
from .base import DetectorResult

# Secondary multi-hash band (bits of 64). Softer than primary so
# aHash/dHash can catch re-encoded or slightly cropped figures.
_SECONDARY_HAMMING: int = 12
# High severity when primary Hamming is this tight.
_HIGH_SEVERITY_HAMMING: int = 4

# Region / tile bridge (forensics-hit → image_dup recall).
_REGION_GRID: int = 4
_REGION_CELL_MIN: int = 24  # px; skip tiny cells
_REGION_HAMMING: int = 2
_REGION_MIN_STD: float = 18.0  # skip flat / blank tiles
_REGION_MAX_FINDINGS: int = 40
# Cap multi-hash decode work on very large figure sets.
_MAX_SECONDARY_PAIRS: int = 200


def _hamming(a: str, b: str) -> int:
    """Hex-string Hamming distance."""
    if len(a) != len(b):
        # Different pHash lengths cannot be compared meaningfully.
        return len(a) * 4 + len(b) * 4
    ai = int(a, 16)
    bi = int(b, 16)
    return bin(ai ^ bi).count("1")


def _severity_for_primary(d: int) -> str:
    if d <= _HIGH_SEVERITY_HAMMING:
        return "high"
    return "medium"


def _compute_algo_hash(algo: str, image_path: str | None) -> str | None:
    """Compute aHash / dHash / pHash for a path; None on failure."""
    if not image_path:
        return None
    try:
        import imagehash
        from PIL import Image

        with Image.open(image_path) as img:
            if algo == "ahash":
                h = imagehash.average_hash(img)
            elif algo == "dhash":
                h = imagehash.dhash(img)
            else:
                h = imagehash.phash(img)
        return str(h)
    except Exception:  # noqa: BLE001 — skip corrupt rasters
        return None


def _region_cell_hashes(
    image_path: str | None,
) -> list[tuple[int, int, str, float]]:
    """Return (row, col, ahash_hex, cell_std) for high-variance tiles.

    Uses a fixed grid so cell coordinates are stable across pairs.
    Flat tiles (icons, white margins) are dropped so we do not
    flag blank gutters as texture reuse.
    """
    if not image_path:
        return []
    try:
        from PIL import Image
        import imagehash
        import statistics
    except Exception:  # noqa: BLE001
        return []
    try:
        with Image.open(image_path) as img:
            img = img.convert("L")
            w, h = img.size
            if w < _REGION_CELL_MIN * 2 or h < _REGION_CELL_MIN * 2:
                return []
            cw = max(_REGION_CELL_MIN, w // _REGION_GRID)
            ch = max(_REGION_CELL_MIN, h // _REGION_GRID)
            out: list[tuple[int, int, str, float]] = []
            for r in range(_REGION_GRID):
                for c in range(_REGION_GRID):
                    left = min(c * cw, max(0, w - cw))
                    top = min(r * ch, max(0, h - ch))
                    cell = img.crop((left, top, left + cw, top + ch))
                    # Sample luminance for variance gate.
                    tiny = cell.resize((16, 16))
                    try:
                        sample = list(
                            getattr(tiny, "get_flattened_data", tiny.getdata)()
                        )
                    except Exception:  # noqa: BLE001
                        continue
                    if len(sample) < 4:
                        continue
                    try:
                        std = float(statistics.pstdev(sample))
                    except statistics.StatisticsError:
                        continue
                    if std < _REGION_MIN_STD:
                        continue
                    try:
                        hx = str(imagehash.average_hash(cell))
                    except Exception:  # noqa: BLE001
                        continue
                    out.append((r, c, hx, std))
            return out
    except Exception:  # noqa: BLE001
        return []


class ImageDuplicateDetector:
    """Detect near-duplicate images inside the PDF.

    Primary pHash + secondary multi-hash + region tile bridge.
    See module docstring. Size gates still skip decorative icons.
    """

    name = "image_dup"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        settings = get_settings()
        threshold = settings.image_duplicate_hamming_threshold
        images: list[ExtractedImage] = doc.images
        findings: list[Finding] = []

        # R-2026-06-19 (P0-A1/C3): classify images by size BEFORE the
        # N^2 pair loop so we can (a) skip pairs where EITHER image is
        # too small and (b) surface the skip count in stats.
        from ._image_size import summarize_image_sizes

        size_stats = summarize_image_sizes(images)
        # R-2026-06-21 (CDE-DETER): explicit sorted list (not a set)
        # so iteration order is deterministic across Python versions /
        # PYTHONHASHSEED settings.
        eligible_indexes = sorted(
            i
            for i, img in enumerate(images)
            if img.width >= 64
            and img.height >= 64
            and img.bytes_size >= 5 * 1024
        )

        # Track pairs already reported so secondary/region passes
        # do not double-count the same (i, j).
        flagged_pairs: set[tuple[int, int]] = set()
        n_primary = 0
        n_secondary = 0
        n_region = 0

        # ----- Pass 1: primary pHash -----
        # 2026-07 (negative_controls_v1): collect matches first,
        # then demote *furniture* pairs. A logo / license icon /
        # author photo repeats across MANY images in a legitimate
        # paper; a fraudulently reused figure is typically an
        # exclusive pair. Pairs whose combined match support
        # spans > 2 images are demoted to low (not dropped, so
        # recall on 3x-duplicated fraud panels still counts).
        primary_matches: list[tuple[int, int, int]] = []
        support: dict[int, set[int]] = {}
        for i in eligible_indexes:
            for j in eligible_indexes:
                if j <= i:
                    continue
                a, b = images[i], images[j]
                pa = a.phash
                pb = b.phash
                if not pa or not pb:
                    continue
                d = _hamming(pa, pb)
                if d <= threshold:
                    primary_matches.append((i, j, d))
                    support.setdefault(i, set()).add(j)
                    support.setdefault(j, set()).add(i)
        for i, j, d in primary_matches:
            a, b = images[i], images[j]
            span = {i, j} | support.get(i, set()) | support.get(j, set())
            if len(span) >= 5:
                # True furniture: a logo / icon / author photo
                # on nearly every page.
                sev = "low"
            elif len(span) > 2:
                # Small cluster: could be a 3x-duplicated fraud
                # panel -- keep visible but not high.
                sev = "medium"
            else:
                sev = _severity_for_primary(d)
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity=sev,
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
                        "image_a": {
                            "page": a.page,
                            "index": a.index,
                            "phash": a.phash,
                        },
                        "image_b": {
                            "page": b.page,
                            "index": b.index,
                            "phash": b.phash,
                        },
                        "hamming": d,
                        "algorithm": "phash",
                        "pass": "primary",
                    },
                )
            )
            flagged_pairs.add((i, j))
            n_primary += 1

        # ----- Pass 2: secondary multi-hash (aHash / dHash) -----
        secondary_pairs = [
            (i, j)
            for i in eligible_indexes
            for j in eligible_indexes
            if j > i and (i, j) not in flagged_pairs
        ]
        # Prefer pairs that already look somewhat close on pHash so we
        # do not decode every distant pair on large papers.
        def _phash_hint(pair: tuple[int, int]) -> int:
            i, j = pair
            pa, pb = images[i].phash, images[j].phash
            if pa and pb and len(pa) == len(pb):
                return _hamming(pa, pb)
            return 64

        secondary_pairs.sort(key=_phash_hint)
        secondary_pairs = secondary_pairs[:_MAX_SECONDARY_PAIRS]

        # Cache secondary hashes per image index.
        ahash_cache: dict[int, str | None] = {}
        dhash_cache: dict[int, str | None] = {}

        def _get_ahash(idx: int) -> str | None:
            if idx not in ahash_cache:
                ahash_cache[idx] = _compute_algo_hash(
                    "ahash", images[idx].image_path
                )
            return ahash_cache[idx]

        def _get_dhash(idx: int) -> str | None:
            if idx not in dhash_cache:
                dhash_cache[idx] = _compute_algo_hash(
                    "dhash", images[idx].image_path
                )
            return dhash_cache[idx]

        for i, j in secondary_pairs:
            a, b = images[i], images[j]
            best_algo: str | None = None
            best_d = 64
            for algo, getter in (
                ("ahash", _get_ahash),
                ("dhash", _get_dhash),
            ):
                ha = getter(i)
                hb = getter(j)
                if not ha or not hb:
                    continue
                d = _hamming(ha, hb)
                if d < best_d:
                    best_d = d
                    best_algo = algo
            if best_algo is None or best_d > _SECONDARY_HAMMING:
                continue
            sev = "high" if best_d <= _HIGH_SEVERITY_HAMMING else "medium"
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity=sev,
                    title=(
                        f"Near-duplicate image detected "
                        f"({best_algo} secondary)"
                    ),
                    evidence=(
                        f"Image p{i} (page {a.page + 1}) and p{j} "
                        f"(page {b.page + 1}) share {best_algo} distance "
                        f"{best_d} (≤{_SECONDARY_HAMMING} secondary band)."
                    ),
                    location=(
                        f"Page {a.page + 1} / image {a.index}  ↔  "
                        f"Page {b.page + 1} / image {b.index}"
                    ),
                    raw={
                        "image_a": {
                            "page": a.page,
                            "index": a.index,
                            "phash": a.phash,
                        },
                        "image_b": {
                            "page": b.page,
                            "index": b.index,
                            "phash": b.phash,
                        },
                        "hamming": best_d,
                        "algorithm": best_algo,
                        "pass": "secondary",
                    },
                )
            )
            flagged_pairs.add((i, j))
            n_secondary += 1

        # ----- Pass 3: region / tile bridge -----
        # Only compare images that still have no whole-image hit.
        region_indexes = [
            i
            for i in eligible_indexes
            if images[i].image_path
        ]
        cell_cache: dict[int, list[tuple[int, int, str, float]]] = {}

        def _cells(idx: int) -> list[tuple[int, int, str, float]]:
            if idx not in cell_cache:
                cell_cache[idx] = _region_cell_hashes(images[idx].image_path)
            return cell_cache[idx]

        for pos_a, i in enumerate(region_indexes):
            if n_region >= _REGION_MAX_FINDINGS:
                break
            cells_a = _cells(i)
            if not cells_a:
                continue
            for j in region_indexes[pos_a + 1 :]:
                if n_region >= _REGION_MAX_FINDINGS:
                    break
                if (i, j) in flagged_pairs:
                    continue
                cells_b = _cells(j)
                if not cells_b:
                    continue
                match = _best_region_match(cells_a, cells_b)
                if match is None:
                    continue
                (ra, ca, rb, cb, d, std_a, std_b) = match
                a, b = images[i], images[j]
                findings.append(
                    Finding.make(
                        trace_id=doc.trace_id,
                        detector=self.name,
                        severity="medium",
                        title=(
                            "Local region reuse across images "
                            "(tile bridge)"
                        ),
                        evidence=(
                            f"Image p{i} (page {a.page + 1}) cell "
                            f"({ra},{ca}) and p{j} (page {b.page + 1}) "
                            f"cell ({rb},{cb}) share tile aHash distance "
                            f"{d} (≤{_REGION_HAMMING}). Consistent with "
                            f"reused panel/gel/texture fragments that "
                            f"whole-image pHash misses."
                        ),
                        location=(
                            f"Page {a.page + 1} / image {a.index} "
                            f"cell ({ra},{ca})  ↔  "
                            f"Page {b.page + 1} / image {b.index} "
                            f"cell ({rb},{cb})"
                        ),
                        raw={
                            "image_a": {
                                "page": a.page,
                                "index": a.index,
                                "cell": [ra, ca],
                            },
                            "image_b": {
                                "page": b.page,
                                "index": b.index,
                                "cell": [rb, cb],
                            },
                            "hamming": d,
                            "std_a": std_a,
                            "std_b": std_b,
                            "algorithm": "tile_ahash",
                            "pass": "region",
                            "grid": _REGION_GRID,
                        },
                    )
                )
                flagged_pairs.add((i, j))
                n_region += 1

        stats: dict[str, Any] = size_stats.to_stats_dict()
        stats.update(
            {
                "n_primary_hits": n_primary,
                "n_secondary_hits": n_secondary,
                "n_region_hits": n_region,
                "primary_threshold": threshold,
                "secondary_threshold": _SECONDARY_HAMMING,
            }
        )
        return DetectorResult(
            detector=self.name,
            ok=True,
            findings=findings,
            stats=stats,
        )


def _best_region_match(
    cells_a: list[tuple[int, int, str, float]],
    cells_b: list[tuple[int, int, str, float]],
) -> tuple[int, int, int, int, int, float, float] | None:
    """Return best (ra, ca, rb, cb, d, std_a, std_b) under Hamming gate."""
    best: tuple[int, int, int, int, int, float, float] | None = None
    best_d = _REGION_HAMMING + 1
    for ra, ca, ha, std_a in cells_a:
        for rb, cb, hb, std_b in cells_b:
            if len(ha) != len(hb):
                continue
            d = _hamming(ha, hb)
            if d > _REGION_HAMMING:
                continue
            if d < best_d:
                best_d = d
                best = (ra, ca, rb, cb, d, std_a, std_b)
                if d == 0:
                    return best
    return best
