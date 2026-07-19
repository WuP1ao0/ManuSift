"""P6.1: vertical gel/blot splice seam heuristic."""
from __future__ import annotations

from pathlib import Path

from manusift.contracts import ExtractedImage
from manusift.detectors.image_forensics import _vertical_gel_seam_check


def test_vertical_seam_on_spliced_blot(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw
    import random

    # Hard vertical join at mid-width with different noise fields.
    rng = random.Random(0)
    img = Image.new("L", (200, 120))
    pix = img.load()
    for y in range(120):
        for x in range(200):
            if x < 100:
                pix[x, y] = max(0, min(255, 70 + rng.randint(-25, 25)))
            else:
                pix[x, y] = max(0, min(255, 190 + rng.randint(-20, 20)))
    d = ImageDraw.Draw(img)
    d.rectangle([15, 40, 85, 55], fill=15)
    d.rectangle([120, 60, 185, 80], fill=25)
    path = tmp_path / "splice.png"
    img.save(path)

    ei = ExtractedImage(
        page=0,
        index=0,
        xref=1,
        width=200,
        height=100,
        bytes_size=path.stat().st_size,
        image_path=str(path),
        phash=None,
    )
    hit = _vertical_gel_seam_check(ei)
    assert hit is not None
    sev, title, _ev, _loc, raw = hit
    assert sev in ("high", "medium", "low")
    assert raw.get("kind") == "vertical_gel_seam"
    assert 0.15 < float(raw["seam_x_fraction"]) < 0.85


def test_smooth_gradient_not_seam(tmp_path: Path) -> None:
    from PIL import Image

    img = Image.new("L", (200, 100))
    pix = img.load()
    for x in range(200):
        v = int(50 + 150 * (x / 199.0))
        for y in range(100):
            pix[x, y] = v
    path = tmp_path / "grad.png"
    img.save(path)
    ei = ExtractedImage(
        page=0,
        index=0,
        xref=1,
        width=200,
        height=100,
        bytes_size=path.stat().st_size,
        image_path=str(path),
        phash=None,
    )
    assert _vertical_gel_seam_check(ei) is None
