# ManuSift

Paper-integrity screener: PDF (+ companion Source Data) → detector suite →
findings + HTML report. Flags suspicious metadata, image forensics
(ELA, copy-move, texture reuse), table forgery signals (Benford with
domain gates, near-dup rows, cross-sheet copy, …), and text/reference
patterns.

## Quickstart

Requires **Python ≥ 3.10** (3.11 recommended). Windows, Linux and macOS
are supported; heavy vision deps are installed as wheels.

```bash
git clone <repo-url> && cd ManuSift1
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
pip install -e .

# Screen a paper (offline pipeline, no LLM keys needed)
manusift screen path/to/paper.pdf --no-llm
```

Results land in `data/jobs/<trace_id>/output/` (`report.html`,
`findings.json`, `issues.json`, plus `investigation_pairs.html`).

Optional extras:

```bash
pip install -e ".[dev]"   # pytest + ruff, for contributors
pip install -e ".[ocr]"   # EasyOCR+torch (~2 GB): figure_grim / figure_table_ocr
```

LLM enrichment/adjudication is **off by default**; set
`MANUSIFT_ANTHROPIC_API_KEY` (or OpenAI equivalents) and
`MANUSIFT_LLM_ENRICH_MODE` / `MANUSIFT_LLM_ADJUDICATE` to enable.
Run the tests with `python -m pytest -q` (~2300 tests, no network or
benchmark data required).

## Product shape (2026-07): **B + C only**

| Surface | Role |
|---------|------|
| **B — Batch CLI** | Strong offline `manusift screen` (no chat agent) |
| **C — MCP tools** | Domain Kernel for *other* agents (`manusift mcp`) |

**Removed:** conversational chat TUI (`chat_app`) is deleted. Optional
job browser remains as `manusift-workspace` / `manusift-tui`.

```bash
# B — batch screen (core suite by default)
manusift screen paper.pdf --with-sidecar --no-llm
manusift screen paper.pdf --data-paths ./source_data --suites table

# Suites: core | full | image | table | fast
manusift suites

# C — MCP for Claude Desktop / Cursor / other agents
manusift mcp --list-tools          # curated 40 kernel tools
manusift mcp --all-tools           # full registry (large)
manusift-mcp --list-tools          # same server entry point

# Cursor / Claude Desktop (stdio)
# { "command": "manusift-mcp", "args": [], "env": { "MANUSIFT_WORKSPACE_DIR": "..." } }
```

See `docs/mcp/README.md` for MCP client config; the agent-runtime
(PydanticAI + MCP) architecture is documented in
`docs/AGENT_RUNTIME_MIGRATION.md`.

## Status (2026-07, beta)

**~2300 pytest (0 failed), 6 eval cases + 6 e2e eval passing,
9 console scripts, 48 registered detectors (39 in pipeline),
40 curated MCP tools.**

Current capabilities:

- **Image forensics** — pHash/aHash/dHash multi-hash duplicate
  detection, SIFT copy-move & cross-image matching, panel
  segmentation + SSIM, page-raster tile duplicates, noise/ELA
  inconsistency, AI-generated figure probes.
- **Table & statistics** — Benford (domain-gated), duplicate /
  near-duplicate rows, cross-sheet copy, round bias, outliers,
  GRIM / GRIMMER bound, DEBIT, and a statcheck-style recomputation
  of reported t / F / χ² / z / r statistics against their p-values
  (rounding-interval judgement, one-tailed exemption,
  decision-error flagging).
- **Figure ↔ text cross-checks** — bar-chart geometry extraction,
  figure-vs-table/prose percentage pairing, forest-plot rule
  pipeline (CI order / asymmetry / null-line checks).
- **Text & metadata** — tortured phrases (5,802-entry verified
  dictionary), paper-mill template/authorship signals, PDF
  metadata anomalies, reference duplication & format checks.
- **External verification** (opt-in, cached) — Crossref citation
  verification with offline replay, OpenAlex cited-retraction
  checks, data-availability link resolution.
- **Triage layer** — findings calibrated + aggregated into
  *issues* (5–10× fewer review items), publisher-baseline
  whitelist, optional LLM enrichment/adjudication (off by
  default). Negative-control benchmark: **0.00 high-severity
  findings per legit paper**; fraud benchmarks: **core recall
  1.000** (see `benchmarks/`).

## Web API

Start the server:

```bash
./.venv/Scripts/python.exe -m uvicorn manusift.web.app:app --port 8765
```

| Method | Path                                  | Purpose                           |
|--------|---------------------------------------|-----------------------------------|
| GET    | `/api/health`                         | Legacy health check (always 200)  |
| GET    | `/api/healthz`                        | Liveness probe (always 200)       |
| GET    | `/api/health/ready`                   | Readiness probe (200 or 503)      |
| POST   | `/api/upload`                         | Upload a PDF (rate-limited)       |
| GET    | `/api/jobs/{trace_id}`                | Job status + summary              |
| GET    | `/api/jobs/{trace_id}/progress`       | Live detector-by-detector progress|
| GET    | `/api/jobs/{trace_id}/findings`       | Finding list as JSON              |
| GET    | `/api/jobs/{trace_id}/report`         | HTML report                       |
| GET    | `/`                                   | Static dashboard (index.html)     |

Upload a PDF:

```bash
curl -F file=@paper.pdf http://127.0.0.1:8765/api/upload
# {"trace_id":"...","status":"queued",...}

curl http://127.0.0.1:8765/api/jobs/<trace_id>
curl http://127.0.0.1:8765/api/jobs/<trace_id>/findings
curl http://127.0.0.1:8765/api/jobs/<trace_id>/report | head
```

## Optional: job workspace browser

