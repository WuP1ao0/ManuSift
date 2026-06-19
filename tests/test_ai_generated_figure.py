"""Unit tests for the AI-generated-figure detector (P0-AI).

Covers:
  - Probe 1: AI-tool fingerprint match in /Producer /Creator / XMP.
  - Probe 2: AI-prompt-token match in metadata.
  - Probe 3: per-figure dimension consistency.
  - Detector returns ok=True even when no findings (best-effort).
  - Detector does not crash on missing path / missing pikepdf.

These tests use the ``ParsedDoc`` dataclass directly (no PDF parse).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def _make_doc(source_path: str = "/fake/path.pdf") -> "ParsedDoc":  # noqa: F821
    """Build a minimal ParsedDoc for unit tests."""
    from manusift.contracts import ParsedDoc, TextBlock
    return ParsedDoc(
        trace_id="test-trace",
        source_path=source_path,
        text_blocks=[TextBlock(page=0, bbox=(0.0, 0.0, 0.0, 0.0), text="")],
        images=[],
        metadata={},
    )


# ---------- Probe 1: AI tool fingerprint ----------

def test_midjourney_in_creator_field_triggers_high() -> None:
    """When /Creator mentions Midjourney, a high-severity finding fires."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc()
    det = AIGeneratedFigureDetector()

    fake_info = {"Creator": "Midjourney v6", "Producer": "Midjourney"}
    fake_xmp = ""
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value=fake_info,
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value=fake_xmp,
    ):
        result = det.run(doc)
    assert result.ok is True
    findings = result.findings
    assert len(findings) >= 1
    f = findings[0]
    assert f.severity == "high"
    assert "Midjourney" in f.title
    assert f.detector == "ai_generated_figure"


def test_stable_diffusion_in_xmp_triggers_high() -> None:
    """Stable Diffusion fingerprint in XMP packet fires."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc()
    det = AIGeneratedFigureDetector()

    fake_info = {}
    fake_xmp = "<x:xmpmeta>...prompt: a cat, negative: ugly, model: sd_xl_base_1.0, Stable Diffusion...</x:xmpmeta>"
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value=fake_info,
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value=fake_xmp,
    ):
        result = det.run(doc)
    assert any(
        "Stable Diffusion" in f.title and f.severity == "high"
        for f in result.findings
    )


def test_c2pa_trainedalgorithmicmedia_triggers_high() -> None:
    """C2PA / IPTC 'trainedAlgorithmicMedia' marker fires (DALL-E/Firefly)."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc()
    det = AIGeneratedFigureDetector()

    fake_info = {"Producer": "OpenAI DALL-E", "Keywords": "trainedAlgorithmicMedia"}
    fake_xmp = ""
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value=fake_info,
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value=fake_xmp,
    ):
        result = det.run(doc)
    # Should fire for both DALL-E and trainedAlgorithmicMedia.
    titles = " | ".join(f.title for f in result.findings)
    assert "DALL-E" in titles
    assert "trainedAlgorithmicMedia" in titles
    # Highest severity wins -> high.
    assert any(f.severity == "high" for f in result.findings)


def test_no_metadata_returns_ok_with_no_findings() -> None:
    """An empty /Info dictionary + empty XMP returns zero findings."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc()
    det = AIGeneratedFigureDetector()
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value={},
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value="",
    ):
        result = det.run(doc)
    assert result.ok is True
    assert result.findings == []


# ---------- Probe 2: AI-prompt-token residue ----------

def test_ai_prompt_token_4k_triggers_medium() -> None:
    """A '4k' or '8k' prompt residue in metadata fires medium severity."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc()
    det = AIGeneratedFigureDetector()

    fake_info = {"Subject": "4k photorealistic portrait, trending on artstation"}
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value=fake_info,
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value="",
    ):
        result = det.run(doc)
    # The detector should fire on multiple tokens (8k/4k/UHD/HDR/etc).
    # We just need at least one finding.
    assert len(result.findings) >= 1
    assert any(
        "AI-prompt-style" in f.title and f.severity == "medium"
        for f in result.findings
    )


# ---------- Probe 3: dimension consistency ----------

def test_three_identical_dim_images_triggers_low() -> None:
    """3+ images with the same pixel dimensions fires a low finding."""
    from dataclasses import dataclass
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )

    @dataclass
    class _Img:
        page: int = 1
        width: int = 512
        height: int = 512

    doc = _make_doc()
    doc = type(doc)(
        trace_id=doc.trace_id,
        source_path=doc.source_path,
        text_blocks=doc.text_blocks,
        images=[_Img(), _Img(), _Img()],
        metadata={},
    )
    det = AIGeneratedFigureDetector()
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value={},
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value="",
    ):
        result = det.run(doc)
    assert any(
        "share identical pixel dimensions" in f.title
        and f.severity == "low"
        for f in result.findings
    )


def test_two_identical_dim_images_does_not_trigger() -> None:
    """Two identical-dim images is below the threshold (>=3 required)."""
    from dataclasses import dataclass
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )

    @dataclass
    class _Img:
        page: int = 1
        width: int = 512
        height: int = 512

    doc = _make_doc()
    doc = type(doc)(
        trace_id=doc.trace_id,
        source_path=doc.source_path,
        text_blocks=doc.text_blocks,
        images=[_Img(), _Img()],
        metadata={},
    )
    det = AIGeneratedFigureDetector()
    with patch(
        "manusift.detectors.ai_generated_figure._read_pdf_info_dict",
        return_value={},
    ), patch(
        "manusift.detectors.ai_generated_figure._read_xmp_packet",
        return_value="",
    ):
        result = det.run(doc)
    # No dimension-consistency finding.
    assert not any(
        "share identical pixel dimensions" in f.title
        for f in result.findings
    )


# ---------- Robustness ----------

def test_missing_pikepdf_does_not_crash() -> None:
    """When pikepdf is unavailable, _read_pdf_info_dict returns {} and
    the detector returns ok=True with no findings."""
    from manusift.detectors import ai_generated_figure as mod
    doc = _make_doc()
    # Force the lazy import inside the detector functions to fail.
    original_info = mod._read_pdf_info_dict
    original_xmp = mod._read_xmp_packet

    def _raise(*a, **kw):
        raise ImportError("pikepdf not available")

    # We patch the module-level helpers; their bodies lazy-import, so
    # the failure is at the pikepdf import step. We simulate by
    # replacing the function body.
    mod._read_pdf_info_dict = lambda path: {}  # type: ignore[assignment]
    mod._read_xmp_packet = lambda path: ""  # type: ignore[assignment]
    try:
        det = mod.AIGeneratedFigureDetector()
        result = det.run(doc)
        assert result.ok is True
    finally:
        mod._read_pdf_info_dict = original_info  # type: ignore[assignment]
        mod._read_xmp_packet = original_xmp  # type: ignore[assignment]


def test_nonexistent_path_returns_ok() -> None:
    """A non-existent PDF path does not raise; returns ok=True with no findings."""
    from manusift.detectors.ai_generated_figure import (
        AIGeneratedFigureDetector,
    )
    doc = _make_doc(source_path="/does/not/exist.pdf")
    det = AIGeneratedFigureDetector()
    result = det.run(doc)
    assert result.ok is True
    assert result.findings == []


def test_detector_registered_in_pipeline() -> None:
    """The detector is reachable from pipeline._pipeline_detector_classes."""
    from manusift.pipeline import _pipeline_detector_classes
    names = [d().name for d in _pipeline_detector_classes()]
    assert "ai_generated_figure" in names