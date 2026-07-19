# Detector layers — pipeline vs registry vs agent

> 2026-07 redundancy pass (P0/P1). Single source of truth for **where** a
> detector runs and **which** module owns a capability.

## Three surfaces

| Surface | What runs | Entry |
|---------|-----------|--------|
| **Offline pipeline** | `_BUILTIN_DETECTOR_CLASS_NAMES` in `manusift/pipeline.py` | `run_pipeline` / `manusift screen` / MCP `submit_screen` |
| **Registry (all)** | `_DETECTOR_SPECS` in `manusift/detectors/__init__.py` | Agent tools, MCP fine-grained detectors |
| **Intentionally offline-excluded** | `PIPELINE_EXCLUDED` in `pipeline.py` | Still registered; **not** in batch screen (avoids double-count / cost) |

Rule (enforced by `tests/test_pipeline_detector_coverage.py`): every registry
class is either in the pipeline list **or** documented in `PIPELINE_EXCLUDED`.

## Capability owners (prefer one primary)

| Capability | **Primary (use this)** | Secondary / agent-only / nested |
|------------|------------------------|----------------------------------|
| Whole-image near-duplicate | **`image_dup`** (pHash + aHash/dHash + geo + region + loading-control) | `imagehash_*` (P/A/D/WHash single-algo probes) — **agent-only**, do not re-implement |
| Within-image copy-move | **`image_forensics`** (SIFT primary + grid secondary) | `image_sift_copymove` standalone also in pipeline (shared core) |
| Cross-image local match | **`image_forensics`** cross-SIFT | — |
| Multi-panel split + within-figure panel reuse | **`panel_duplicate`** (`PanelSegmentationDetector`) | — |
| Cross-page panel hash (whitespace split of figure regions) | **`panel_dup`** | Different algo/scope than `panel_duplicate` — see below |
| Page furniture / raster tiles | **`page_raster_dup`** | — |
| Table Excel-style fingerprints | **`table_relationships`** + discrete table_* detectors in pipeline | **`table_forensics`** — orchestrator that **re-runs** the same suite; **pipeline-excluded** to avoid double-report |
| PDF tables ↔ SI xlsx | **`source_data_consistency`** | — |
| SSIM whole-image | (none in pipeline) | `image_ssim` agent-only |
| Heavy OCR tables | (off by default) | `figure_table_ocr` — env-gated |

## `panel_dup` vs `panel_duplicate` (do not merge casually)

| | `panel_dup` | `panel_duplicate` (`PanelSegmentationDetector`) |
|--|-------------|--------------------------------------------------|
| **Scope** | Across pages / figure regions from page raster path | Within one multi-panel figure image |
| **Split** | Whitespace-gap recursion on figure regions | Otsu / layout segmentation into panels |
| **Compare** | Panel pHash across splits | Panel SSIM + pHash within figure |
| **Typical fraud** | Same panel reused in Fig 1 vs Fig 3 | Fig 2a and Fig 2c are the same blot |
| **Gold / tools name** | `panel_dup` | `panel_duplicate` |

Both can fire on the same paper; findings use different detector names so
calibration and aggregation stay distinct.

## `image_dup` vs `imagehash_*`

- **`image_dup`**: production multi-pass path; thresholds tuned on
  fraud / negative_controls benchmarks.
- **`imagehash_ahash` / `dhash` / `phash` / `whash`**: thin, single-algorithm
  pair scanners for **agent inspection**. Pipeline excludes them because
  `image_dup` already covers multi-hash.

Do **not** add new whole-image hash logic to `imagehash_dup.py` — extend
`image_dup.py` instead.

## `table_forensics` vs pipeline table suite

`TableForensicsDetector` loops Benford, duplicate rows, relationships, etc.
and emits a summary risk score. Useful as a **single agent tool**. Running it
inside the offline pipeline would duplicate every component finding.

## Agent runtime note

- Prefer `manusift.agent.create_agent_loop()` → **Pydantic** loop.
- `legacy_loop.AgentLoop` is frozen maintenance (tests / fallback only).

## Chat TUI

Conversational `chat_app` was **removed**. `ChatMessage` in `contracts.py`
is a shared transcript DTO only (workspace TUI / logs), not a chat app.


## P2 / P3 redundancy outcomes (2026-07)

### Safe-read (P2)

Open-source pattern: **single public facade + implementation dual-support**
(Python/Django style: keep old import path importable; re-export from the
canonical module).

- **Canonical:** `manusift.tools.safe_read` (Phase A + re-exports Phase B)
- **Implementation:** `safe_read_b` (xlsx/docx extract, tracker, redact)
- Direct `import safe_read_b` → `DeprecationWarning` (except via facade / pytest)

### Report path (P2)

Open-source pattern: **document primary pipeline; mark secondary formats**.

See `docs/REPORT_PATH.md`. Primary offline: `investigation_pairs`.

### Agent loop (P3)

Open-source pattern: **one maintained runtime + explicit legacy flag**
(PydanticAI default; dual-support without dual maintenance).

- Factory: `create_agent_loop()` → `PydanticAgentLoop`
- `legacy_loop.AgentLoop`: frozen; DeprecationWarning on construct

### SIFT / copy-move (P3)

| Entry | Role |
|-------|------|
| `image_forensics` | **Primary owner** for in-pipeline forensics suite (calls sift_copymove helpers for within-image CMFD + cross-image match + gel seam, etc.) |
| `image_sift_copymove` (`SiftCopyMoveDetector`) | **Shared core** standalone detector also registered in the offline pipeline for focused SIFT CMFD findings; same algorithms as forensics primary path, separate finding stream |
| Do not remove either from pipeline without a double-count audit on golds |

Finding names differ (`image_forensics` kinds vs `image_sift_copymove`), so calibration can treat them separately.
