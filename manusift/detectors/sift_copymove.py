"""Copy-move forgery detector using SIFT keypoint matching (T8).

The previous detectors
(``image_dup`` and the four
``imagehash_*`` detectors)
catch the case where the *same*
image appears twice in the
PDF -- a "duplicate figure"
attack. Copy-move forgery is
a more subtle attack: the
forger copies a *region* of an
image, pastes it elsewhere in
the *same* image, and covers
the original region with new
content. The result is one
"natural-looking" image that
contains a hidden splice.

The standard SIFT-based
algorithm:

  1. Detect SIFT keypoints in
     the image.
  2. For each keypoint, compute
     a 128-dimensional SIFT
     descriptor.
  3. Match every keypoint to
     its nearest neighbor in
     the same image (left-right
     self-match) using a
     kd-tree (FLANN).
  4. Discard matches whose
     nearest-neighbor distance
     ratio (Lowe's ratio) is
     above 0.8 -- the standard
     SIFT filter for "this match
     is not unique enough to
     trust".
  5. For the remaining matches,
     keep only those whose two
     keypoints are spatially
     separated by more than a
     minimum pixel distance
     (typically 32 px). Matches
     that are too close to each
     other are trivially the
     same region and not
     interesting.
  6. Cluster the surviving
     matches by translation
     vector. A copy-move attack
     produces many matches with
     a similar translation
     vector (the offset between
     the source patch and the
     pasted patch); a natural
     image produces matches
     with a *random* spread of
     translation vectors.
  7. If any cluster has more
     than 8 matches (a typical
     threshold from the
     literature), report a
     copy-move finding.

The detector works on a single
image at a time; the pipeline
runs it on every image in
``doc.images``. The output is
a list of findings, one per
suspicious image. Severity is
"high" for >= 20 matches in
the largest cluster, "medium"
for 8-19.

The implementation uses
``opencv-python-headless`` so
it works in environments
without a display. We do not
require a GPU; SIFT runs in
well under a second per
typical paper figure.

Borrowed from the algorithm
in the CMFDL paper (Springer
2023) and the open-source
``image-copy-move-detection``
repo on GitHub.
"""
from __future__ import annotations

import json
from importlib.util import find_spec
from typing import Any

from PIL import Image

_HAS_NUMPY = find_spec("numpy") is not None
_HAS_CV2 = find_spec("cv2") is not None

from ..contracts import Finding, ParsedDoc
from .base import DetectorResult


# Tunable constants. These are
# the values most often cited
# in the literature; we expose
# them as module-level
# constants so a future
# revision can drive them from
# settings without rewriting
# the detector.
LOWE_RATIO: float = 0.8
MIN_PIXEL_DISTANCE: int = 32
MIN_CLUSTER_SIZE: int = 8
HIGH_SEVERITY_THRESHOLD: int = 20


def _load_numpy() -> Any | None:
    if not _HAS_NUMPY:
        return None
    import numpy as np

    return np


def _load_cv2() -> Any | None:
    if not _HAS_CV2:
        return None
    import cv2  # type: ignore

    return cv2


def _read_image(path: str) -> Any | None:
    """Read an image as a BGR
    numpy array. Returns None
    if the file cannot be
    opened. We use OpenCV here
    instead of PIL because the
    SIFT detector is in
    ``cv2`` and we want to avoid
    the round-trip."""
    cv2 = _load_cv2()
    np = _load_numpy()
    if cv2 is None or np is None:
        return None
    try:
        # ``cv2.imread`` returns
        # ``None`` on failure;
        # we rely on that
        # rather than a
        # try/except for speed.
        arr = cv2.imread(path)
    except Exception:  # noqa: BLE001
        return None
    if arr is None:
        # Some PIL-readable
        # formats are not
        # recognised by
        # ``cv2.imread``; fall
        # back to PIL.
        try:
            pil = Image.open(path).convert("RGB")
            arr = cv2.cvtColor(
                np.array(pil), cv2.COLOR_RGB2BGR
            )
        except Exception:  # noqa: BLE001
            return None
    return arr


def _detect_sift(img_bgr: Any) -> tuple[Any, Any] | None:
    """Detect SIFT keypoints and
    descriptors. We use
    ``cv2.SIFT_create`` which
    is the OpenCV 4.5+ SIFT
    implementation (no
    xfeatures2d dependency).
    Returns None if the
    detector cannot initialise
    (some OpenCV builds ship
    without SIFT; we surface
    that as a silent skip
    rather than a crash)."""
    cv2 = _load_cv2()
    if cv2 is None:
        return None
    try:
        sift = cv2.SIFT_create()
    except Exception:  # noqa: BLE001
        return None
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    kp, des = sift.detectAndCompute(gray, None)
    if des is None or len(kp) < 2:
        return None
    return kp, des