Browse finished jobs on disk (not a chat agent):

```bash
manusift-workspace
# or
manusift-tui
```

Conversational chat TUI (`chat_app`) has been **removed**.

## Configuration

All settings are environment variables prefixed `MANUSIFT_`. See
`manusift/config.py` for the full list and defaults. The most
common ones:

| Variable                          | Default                          | Purpose                          |
|-----------------------------------|----------------------------------|----------------------------------|
| `MANUSIFT_WORKSPACE_DIR`          | `./data/jobs`                    | Where uploaded PDFs land         |
| `MANUSIFT_MAX_UPLOAD_MB`          | `50`                             | Hard cap on upload size          |
| `MANUSIFT_OPENAI_API_KEY`         | _(unset)_                        | OpenAI-compatible API key        |
| `MANUSIFT_OPENAI_BASE_URL`        | `https://api.openai.com/v1`      | OpenAI base URL                  |
| `MANUSIFT_OPENAI_MODEL`           | `gpt-4o-mini`                    | OpenAI model name                |
| `MANUSIFT_ANTHROPIC_API_KEY`      | _(unset)_                        | Anthropic API key                |
| `MANUSIFT_ANTHROPIC_BASE_URL`     | `https://api.anthropic.com`      | Anthropic base URL               |
| `MANUSIFT_ANTHROPIC_MODEL`        | `claude-3-5-sonnet-latest`       | Anthropic model name             |
| `MANUSIFT_DEFAULT_LLM_PROVIDER`   | `openai`                         | `openai` or `anthropic`         |
| `MANUSIFT_LLM_MAX_CONCURRENCY`    | `4`                              | Parallel LLM calls per job       |
| `MANUSIFT_CORS_ALLOW_ORIGINS`     | `http://127.0.0.1:8765,...`      | Comma-separated CORS allow-list  |
| `MANUSIFT_RATE_LIMIT_PER_MINUTE`  | `10`                             | POSTs per IP per 60s (`0`=off)   |
| `MANUSIFT_LOG_LEVEL`              | `INFO`                           | Log level                        |

Run with a real LLM:

```bash
export MANUSIFT_OPENAI_API_KEY=...
./.venv/Scripts/python.exe -m uvicorn manusift.web.app:app --port 8765
```

With no API keys the pipeline runs in **mock mode**: no LLM
enrichment, mock "no verdict" replies. Use this for local dev
and CI.

## Adding a detector

```python
# manusift/detectors/my_detector.py
from .base import DetectorResult
from ..contracts import ParsedDoc

class MyDetector:
    """One-line description; this is what the LLM
    agent sees in the tool list."""
    name = "my_detector"

    def run(self, doc: ParsedDoc) -> DetectorResult:
        # ...
        return DetectorResult(
            detector=self.name, ok=True, findings=[], duration_ms=1
        )
```

Then register in `manusift/detectors/__init__.py`. To ship as a
**third-party plugin**, declare an entry point:

```toml
[project.entry-points."manusift.detectors"]
my_detector = "my_pkg:MyDetector"
```

## Architecture

```
PDF → ingest (PyMuPDF) → pipeline detectors
       (39 in pipeline; 3rd-party plugins via entry_points)
     → calibration + issue aggregation
     → LLM enrichment/adjudication (off by default)
     → HTML reports + output/findings.json + steps/<idx>.json checkpoint
```

The `Tool` Protocol (J1) is the same shape Claude Code uses
(`name` / `description` / `input_schema` / `execute`). Detectors
are double-Protocol: `Detector` for the pipeline, `Tool` for
the LLM agent. They share the same instance via a 1-file
adapter.

## Tests

```bash
./.venv/Scripts/python.exe -m pytest
# ~2300 passed, a few environment-gated skips

./.venv/Scripts/manusift-evals
# 5 passed, 1 LLM-gated skip (set MANUSIFT_LLM_EVALS=1 to enable)

./.venv/Scripts/manusift-evals-e2e
# 6 passed
```

## Benchmark regression gate (P5.2)

`scripts/ci_benchmark_gate.py` runs the four benchmarks
(`fraud_representatives_v1`, `fraud_web_v1`, `negative_controls_v1`,
`figure_text_v1`) and turns them into a hard gate: any benchmark's
core recall < 1.0, > 2.0 high-severity findings per legit control
paper, or any figure-text negative-case false positive fails the run
(exit 1). It sets the smoke env vars for the subprocesses itself
(including `MANUSIFT_CROSSREF_OFFLINE=1`, so citation checks replay
from `data/cache/crossref_cache.json` — no network).

```bash
# Full gate: re-run all detectors + aggregate + check (1-2 h)
./.venv/Scripts/python.exe scripts/ci_benchmark_gate.py

# Fast check against the persisted artifacts (seconds)
./.venv/Scripts/python.exe scripts/ci_benchmark_gate.py --skip-run

# Single benchmark
./.venv/Scripts/python.exe scripts/ci_benchmark_gate.py --only fraud_web_v1
```

CI wiring lives in `.github/workflows/benchmark_gate.yml`: the gate
*rule* tests run on every PR; the full benchmark gate runs on demand
(`workflow_dispatch`) and restores the benchmark corpora (~430 MB,
gitignored) from the `benchmark-data` GitHub Release asset — see the
workflow header for the one-time upload command.

## Roadmap

The 2026-07-18 roadmap (P1–P5: precision triage, external
verification, MCP product surface, figure-text cross-checks, eval
expansion + CI gate) is **complete**. Registered follow-ups for
future versions: cross-paper evidence comparison
(retraction-database + image-fingerprint corpus), DePlot
cross-validation for charts, adversarial ("whitewashed") benchmark
cases.
