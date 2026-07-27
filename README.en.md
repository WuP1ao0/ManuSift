# ManuSift

<p align="center">
  <img src="docs/assets/manusift.png" alt="ManuSift" width="920" />
</p>

<p align="center">
  <strong>Academic-integrity screening agent · Offline detection kernel · Standalone pi-SDK TUI</strong><br/>
  <a href="README.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/WuP1ao0/ManuSift/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg"></a>
  <a href="CHANGELOG.md"><img alt="Status" src="https://img.shields.io/badge/status-beta-yellow.svg"></a>
  <a href="docs/pi-agent.md"><img alt="pi agent" src="https://img.shields.io/badge/pi-agent-purple.svg"></a>
</p>

## Overview

ManuSift screens paper PDFs and companion Source Data spreadsheets for
research-integrity signals: 52 detectors covering image reuse, fabricated-table
fingerprints, statistical inconsistencies, tortured phrases, and citation
anomalies, producing evidence-anchored findings / issues / HTML reports.

Two product surfaces:

| Entry | Description |
|-------|-------------|
| **Interactive agent** | `manusift` launches a standalone TUI; conversational screening, `/screen <pdf>` triggers the full pipeline |
| **Batch CLI** | `manusift screen paper.pdf --no-llm`; fully offline, no API keys, suited to scripts and bulk runs |

