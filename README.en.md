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

## What is this?

ManuSift is an **academic-integrity screening agent**. Feed it a paper PDF
(plus Source Data spreadsheets if you have them) and it runs 52 detectors over
it — image reuse, fabricated-table fingerprints, stats that don't add up,
tortured phrases, citation weirdness — then hands you a report with evidence.

Two ways to use it:

| Mode | In one line |
|------|-------------|
| **Interactive agent** (recommended) | Type `manusift` for the branded TUI and screen papers conversationally; `/screen <pdf>` fires the whole pipeline |
| **Batch CLI** | `manusift screen paper.pdf --no-llm` — fully offline, zero API keys, great for scripts |

Architecturally it's an "oh-my-pi style" standalone agent: the interactive
layer is built on the [pi](https://github.com/earendil-works/pi) SDK (no
fork), the detection kernel stays in Python, and a JSON-lines stdio bridge
(`manusift toolserver`) feeds all **~82 domain tools** to the agent.

> **Up front:** ManuSift produces *screening signals*, not misconduct
> verdicts. Humans make the call.

---

## Quickstart

Python ≥ 3.10 (3.11 recommended). Windows / Linux / macOS all fine.

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift

python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate
pip install -e .

# smoke test the install
python scripts/install_smoke.py

# screen a paper offline (no keys needed)
manusift screen evals/fixtures/clean_academic.pdf --no-llm --suites fast --workspace ./my_jobs
```

### Interactive agent (needs Node.js ≥ 20 + an LLM key)

```bash
cd agent && npm install --ignore-scripts && cd ..   # one-time
manusift                                            # branded TUI, just chat
```

Inside the TUI:

- Talk normally: `screen C:\papers\paper.pdf for integrity issues`,
  `is figure 3 duplicated?`
- `/screen <pdf>` — runs the full pipeline in the background (progress in the
  footer) and summarizes the verdict when done
- `/manusift status` / `restart` — check or restart the Python tool bridge
- One-shot mode: `manusift agent -p "screen path/to/paper.pdf"`

The agent's LLM key goes through pi's auth (first launch walks you through
login, or set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`). **Batch mode needs
none of this.**

### Where results land

```text
<workspace>/<trace_id>/
├── inputs/       # original PDF (+ companion data)
├── steps/        # per-detector checkpoints
└── output/
    ├── findings.json            # calibrated raw findings
    ├── issues.json              # aggregated review items (fewer, readable)
    ├── report.html              # HTML summary
    └── investigation_pairs.*    # primary investigation view (open this first)
```

Always pass `--workspace`, otherwise results land in `data/jobs/` and get
easy to lose.

### Optional extras

```bash
pip install -e ".[dev]"   # pytest + ruff (contributors)
pip install -e ".[ocr]"   # EasyOCR + torch (~2GB): unlocks in-figure table OCR detectors
```

Want LLM-polished batch reports? Copy `.env.example` → `.env`, set
`MANUSIFT_OPENAI_API_KEY` or `MANUSIFT_ANTHROPIC_API_KEY`, and drop
`--no-llm`. Without keys everything still runs; `llm_report.*` just stays an
empty shell. Reports default to Chinese; `--lang en` switches to English.

---

## What it checks

| Area | The actual checks |
|------|-------------------|
| **Image forensics** | Multi-hash reuse (pHash/aHash/dHash), SIFT copy-move, flip/rotate matching, gel seams, panel + SSIM, page-raster tiles, noise/ELA, AI-generated-figure probes |
| **Tables & statistics** | Benford, duplicate/near-duplicate rows, cross-sheet copies, fixed offsets/ratios, decimal-tail bias, GRIM/GRIMMER, DEBIT, statcheck-style t/F/χ²/z/r vs p recomputation |
| **Figure ↔ text** | Bar-chart geometry vs reported numbers, forest-plot CI rules |
| **Text & metadata** | Tortured phrases (5,802-entry dictionary), paper-mill signals, PDF metadata, reference duplicates/conflicts |
| **External checks** (opt-in) | Crossref / OpenAlex retraction lookups / data-availability link checks (cached; offline replay for CI) |
| **Triage** | Calibration + issue aggregation into high/medium/low — deliberately conservative |

Numbers, so nobody gets confused: **52** detectors registered, **44** run in
the offline pipeline (8 are agent-on-demand); the agent tool surface is
**~82** tools = detectors-as-tools + ingest/report/job helpers. Count them
yourself with `manusift toolserver --list-tools`.

---

## How it's wired

```text
you ──> manusift  (branded TUI, pi SDK, agent/bin/manusift-agent.mjs)
          │  ships the integrity-screening system prompt;
          │  read-only tool surface by default (--dev opens bash/edit/write)
          ▼
        .pi/extensions/manusift/   bridge extension (/screen, dedup gate, 82 tools)
          ▼
        python -m manusift.toolserver   JSON-lines stdio bridge
          ▼
        Python detection kernel: ingest → 44 detectors in parallel → calibrate/aggregate → reports
```

Batch `manusift screen` talks to the bottom layer directly — no agent
involved.

Other entry points: `manusift-workspace` (local job browser) and
`python -m uvicorn manusift.web.app:app` (loopback-only HTTP API — this is
not a hosted cloud).

### Adding your own detector

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """One-liner (also shows up in the agent tool list)."""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        return DetectorResult(detector=self.name, ok=True, findings=[], duration_ms=1)
```

Register it in `manusift/detectors/__init__.py`, or ship it as a third-party
plugin via entry_points — it becomes an agent tool automatically.

---

## Common configuration

Everything is prefixed `MANUSIFT_`; full list in `manusift/config.py`.

| Variable | Default | What it does |
|----------|---------|--------------|
| `MANUSIFT_WORKSPACE_DIR` | `./data/jobs` | Job root (same as `--workspace`) |
| `MANUSIFT_DETECTOR_WORKERS` | `4` | Detector parallelism (`1` = serial) |
| `MANUSIFT_REPORT_LANGUAGE` | `zh` | Report language `zh` / `en` |
| `MANUSIFT_OPENAI_API_KEY` etc. | unset | Batch LLM enrichment (optional) |
| `MANUSIFT_PYTHON` | auto-detect `.venv` | Which Python the agent bridge uses |
| `MANUSIFT_PI` | unset | Force plain pi instead of the standalone agent |

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
python -m pytest -q          # full suite
python -m ruff check manusift tests

python scripts/ci_benchmark_gate.py --skip-run   # benchmark gate (persisted artifacts)
```

Benchmarks live in `benchmarks/`: real retraction cases hold recall at 1.0
and negative controls at zero high-severity false positives. Read
`docs/DETECTOR_LAYERS.md` before touching detectors, run the gate after.

---

## License & community

MIT ([LICENSE](LICENSE)) · [Contributing](CONTRIBUTING.md) ·
[Code of Conduct](CODE_OF_CONDUCT.md) · [Security](SECURITY.md) ·
[Changelog](CHANGELOG.md) · [Cite](CITATION.cff)

## Disclaimer

ManuSift is a **screening aid**. It surfaces signals worth a human look — it
is not a legal or institutional determination of research misconduct, and it
does not replace review by editors, institutions, or domain experts.