def _match_self(
    descriptors: Any,
) -> list[tuple[int, int, float]]:
    """Self-match every keypoint
    against the same set. We
    use a kd-tree (FLANN) for
    fast approximate nearest
    neighbor search; the
    alternative is a brute-
    force BFMatcher which is
    O(N^2) and slow on a 1000-
    keypoint image.

    Returns a list of
    ``(i, j, distance)`` tuples
    sorted by ascending
    distance. The i==j matches
    (self-matches) are dropped
    -- they are not informative.
    """
    if len(descriptors) < 2:
        return []
    cv2 = _load_cv2()
    if cv2 is None:
        return []
    # FLANN parameters for
    # SIFT: 4 kd-trees, 64
    # checks per leaf.
    flann = cv2.FlannBasedMatcher(
        dict(algorithm=1, trees=4), dict(checks=64)
    )
    # ``knnMatch`` with k=2
    # returns the two nearest
    # neighbors for every
    # query; we use that for
    # Lowe's ratio test.
    try:
        pairs = flann.knnMatch(descriptors, descriptors, k=2)
    except cv2.error:
        return []
    out: list[tuple[int, int, float]] = []
    for m, n in pairs:
        # Self-matches (where
        # the nearest neighbor
        # is the query itself)
        # have a distance very
        # close to zero; we
        # drop them.
        if m.queryIdx == m.trainIdx:
            continue
        if m.distance >= n.distance * LOWE_RATIO:
            continue
        out.append(
            (m.queryIdx, m.trainIdx, m.distance)
        )
    out.sort(key=lambda x: x[2])
    return out


def _cluster_by_translation(
    keypoints: Any,
    matches: list[tuple[int, int, float]],
    img_w: int,
    img_h: int,
) -> int:
    """Group matches by their
    translation vector (the
    x, y offset between the two
    keypoints) and return the
    size of the largest
    cluster. Matches with the
    same offset (within
    ``MIN_PIXEL_DISTANCE``)
    are bucketed together; a
    large bucket is the
    signature of a copy-move
    attack.

    We use a simple O(M^2)
    greedy clustering. For a
    typical paper figure with
    200-1000 keypoints, M (the
    number of surviving matches
    after the Lowe filter) is
    in the 10-200 range, so the
    O(M^2) cost is fine.
    """
    if not matches:
        return 0
    # First, drop matches whose
    # spatial offset is below
    # the minimum pixel
    # distance.
    useful: list[tuple[float, float]] = []
    for i, j, _ in matches:
        p1 = keypoints[i].pt
        p2 = keypoints[j].pt
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        if (dx * dx + dy * dy) ** 0.5 < MIN_PIXEL_DISTANCE:
            continue
        useful.append((dx, dy))
    if not useful:
        return 0
    # Greedy clustering: pick
    # the first unassigned
    # match as a centroid,
    # then every other match
    # within ``MIN_PIXEL_DISTANCE``
    # of the centroid is in
    # the same cluster.
    assigned = [False] * len(useful)
    biggest = 0
    for c_idx, (cx, cy) in enumerate(useful):
        if assigned[c_idx]:
            continue
        size = 0
        for j_idx in range(c_idx, len(useful)):
            if assigned[j_idx]:
                continue
            jx, jy = useful[j_idx]
            if (
                (jx - cx) ** 2 + (jy - cy) ** 2
            ) ** 0.5 < MIN_PIXEL_DISTANCE:
                assigned[j_idx] = True
                size += 1
        if size > biggest:
            biggest = size
        # Image-size guard: a
        # cluster of 1 is not
        # interesting.
        if biggest >= MIN_CLUSTER_SIZE:
            # We can stop early.
            return biggest
    return biggest


class SiftCopyMoveDetector:
    """Run the SIFT-based copy-
    move detection on every
    image in the document. One
    finding per image whose
    largest translation
    cluster exceeds
    ``MIN_CLUSTER_SIZE``."""

    name = "image_sift_copymove"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        if not (_HAS_CV2 and _HAS_NUMPY):
            return DetectorResult(
                detector=self.name,
                findings=[],
                ok=True,
            )
        findings: list[Finding] = []
        # R-2026-06-19 (P0-A1/C3):
        # classify images by
        # size so the report
        # renderer can show
        # "N images too small
        # for image_sift_copymove
        # analysis" instead of
        # silent "no finding".
        from ._image_size import summarize_image_sizes
        size_stats = summarize_image_sizes(doc.images)
        for i, img in enumerate(doc.images):
            path = img.image_path
            if not path:
                continue
            arr = _read_image(path)
            if arr is None:
                continue
            h, w = arr.shape[:2]
            # Skip tiny images --
            # there is no useful
            # signal in a 16x16
            # thumbnail.
            # R-2026-06-19 (P0-A1/C3):
            # the size check is
            # duplicated here so
            # the per-image loop
            # stays fast (no
            # extra dict lookup)
            # but the stats dict
            # above already
            # counted the skipped
            # ones for the report.
            if h < 64 or w < 64:
                continue
            if img.bytes_size < 5 * 1024:
                continue
            detected = _detect_sift(arr)
            if detected is None:
                continue
            keypoints, descriptors = detected
            if len(keypoints) < MIN_CLUSTER_SIZE * 2:
                continue
            matches = _match_self(descriptors)
            cluster = _cluster_by_translation(
                keypoints, matches, w, h
            )
            if cluster < MIN_CLUSTER_SIZE:
                continue
            severity = (
                "high"
                if cluster >= HIGH_SEVERITY_THRESHOLD
                else "medium"
            )
            findings.append(
                Finding.make(
                    trace_id=doc.trace_id,
                    detector=self.name,
                    severity=severity,
                    title=(
                        f"Image {i + 1} on page {img.page} "
                        f"shows copy-move forgery "
                        f"({cluster} matching keypoints)"
                    ),
                    location=(
                        f"image {i + 1} on page {img.page}"
                    ),
                    evidence=json.dumps(
                        {
                            "image_index": i,
                            "page": img.page,
                            "keypoint_count": len(keypoints),
                            "match_count": len(matches),
                            "largest_cluster": cluster,
                            "width": w,
                            "height": h,
                        }
                    ),
                )
            )
        return DetectorResult(
            detector=self.name,
            findings=findings,
            ok=True,
            stats=size_stats.to_stats_dict(),
        )