Architecture: the interactive layer is a standalone agent built on the
[pi](https://github.com/earendil-works/pi) SDK (not a fork); the detection
kernel remains Python. The two connect over a JSON-lines stdio bridge
(`manusift toolserver`) exposing all **~82 domain tools** to the agent.

> ManuSift emits screening signals, not misconduct determinations.

---

## Install & run

Requires Python ≥ 3.10 (3.11 recommended); Windows / Linux / macOS.

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -e .

python scripts/install_smoke.py    # install self-check

# offline batch run (no keys)
manusift screen evals/fixtures/clean_academic.pdf --no-llm --suites fast --workspace ./my_jobs
```

### Interactive agent

Requires Node.js ≥ 20 and an LLM provider key (via pi's auth flow on first
launch, or `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`; batch mode does not need
any of this).

```bash
cd agent && npm install --ignore-scripts && cd ..   # one-time
manusift                                            # interactive TUI
manusift agent -p "screen path/to/paper.pdf"        # one-shot print mode
```

In the TUI:

- Natural-language commands: `screen C:\papers\paper.pdf`,
  `is figure 3 duplicated?`
- `/screen <pdf>`: runs the full pipeline asynchronously (progress in the
  footer), then reports the verdict in a fixed 5-section shape
- `/manusift status | restart`: bridge management
- Read-only built-in tool surface by default (no bash/edit/write);
  `--dev` lifts the restriction

### Output layout

```text
<workspace>/<trace_id>/
├── inputs/       # original PDF + companion data
├── steps/        # per-detector checkpoints
└── output/
    ├── findings.json            # calibrated findings
    ├── issues.json              # aggregated review items
    ├── report.html              # HTML summary
    └── investigation_pairs.*    # primary investigation view
```

Specify `--workspace` explicitly; the default location is
`data/jobs/<trace_id>/`.

### Optional extras

```bash
pip install -e ".[dev]"   # pytest + ruff
pip install -e ".[ocr]"   # EasyOCR + torch (~2GB): in-figure table OCR detectors
```

Batch-mode LLM enrichment: copy `.env.example` → `.env`, set
`MANUSIFT_OPENAI_API_KEY` or `MANUSIFT_ANTHROPIC_API_KEY`, and omit
`--no-llm`. Without keys the pipeline still completes; `llm_report.*` stays
empty. Reports default to Chinese; use `--lang en` for English.

---

## Detection coverage

| Area | Checks |
|------|--------|
| **Image forensics** | Multi-hash reuse (pHash/aHash/dHash), SIFT copy-move, flip/rotate matching, gel seams, panel + SSIM, page-raster tiles, noise/ELA, AI-generated-figure probes |
| **Tables & statistics** | Benford, duplicate/near-duplicate rows, cross-sheet copies, fixed offsets/ratios, decimal-tail bias, GRIM/GRIMMER, DEBIT, statcheck-style t/F/χ²/z/r vs p recomputation |
| **Figure ↔ text** | Bar-chart geometry vs reported values, forest-plot CI rules |
| **Text & metadata** | Tortured phrases (5,802-entry dictionary), paper-mill signals, PDF metadata, reference duplicates/conflicts |
| **External checks** (opt-in) | Crossref / OpenAlex retraction lookups, data-availability link resolution (cached; offline replay for CI) |
| **Triage** | Calibration + issue aggregation into high/medium/low with strict false-positive control |

Counting conventions: **52** registered detectors, **44** in the offline
pipeline (8 agent-on-demand); the agent tool surface is **~82** =
detectors-as-tools + ingest / report / job helpers. Verify with
`manusift toolserver --list-tools`.

---

## Architecture

```text
manusift  (standalone TUI, pi SDK, agent/bin/manusift-agent.mjs)
   │  custom system prompt; read-only tool surface by default (--dev opens bash/edit/write)
   ▼
.pi/extensions/manusift/          bridge extension: /screen, dedup gate, ~82 tool registrations
   ▼
python -m manusift.toolserver     JSON-lines stdio bridge
   ▼
Python detection kernel: ingest → 44 detectors in parallel → calibration/aggregation → reports
```

Batch `manusift screen` calls the kernel directly, bypassing the agent layer.

Other entry points: `manusift-workspace` (local job browser),
`python -m uvicorn manusift.web.app:app` (loopback-only local HTTP API).

### Adding a detector

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """One-line description (also used in the agent tool list)."""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(detector=self.name, ok=True, findings=[], duration_ms=1)
```

Register in `manusift/detectors/__init__.py`, or publish as a third-party
plugin via entry_points; registered detectors join the agent tool surface
automatically.

---

## Configuration

All settings use the `MANUSIFT_` prefix; full list in `manusift/config.py`.

| Variable | Default | Purpose |
|----------|---------|---------|
| `MANUSIFT_WORKSPACE_DIR` | `./data/jobs` | Job root (same as `--workspace`) |
| `MANUSIFT_DETECTOR_WORKERS` | `4` | Detector parallelism (`1` = serial) |
| `MANUSIFT_REPORT_LANGUAGE` | `zh` | Report language `zh` / `en` |
| `MANUSIFT_OPENAI_API_KEY` etc. | unset | Batch LLM enrichment (optional) |
| `MANUSIFT_PYTHON` | auto-detect `.venv` | Python interpreter for the agent bridge |
| `MANUSIFT_PI` | unset | Force plain-pi launch (skip the standalone agent) |

---

## Docs

| Doc | Topic |
|-----|-------|
| [`docs/pi-agent.md`](docs/pi-agent.md) | Agent setup, /screen, troubleshooting |
| [`docs/DETECTOR_LAYERS.md`](docs/DETECTOR_LAYERS.md) | Detector ownership (pipeline / registry / excluded) |
| [`docs/REPORT_PATH.md`](docs/REPORT_PATH.md) | Primary report path (investigation_pairs) |
| [`docs/pubpeer_100_fraud_methods.md`](docs/pubpeer_100_fraud_methods.md) | 100 PubPeer fraud patterns vs detectors |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Security notes |

---

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check manusift tests

python scripts/ci_benchmark_gate.py --skip-run   # benchmark gate (persisted artifacts)
```

Benchmarks live in `benchmarks/`: core recall on real retraction cases holds
at 1.0 with zero high-severity false positives on negative controls. Read
`docs/DETECTOR_LAYERS.md` before modifying detectors; run the gate afterwards.

---

## License & community

MIT ([LICENSE](LICENSE)) · [CONTRIBUTING](CONTRIBUTING.md) ·
[CODE_OF_CONDUCT](CODE_OF_CONDUCT.md) · [SECURITY](SECURITY.md) ·
[CHANGELOG](CHANGELOG.md) · [CITATION](CITATION.cff)

## Disclaimer

ManuSift is a screening aid. Its output is a set of signals for human
review — not a legal or institutional determination of research misconduct,
and no substitute for review by editors, institutions, or domain experts.
