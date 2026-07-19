# ManuSift

**Screen scholarly PDFs and companion Source Data for research-integrity
red flags**—image reuse and forensics, table/source-data anomalies, and
metadata or text patterns—then write findings plus HTML reports.

Runs **offline** by default (`manusift screen --no-llm`; no API key).
Batch CLI for humans; **MCP** tools for other agents. Conversational chat
is not part of the product.

## Quickstart

Requires **Python ≥ 3.10** (3.11 recommended). Windows, Linux and macOS
x86_64/arm64 are supported when pip can fetch wheels for OpenCV /
NumPy / SciPy (no compiler required on common platforms).

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -U pip
pip install -e .

# Verify install (package-data + CLI + offline screen, no API keys)
python scripts/install_smoke.py

# Screen a paper (offline pipeline; no LLM keys / no network).
# Pin --workspace so results stay in a fixed directory you control.
manusift screen evals/fixtures/clean_academic.pdf --no-llm --suites fast --workspace ./my_jobs
# Or any PDF with the same pinned workspace root:
manusift screen path/to/paper.pdf --no-llm --workspace ./my_jobs
```

**Where results land:** each job writes under
`<workspace>/<trace_id>/output/` (with `--workspace DIR` that is
`DIR/<trace_id>/…`). If you omit `--workspace`, the default root is
`data/jobs/` → `data/jobs/<trace_id>/`. Outputs include
`findings.json`, `report.html`, `issues.json`, and
`investigation_pairs.html` under that `output/` folder. Prefer a fixed
`--workspace` when you need to open reports after the run (temp or
cwd-relative defaults are easy to lose).

Shipped sample PDFs live in `evals/fixtures/` (tracked in git so a bare
clone can smoke-test offline). If they are missing, `scripts/install_smoke.py`
generates a one-page PDF with PyMuPDF.

Optional extras:

```bash
pip install -e ".[dev]"   # pytest + ruff, for contributors
pip install -e ".[ocr]"   # EasyOCR+torch (~2 GB): figure_grim / figure_table_ocr
```

LLM enrichment/adjudication is **off by default** and is **not** required
for offline screening. To enable later, copy `.env.example` → `.env` and set
`MANUSIFT_ANTHROPIC_API_KEY` / `MANUSIFT_OPENAI_API_KEY` (see
`manusift/config.py`). Never commit `.env`.

Contributor tests: `pip install -e ".[dev]"` then e.g.
`python -m pytest -q tests/test_install_smoke.py` or the CI subset in
`.github/workflows/ci.yml`. Full-tree `pytest -q` is large (~thousands of
cases) and may include environment- or corpus-gated skips/fails; CI does
**not** require the entire tree green.

## License & community

- **License:** [MIT](LICENSE)
- **Contributing:** [CONTRIBUTING.md](CONTRIBUTING.md)
- **Code of Conduct:** [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **Security:** [SECURITY.md](SECURITY.md)
- **Changelog:** [CHANGELOG.md](CHANGELOG.md) (beta history; GitHub Releases may mirror tagged notes)
- **Cite:** [CITATION.cff](CITATION.cff)

### Integrity pattern notes (PubPeer-derived)

Screening-signal maps only—not misconduct determinations:

- [Integrity patterns → detectors](docs/pubpeer_integrity_patterns.md)
- [Fraud methods catalogue](docs/pubpeer_100_fraud_methods.md)
- [Coverage matrix](docs/pubpeer_100_coverage_matrix.md)

Also: [detector layering](docs/DETECTOR_LAYERS.md), [report paths](docs/REPORT_PATH.md),
[MCP client config](docs/mcp/README.md).

**Disclaimer:** ManuSift is a *screening* aid for integrity signals. It is not a
legal determination of misconduct and does not replace human review (editors,
institutions, or domain experts).

## Product shape (2026-07): **B + C only**

| Surface | Role |
|---------|------|
| **B — Batch CLI** | Strong offline `manusift screen` (no chat agent) |
| **C — MCP tools** | Domain Kernel for *other* agents (`manusift mcp`) |

**Removed:** conversational chat TUI (`chat_app`) is deleted. Optional
job browser remains as `manusift-workspace` / `manusift-tui`.

```bash
# B — batch screen (default suite is deep = full offline pipeline)
manusift screen paper.pdf --with-sidecar --no-llm
manusift screen paper.pdf --data-paths ./source_data --suites table
manusift screen paper.pdf --no-llm --suites fast   # lighter triage

# Suites: core | deep | fast | full | image | table
manusift suites
# Same entry via module (if console scripts not on PATH):
python -m manusift screen paper.pdf --no-llm

# C — MCP for Claude Desktop / Cursor / other agents
manusift mcp --list-tools          # full registry (~80+ tools; default)
manusift mcp --curated             # optional smaller kernel allow-list
manusift-mcp --list-tools          # same server entry point
python -m manusift mcp --list-tools

# Cursor / Claude Desktop (stdio example)
# { "command": "manusift-mcp", "args": [], "env": { "MANUSIFT_WORKSPACE_DIR": "..." } }
```

See `docs/mcp/README.md` for MCP client config.

**Detector layering** (pipeline vs agent-only vs EXCLUDED; `image_dup`
vs `imagehash_*`; `panel_dup` vs `panel_duplicate`):
`docs/DETECTOR_LAYERS.md`.

## Status (2026-07, beta)

**6 eval cases + 6 e2e eval, 9 console scripts,
52 registered detectors (44 offline pipeline; 8 EXCLUDED agent-only),
~80+ MCP tools by default (full registry; ``--curated`` for smaller set).**
Large pytest tree; CI runs a reproducible subset.

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
# CI subset / install_smoke — prefer targeted pytest; full tree optional

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
