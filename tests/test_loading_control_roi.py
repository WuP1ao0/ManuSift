"""P6.1 loading-control bottom-strip ROI reuse detection."""
from __future__ import annotations

from pathlib import Path

from manusift.contracts import ExtractedImage, ParsedDoc
from manusift.detectors.image_dup import (
    ImageDuplicateDetector,
    _best_loading_control_match,
    _loading_control_strip_hashes,
)


def _make_blot_pair(tmp: Path) -> tuple[Path, Path]:
    """Two blots: very different upper halves, identical bottom LC strip."""
    from PIL import Image, ImageDraw

    def base(path: Path, *, upper: str) -> None:
        img = Image.new("RGB", (240, 200), color=(250, 250, 250))
        d = ImageDraw.Draw(img)
        if upper == "a":
            # dense dark bands top-left
            for i, y in enumerate(range(10, 100, 18)):
                d.rectangle([10 + i * 5, y, 100 + i * 8, y + 10], fill=(20, 20, 20))
            d.polygon([(150, 15), (220, 40), (160, 95)], fill=(180, 40, 40))
        else:
            # sparse light structure top-right (visually different)
            d.ellipse([120, 10, 230, 100], outline=(30, 30, 180), width=8)
            d.line([20, 20, 100, 110], fill=(40, 160, 40), width=6)
            d.rectangle([30, 40, 90, 90], outline=(0, 0, 0), width=3)
        # identical loading-control strip at bottom
        d.rectangle([10, 150, 230, 190], fill=(30, 30, 30))
        for x in (25, 70, 115, 160, 200):
            d.rectangle([x, 158, x + 18, 182], fill=(8, 8, 8))
        img.save(path)

    p1 = tmp / "blot_a.png"
    p2 = tmp / "blot_b.png"
    base(p1, upper="a")
    base(p2, upper="b")
    return p1, p2


def test_strip_hashes_stable_on_shared_bottom(tmp_path: Path) -> None:
    p1, p2 = _make_blot_pair(tmp_path)
    s1 = _loading_control_strip_hashes(str(p1))
    s2 = _loading_control_strip_hashes(str(p2))
    assert s1 and s2
    hit = _best_loading_control_match(s1, s2)
    assert hit is not None
    _sa, _sb, d = hit
    assert d <= 5


def test_image_dup_flags_loading_control_roi(tmp_path: Path) -> None:
    p1, p2 = _make_blot_pair(tmp_path)
    # Force primary miss with divergent fake phashes
    images = [
        ExtractedImage(
            page=0,
            index=0,
            xref=1,
            width=240,
            height=200,
            bytes_size=30_000,
            image_path=str(p1),
            phash="0123456789abcdef",
        ),
        ExtractedImage(
            page=1,
            index=0,
            xref=2,
            width=240,
            height=200,
            bytes_size=30_000,
            image_path=str(p2),
            phash="fedcba9876543210",
        ),
    ]
    doc = ParsedDoc(
        trace_id="lc-t",
        source_path="paper.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )
    result = ImageDuplicateDetector().run(doc)
    lc = [
        f
        for f in result.findings
        if (f.raw or {}).get("pass") == "loading_control"
        or (f.raw or {}).get("check") == "loading_control_roi_dup"
    ]
    assert lc, f"expected loading-control hit, got {[f.title for f in result.findings]}"
    assert lc[0].severity in ("high", "medium")
    assert (lc[0].raw or {}).get("pubpeer_pattern") == "image_loading_control_reuse"


def test_loading_control_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MANUSIFT_LOADING_CONTROL_ROI", "0")
    p1, p2 = _make_blot_pair(tmp_path)
    images = [
        ExtractedImage(
            page=0,
            index=0,
            xref=1,
            width=240,
            height=200,
            bytes_size=30_000,
            image_path=str(p1),
            phash="0123456789abcdef",
        ),
        ExtractedImage(
            page=1,
            index=0,
            xref=2,
            width=240,
            height=200,
            bytes_size=30_000,
            image_path=str(p2),
            phash="fedcba9876543210",
        ),
    ]
    doc = ParsedDoc(
        trace_id="lc-off",
        source_path="paper.pdf",
        text_blocks=[],
        images=images,
        metadata={},
    )
    result = ImageDuplicateDetector().run(doc)
    lc = [
        f
        for f in result.findings
        if (f.raw or {}).get("check") == "loading_control_roi_dup"
    ]
    assert lc == []
