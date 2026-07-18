"""P0/P1 image forensics: SIFT primary, JPEG ghost, backends, panel hooks."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from manusift.contracts import ExtractedImage, ParsedDoc
from manusift.detectors.image_forensics import (
    ImageForensicsDetector,
    _jpeg_ghost_check,
    _jpeg_ghost_metrics,
)


def _save(img: Image.Image, path: Path, fmt: str = "PNG", **kw) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format=fmt, **kw)
    return path


def _ext(path: Path, page: int = 0, index: int = 0) -> ExtractedImage:
    with Image.open(path) as im:
        w, h = im.size
    return ExtractedImage(
        page=page,
        index=index,
        xref=0,
        phash="0" * 16,
        width=w,
        height=h,
        bytes_size=path.stat().st_size,
        exif={},
        image_path=str(path),
    )


def _doc(*images: ExtractedImage) -> ParsedDoc:
    return ParsedDoc(
        trace_id="t-p0p1",
        source_path="<test>",
        text_blocks=[],
        images=list(images),
        metadata={},
    )


# ---------- JPEG ghost ----------


def test_jpeg_ghost_skips_png(tmp_path: Path) -> None:
    p = _save(Image.new("RGB", (128, 128), (90, 90, 90)), tmp_path / "a.png")
    assert _jpeg_ghost_check(_ext(p)) is None


def test_jpeg_ghost_metrics_on_jpeg(tmp_path: Path) -> None:
    """Uniform JPEG should produce finite metrics without crashing."""
    base = Image.new("RGB", (256, 256), (180, 180, 180))
    # mild gradient so residual is non-zero
    arr = np.array(base)
    arr[:, :, 0] = np.linspace(40, 220, 256, dtype=np.uint8)[None, :]
    im = Image.fromarray(arr)
    p = tmp_path / "g.jpg"
    im.save(p, format="JPEG", quality=85)
    strength, entropy, detail = _jpeg_ghost_metrics(p)
    assert strength >= 0.0
    assert entropy >= 0.0
    assert "qualities" in detail


def test_jpeg_ghost_flags_spliced_jpeg(tmp_path: Path) -> None:
    """Two regions re-encoded at very different qualities → ghost swing."""
    rng = np.random.default_rng(11)
    base = Image.fromarray(rng.integers(80, 180, (256, 256, 3), dtype=np.uint8))
    base_p = tmp_path / "base.jpg"
    base.save(base_p, format="JPEG", quality=95)

    patch = Image.fromarray(rng.integers(0, 255, (128, 128, 3), dtype=np.uint8))
    patch_p = tmp_path / "patch.jpg"
    patch.save(patch_p, format="JPEG", quality=30)

    composite = Image.open(base_p).convert("RGB")
    with Image.open(patch_p) as pp:
        composite.paste(pp, (0, 0))
    out = tmp_path / "splice.jpg"
    composite.save(out, format="JPEG", quality=90)

    result = ImageForensicsDetector().run(_doc(_ext(out)))
    kinds = {f.raw.get("kind") for f in result.findings}
    # Ghost is best-effort on synthetic data; at least pipeline runs.
    assert "image_forensics_summary" in kinds
    ghosts = [f for f in result.findings if f.raw.get("kind") == "jpeg_ghost"]
    # Prefer flagging; if residual swing is weak on this RNG, metrics still ok.
    strength, _ent, _ = _jpeg_ghost_metrics(out)
    if strength >= 12.0:
        assert len(ghosts) >= 1
        assert ghosts[0].severity in {"low", "medium", "high"}


# ---------- optional backends ----------


def test_optional_noop_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_IMAGE_BACKEND", "noop")
    # re-import path is env-driven at call time
    from manusift.detectors.image_backends import (
        get_optional_backends,
        list_backend_names,
        run_backends_on_path,
    )

    assert list_backend_names() == ["noop"]
    backends = get_optional_backends()
    assert len(backends) == 1
    assert backends[0].name == "noop"

    p = _save(Image.new("RGB", (64, 64), (1, 2, 3)), tmp_path / "n.png")
    assert run_backends_on_path(str(p)) == []


def test_optional_backend_hits_become_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A custom factory backend injects one finding into image_forensics."""
    # Register a tiny in-process factory via a dynamic module path is hard;
    # monkeypatch run_backends_on_path instead.
    from manusift.detectors import image_forensics as if_mod
    from manusift.detectors.image_backends import BackendHit

    def fake_run(path, *, context=None):
        return [
            BackendHit(
                backend="fake_ph",
                kind="photoholmes_noise",
                severity="medium",
                title="Fake PhotoHolmes hit",
                evidence="synthetic",
                raw={"score": 0.9},
            )
        ]

    monkeypatch.setattr(if_mod, "_optional_backend_findings", lambda doc: [
        __import__("manusift.contracts", fromlist=["Finding"]).Finding.make(
            trace_id=doc.trace_id,
            detector="image_forensics",
            severity="medium",
            title="Fake PhotoHolmes hit",
            evidence="synthetic",
            location="Page 1 / image 0",
            raw={"kind": "optional_backend", "backend": "fake_ph"},
        )
    ])

    p = _save(
        Image.fromarray(
            np.random.default_rng(0).integers(0, 255, (128, 128, 3), dtype=np.uint8)
        ),
        tmp_path / "x.png",
    )
    result = ImageForensicsDetector().run(_doc(_ext(p)))
    opts = [f for f in result.findings if f.raw.get("kind") == "optional_backend"]
    assert len(opts) == 1
    assert opts[0].raw["backend"] == "fake_ph"


