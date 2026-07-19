# ManuSift

<p align="center">
  <img src="docs/assets/manusift.png" alt="ManuSift" width="920" />
</p>

Screen scholarly **PDFs** and Source Data for research-**integrity** red flags—
image reuse, table anomalies, metadata—then write findings and HTML reports.
Runs **offline** by default (`--no-llm`; no API key). Batch CLI + **MCP** for
other agents; conversational chat is **not part of the product**.

<p align="center">
  <strong>Offline integrity screening · CLI for humans · MCP Domain Kernel for agents</strong>
</p>

<p align="center">
  <a href="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <a href="CHANGELOG.md"><img alt="Status" src="https://img.shields.io/badge/status-beta-yellow.svg"></a>
  <a href="docs/mcp/README.md"><img alt="MCP" src="https://img.shields.io/badge/MCP-Domain%20Kernel-purple.svg"></a>
</p>

Signals only—not a misconduct verdict. Humans use **batch CLI**; other agents use
**MCP**. Pin **`--workspace`** so job outputs are easy to find.

| Surface | What it is |
|---------|------------|
| **B — Batch CLI** | Strong offline `manusift screen` (primary human path) |
| **C — MCP** | Domain Kernel for Claude Desktop / Cursor / other agents |

---

## Table of contents

- [Why ManuSift](#why-manusift)
- [Quickstart](#quickstart)
- [What you get](#what-you-get)
- [Capabilities](#capabilities)
- [Product surfaces](#product-surfaces)
- [Configuration](#configuration)
- [Docs & integrity notes](#docs--integrity-notes)
- [Architecture](#architecture)
- [Development](#development)
- [Related work](#related-work)
- [License & community](#license--community)
- [Disclaimer](#disclaimer)

---

## Why ManuSift

Editors, labs, and agents need a **reproducible first pass** over PDFs and companion
spreadsheets—image reuse, Source Data copy patterns, tortured phrases, broken stats—
without wiring up a chat bot or a cloud key.

| Design choice | Meaning |
|---------------|---------|
| Offline-first | Detectors run with `--no-llm`; network only if you opt in |
| Signals, not judgments | Findings + triage *issues*; humans decide |
| B + C product | CLI for people, MCP for other agents—no chat product |
| Fixed workspace | Pin `--workspace` so reports are easy to find after the run |
| Open benchmarks | Negative controls + fraud suites under `benchmarks/` |

---

## Quickstart

**Requires:** Python **≥ 3.10** (3.11 recommended). Windows / Linux / macOS when
pip can fetch wheels for OpenCV, NumPy, SciPy (no compiler on common platforms).

A virtual environment is **recommended** (not mandatory)—any isolated env works.

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate

python -m pip install -U pip
pip install -e .

# Package data + CLI + offline screen (no API keys)
python scripts/install_smoke.py

# Screen a paper — pin --workspace so results stay where you expect
manusift screen evals/fixtures/clean_academic.pdf \
  --no-llm --suites fast --workspace ./my_jobs

# Your own PDF
manusift screen path/to/paper.pdf --no-llm --workspace ./my_jobs
```

### Where results land

| Mode | Job root | Artifacts under `…/output/` |
|------|----------|------------------------------|
| `--workspace DIR` (**recommended**) | `DIR/<trace_id>/` | `findings.json`, `report.html`, `issues.json`, `investigation_pairs.html` |
| Default (omit flag) | `data/jobs/<trace_id>/` | same filenames |

Sample PDFs ship in `evals/fixtures/` (tracked in git). If missing,
`scripts/install_smoke.py` can generate a one-page PDF with PyMuPDF.

### Optional extras

```bash
pip install -e ".[dev]"   # pytest + ruff (contributors)
pip install -e ".[ocr]"   # EasyOCR + torch (~2 GB): figure_grim / figure_table_ocr
```

LLM enrichment is **off by default**. To enable later: copy `.env.example` → `.env`,
set `MANUSIFT_ANTHROPIC_API_KEY` / `MANUSIFT_OPENAI_API_KEY` (see `manusift/config.py`).
**Never commit `.env`.**

---

## What you get

After a successful `manusift screen`:

```text
<workspace>/<trace_id>/
├── inputs/          # original PDF (+ materials when provided)
├── steps/           # per-detector checkpoints
└── output/
    ├── findings.json              # raw calibrated findings
    ├── issues.json                # aggregated review items
    ├── report.html                # HTML summary
    └── investigation_pairs.*      # primary investigation view
```

Open `investigation_pairs.html` or `report.html` in a browser. Optional LLM packaging
(`llm_report` / plain narrative) only runs when keys and concurrency allow.

---

## Capabilities

**Status (beta):** 52 registered detectors · **44** offline pipeline · **8** agent-only
(EXCLUDED from default pipeline) · **~80+** MCP tools by default (`--curated` for a
smaller set) · 6 + 6 eval cases · CI runs a reproducible subset (not the full pytest tree).

| Area | What ManuSift looks for |
|------|-------------------------|
| **Image forensics** | Multi-hash reuse (pHash/aHash/dHash), SIFT copy-move, panel + SSIM, page-raster tiles, noise/ELA, AI-figure probes |
| **Tables & statistics** | Benford (gated), row/near-dup, cross-sheet copy, round bias, outliers, GRIM/GRIMMER, DEBIT, statcheck-style *t/F/χ²/z/r* vs *p* |
| **Figure ↔ text** | Bar-chart geometry, figure–table/prose pairing, forest-plot CI/asymmetry rules |
| **Text & metadata** | Tortured phrases (~5.8k dict), paper-mill signals, PDF metadata, reference dup/format |
| **External checks** | Opt-in Crossref / OpenAlex / data-availability (cached; offline replay for CI) |
| **Triage** | Calibration + *issue* aggregation (far fewer items than raw findings); optional LLM off by default |

Benchmark snapshots (see `benchmarks/`): negative controls aim for **0.00** high-severity
findings per legit paper; fraud suites target **core recall 1.000** under the published gates.

---

## Product surfaces

### Batch CLI (B)

```bash
# Default suite is deep = full offline pipeline
manusift screen paper.pdf --with-sidecar --no-llm --workspace ./my_jobs
manusift screen paper.pdf --data-paths ./source_data --suites table --workspace ./my_jobs
manusift screen paper.pdf --no-llm --suites fast --workspace ./my_jobs   # lighter triage

manusift suites          # core | deep | fast | full | image | table
python -m manusift screen paper.pdf --no-llm --workspace ./my_jobs
```

### MCP for other agents (C)

```bash
manusift mcp --list-tools          # full registry (~80+); default
manusift mcp --curated             # smaller kernel allow-list
manusift-mcp --list-tools
python -m manusift mcp --list-tools
```

Cursor / Claude Desktop (stdio sketch):

```json
{
  "command": "manusift-mcp",
  "args": [],
  "env": { "MANUSIFT_WORKSPACE_DIR": "/path/to/jobs" }
}
```

Full client configs: [`docs/mcp/README.md`](docs/mcp/README.md).

### Optional local helpers

```bash
# Job browser on disk (not a chat agent)
manusift-workspace
# or
manusift-tui

# Local upload API + simple dashboard
python -m uvicorn manusift.web.app:app --port 8765
```

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/healthz` | Liveness |
| `GET` | `/api/health/ready` | Readiness |
| `POST` | `/api/upload` | Upload PDF (rate-limited) |
| `GET` | `/api/jobs/{trace_id}` | Status + summary |
| `GET` | `/api/jobs/{trace_id}/progress` | Detector progress |
| `GET` | `/api/jobs/{trace_id}/findings` | Findings JSON |
| `GET` | `/api/jobs/{trace_id}/report` | HTML report |

```bash
curl -F file=@paper.pdf http://127.0.0.1:8765/api/upload
curl http://127.0.0.1:8765/api/jobs/<trace_id>/findings
```

---

## Configuration

All settings use the `MANUSIFT_` prefix. Full list: `manusift/config.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MANUSIFT_WORKSPACE_DIR` | `./data/jobs` | Job root (same role as `--workspace`) |
| `MANUSIFT_DETECTOR_WORKERS` | `4` | Parallel detectors after parse (`1` = serial) |
| `MANUSIFT_MAX_UPLOAD_MB` | `50` | Upload size cap (web) |
| `MANUSIFT_OPENAI_API_KEY` | _(unset)_ | OpenAI-compatible key |
| `MANUSIFT_ANTHROPIC_API_KEY` | _(unset)_ | Anthropic key |
| `MANUSIFT_DEFAULT_LLM_PROVIDER` | `openai` | `openai` or `anthropic` |
| `MANUSIFT_LLM_MAX_CONCURRENCY` | `4` | Parallel LLM calls (`0` with `--no-llm`) |
| `MANUSIFT_LOG_LEVEL` | `INFO` | Log level |

Without API keys, screening still runs; LLM enrichment stays off / mock.

---

## Docs & integrity notes

| Doc | Topic |
|-----|--------|
| [`docs/DETECTOR_LAYERS.md`](docs/DETECTOR_LAYERS.md) | Pipeline vs agent-only vs EXCLUDED ownership |
| [`docs/REPORT_PATH.md`](docs/REPORT_PATH.md) | Primary report path (`investigation_pairs`) |
| [`docs/mcp/README.md`](docs/mcp/README.md) | MCP clients & tool surface |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Dependency / ops security notes |

**PubPeer-derived pattern maps** (screening signals only—not misconduct determinations):

- [Integrity patterns → detectors](docs/pubpeer_integrity_patterns.md)
- [Fraud methods catalogue](docs/pubpeer_100_fraud_methods.md)
- [Coverage matrix](docs/pubpeer_100_coverage_matrix.md)

---

## Architecture

```text
PDF (+ optional Source Data)
        │
        ▼
   ingest (PyMuPDF / tables / xlsx)
        │
        ▼
   pipeline detectors (44 offline; plugins via entry_points)
   ThreadPool after shared parse (MANUSIFT_DETECTOR_WORKERS)
        │
        ▼
   calibration + issue aggregation
        │
        ├── LLM enrich / adjudicate   (optional, off by default)
        └── reports + findings.json + steps/<idx>.json
```

Detectors implement a pipeline `Detector` protocol; many are also MCP `Tool`s
(`name` / `description` / `input_schema` / `execute`) via a thin adapter.

### Adding a detector

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """One-line description (also surfaces in MCP tool lists)."""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(
            detector=self.name, ok=True, findings=[], duration_ms=1
        )
```

Register in `manusift/detectors/__init__.py`, or ship a third-party plugin:

```toml
[project.entry-points."manusift.detectors"]
my_detector = "my_pkg:MyDetector"
```

---

## Development

```bash
pip install -e ".[dev]"
python scripts/install_smoke.py
python -m pytest -q tests/test_install_smoke.py
# CI public subset is listed in .github/workflows/ci.yml
# Full-tree pytest is large and may include env-gated skips/fails

manusift-evals          # core evals (LLM case skipped unless MANUSIFT_LLM_EVALS=1)
manusift-evals-e2e
```

### Benchmark gate

`scripts/ci_benchmark_gate.py` hard-fails on core recall &lt; 1.0, excess high-severity
findings on negative controls, or figure-text false positives (offline Crossref replay).

```bash
python scripts/ci_benchmark_gate.py              # full re-run (long)
python scripts/ci_benchmark_gate.py --skip-run   # check persisted artifacts
python scripts/ci_benchmark_gate.py --only fraud_web_v1
```

Workflow: [`.github/workflows/benchmark_gate.yml`](.github/workflows/benchmark_gate.yml).

**Roadmap status:** 2026-07 P1–P5 (triage, external checks, MCP surface, figure–text,
eval + CI gate) is complete. Follow-ups: cross-paper corpora, chart cross-validation,
adversarial “whitewashed” cases.

---

## Related work

ManuSift sits among tools that help *screen* integrity signals (each with a different
scope and license). Complementary examples:

| Project | Focus (rough) |
|---------|----------------|
| [ELIS](https://github.com/researchintegrity/elis) | Open image-forensics stack (PDF extract, copy-move, TruFor, …) |
| [statcheck](https://github.com/MicheleNuijten/statcheck) | NHST statistic vs *p*-value consistency (R / ecosystem) |
| [ASReview](https://github.com/asreview/asreview) | Active-learning *literature* screening (different problem; strong OSS README norms) |
| Commercial image services (e.g. ImageTwin / Proofig-class) | Cross-paper image search at scale (typically closed / SaaS) |

ManuSift’s niche: **one offline batch + MCP kernel** covering image, table/SI, text,
and metadata on a single paper (and local Source Data)—open MIT, no chat product.

---

## License & community

| | |
|--|--|
| **License** | [MIT](LICENSE) |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) · [issue / PR templates](.github/) |
| **Code of Conduct** | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| **Security** | [SECURITY.md](SECURITY.md) |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) (GitHub Releases may mirror tags) |
| **Cite** | [CITATION.cff](CITATION.cff) |

---

## Disclaimer

ManuSift is a **screening aid** for integrity *signals*. It is **not** a legal
determination of research misconduct and does **not** replace human review by
editors, institutions, or domain experts.
