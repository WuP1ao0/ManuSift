"""Generate the small PDF fixtures used by the eval suite.

This script is *idempotent*: running it twice produces byte-identical
files, so the eval results stay stable. We pin numpy's RNG seed
where randomness is needed.

Run from project root:

    ./.venv/Scripts/python.exe -m evals.build_fixtures
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz
import numpy as np
from PIL import Image


# Deterministic low-entropy noise so JPEG artefacts are stable.
def _noise(h: int, w: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return Image.fromarray(arr)


def _to_jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _new_doc() -> fitz.Document:
    return fitz.open()


def _save(doc: fitz.Document, path: Path) -> None:
    doc.set_metadata(
        {
            "title": "fixture",
            "author": "manusift-fixtures",
            "producer": "Skia/PDF m117",
        }
    )
    doc.save(str(path))
    doc.close()


# ---------- 1. clean_academic ----------

_CLEAN_BODY = (
    "We present a novel framework for cross-lingual document retrieval "
    "evaluated on standard benchmarks. Our approach achieves state-of-the-art "
    "results while using fewer parameters than prior work. We further provide "
    "a detailed analysis of failure modes and discuss implications for future "
    "research. The proposed method transfers to low-resource settings without "
    "architectural changes, and we report ablations in the appendix. The "
    "results suggest that parameter sharing across languages serves as a "
    "strong inductive bias for retrieval tasks. Code and data will be "
    "released upon publication."
)


def build_clean_academic(out: Path) -> None:
    doc = _new_doc()
    page = doc.new_page(width=400, height=600)
    page.insert_text((40, 40), "1. Introduction")
    page.insert_textbox(fitz.Rect(40, 70, 360, 580), _CLEAN_BODY, fontsize=11)
    _save(doc, out)


# ---------- 2. duplicate_image ----------

def build_duplicate_image(out: Path) -> None:
    """The same 32x32 blue square embedded twice on a page."""
    img = Image.new("RGB", (32, 32), color=(30, 90, 200))
    png = _to_png_bytes(img)
    doc = _new_doc()
    page = doc.new_page(width=400, height=400)
    page.insert_text((40, 40), "Figure appears twice below:")
    page.insert_image(fitz.Rect(40, 60, 200, 220), stream=png)
    page.insert_image(fitz.Rect(40, 240, 200, 400), stream=png)
    _save(doc, out)


# ---------- 3. composite_image ----------

def build_composite_image(out: Path) -> None:
    """High-quality base + low-quality patch — ELA should fire."""
    base = Image.new("RGB", (256, 256), color=(220, 220, 220))
    grad = np.tile(np.linspace(60, 200, 128, dtype=np.uint8), (256, 1))
    arr = np.array(base)
    arr[:, :128, 0] = grad
    arr[:, :128, 1] = grad
    arr[:, :128, 2] = 255 - grad
    base = Image.fromarray(arr)
    base_jpg = _to_jpeg_bytes(base, quality=95)
    patch = _noise(128, 128, seed=42)
    patch_jpg = _to_jpeg_bytes(patch, quality=40)
    composite = Image.open(io.BytesIO(base_jpg)).convert("RGB")
    with Image.open(io.BytesIO(patch_jpg)).convert("RGB") as p:
        composite.paste(p, (0, 0))
    out_jpg = _to_jpeg_bytes(composite, quality=90)
    doc = _new_doc()
    page = doc.new_page(width=400, height=400)
    page.insert_text((40, 40), "Figure: composite test image")
    page.insert_image(fitz.Rect(40, 60, 296, 316), stream=out_jpg)
    _save(doc, out)


# ---------- 4. chatbot_text ----------

_CHATBOT_BODY = (
    "As an AI language model I cannot provide a definitive answer to this "
    "question, but the following discussion is offered as background. "
    "Certainly! The proposed method achieves state-of-the-art results on "
    "the standard benchmark. Smith et al. showed similar trends in prior "
    "work, though their evaluation differs from ours in several respects."
)


def build_chatbot_text(out: Path) -> None:
    doc = _new_doc()
    page = doc.new_page(width=400, height=600)
    page.insert_text((40, 40), "Methods")
    page.insert_textbox(fitz.Rect(40, 70, 360, 580), _CHATBOT_BODY, fontsize=11)
    _save(doc, out)


# ---------- 5. duplicate_paragraph ----------

_DUP_SENTENCE = (
    "Our model achieves a 4.2 point improvement in mean reciprocal rank over "
    "the strongest baseline while using approximately 30% fewer parameters "
    "and converging in half the training time. "
)


def build_duplicate_paragraph(out: Path) -> None:
    doc = _new_doc()
    page = doc.new_page(width=400, height=600)
    page.insert_text((40, 40), "Results")
    page.insert_textbox(
        fitz.Rect(40, 70, 360, 580),
        _DUP_SENTENCE * 3,
        fontsize=11,
    )
    _save(doc, out)


# ---------- runner ----------

BUILDERS = {
    "clean_academic.pdf": build_clean_academic,
    "duplicate_image.pdf": build_duplicate_image,
    "composite_image.pdf": build_composite_image,
    "chatbot_text.pdf": build_chatbot_text,
    "duplicate_paragraph.pdf": build_duplicate_paragraph,
}


def main() -> None:
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    for name, fn in BUILDERS.items():
        out = fixtures_dir / name
        fn(out)
        print(f"wrote {out}  ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