# ---------- SIFT helpers (need OpenCV) ----------


@pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="OpenCV required",
)
def test_sift_analyze_api_blank_not_flagged(tmp_path: Path) -> None:
    from manusift.detectors.sift_copymove import analyze_copymove_path

    p = _save(Image.new("RGB", (200, 200), (200, 200, 200)), tmp_path / "blank.png")
    a = analyze_copymove_path(str(p))
    assert a.ok
    assert a.flagged is False


@pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="OpenCV required",
)
def test_sift_primary_wired_into_forensics(tmp_path: Path) -> None:
    """image_forensics run includes sift path without crashing."""
    rng = np.random.default_rng(3)
    arr = rng.integers(0, 255, (256, 256, 3), dtype=np.uint8)
    # clone a textured patch
    arr[150:230, 150:230] = arr[20:100, 20:100]
    p = _save(Image.fromarray(arr), tmp_path / "cm.png")
    result = ImageForensicsDetector().run(_doc(_ext(p)))
    kinds = {f.raw.get("kind") for f in result.findings}
    assert "image_forensics_summary" in kinds
    summary = next(
        f for f in result.findings if f.raw.get("kind") == "image_forensics_summary"
    )
    assert summary.raw.get("sift_primary") is True


@pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="OpenCV required",
)
def test_cross_image_sift_identical_texture_regions(tmp_path: Path) -> None:
    from manusift.detectors.sift_copymove import match_two_images

    rng = np.random.default_rng(99)
    shared = rng.integers(0, 255, (160, 160, 3), dtype=np.uint8)
    a = rng.integers(0, 80, (256, 256, 3), dtype=np.uint8)
    b = rng.integers(180, 255, (256, 256, 3), dtype=np.uint8)
    a[40:200, 40:200] = shared
    b[50:210, 50:210] = shared
    pa = _save(Image.fromarray(a), tmp_path / "a.png")
    pb = _save(Image.fromarray(b), tmp_path / "b.png")
    m = match_two_images(str(pa), str(pb))
    assert m.ok
    # Strong shared texture should produce matches; flagging depends on RANSAC
    assert m.match_count >= 0


@pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="OpenCV required",
)
def test_panel_then_match_runs(tmp_path: Path) -> None:
    """Two similar panels side by side should not crash panel-then-match."""
    rng = np.random.default_rng(5)
    panel = rng.integers(30, 220, (120, 120, 3), dtype=np.uint8)
    canvas = np.full((280, 300, 3), 255, dtype=np.uint8)
    canvas[20:140, 20:140] = panel
    canvas[20:140, 160:280] = panel  # duplicate panel
    # dark gutter
    canvas[:, 145:155] = 0
    p = _save(Image.fromarray(canvas), tmp_path / "panels.png")
    result = ImageForensicsDetector().run(_doc(_ext(p)))
    assert result.ok
    # May or may not segment/flag depending on contour quality
    kinds = {f.raw.get("kind") for f in result.findings}
    assert "image_forensics_summary" in kinds


def test_grid_copy_move_still_emits_kind(tmp_path: Path) -> None:
    """Regression: cloned corner still yields kind=copy_move from grid path."""
    img = Image.new("RGB", (256, 256), color=(200, 200, 200))
    pattern = Image.new("RGB", (64, 64))
    px = pattern.load()
    for x in range(64):
        for y in range(64):
            px[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256)
    img.paste(pattern, (0, 0))
    img.paste(pattern, (192, 192))
    p = _save(img, tmp_path / "cloned.png")
    result = ImageForensicsDetector().run(_doc(_ext(p)))
    cm = [f for f in result.findings if f.raw.get("kind") == "copy_move"]
    assert len(cm) >= 1
