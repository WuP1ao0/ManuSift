# ManuSift

Paper-integrity screener. Upload a PDF, get a report listing every place
that looks like it could be forged — suspicious metadata, duplicate
images, image forensics (ELA, copy-move), and text patterns
(placeholders, chatbot disclaimers, citation anomalies).

The system runs as either a **web app** (`manusift-tui` + a FastAPI
server) or a **chat TUI** (`manusift-chat`) where an LLM agent
decides which local detector tools to call.

## Status (2026-06)

**482 pytest + 4 skip, 6 eval cases passing (5+1), 6 console scripts,
13 slash commands.**

ManuSift has completed:

- **Step 1–8** — blueprint, image forensics, text patterns, eval
  suite, e2e eval, real LLM enrichment, 4-column TUI, TUI filter
- **H1–H5** — LLM schema validation, typed `DetectorResult`,
  per-step checkpoint, real-time progress endpoint, detector
  entry-points plugin
- **J1–J5** — `Tool` Protocol, LLM `chat()` with tool use,
  ReAct `AgentLoop`, tool entry-points plugin, chat TUI
- **L1–L6** — SecretStr API keys, PDF size + magic check, CORS
  + rate limiting, pip-audit, liveness/readiness probes,
  tool-call audit log
- **P0–P4.3** — structurel log, markdown reports, real streaming,
  Skill system, Plan mode
- **G1–G5 + G5.5** — HTTP retry + circuit-breaker, thread lock,
  graceful shutdown, idempotency key, Prometheus metrics, SDK-level
  retry (OpenAI + Anthropic + Crossref)
- **E1–E5** — formatter registry, rate-limit strategy registry,
  EventBus + webhooks, plugin self-config, hook registry
- **T1–T1.4** — splash banner (cyber/vaporwave), in-TUI banner,
  S-curve fix, TUI colors, token+cost status bar, spinner,
  tool-call visual, 5 Claude-Code slash cmds
- **A.5 + A.1 + A.4 + A.2 + A.3** — token-speed indicator, Shift+Tab
  plan toggle, auto-accept mode, 2-pane chat, session tree
- **Phase A-D (R-2026-06-17 → 2026-06-19)** — borrowed 16
  hardening modules from Claude Code + Hermes:
  - **Phase A** — 8 `read_file` guards: device block,
    binary block, tilde expansion, `/proc` block,
    char-limit guard, BOM strip, protected dir,
    document extraction fallback.
  - **Phase B** — 4 medium-cost: similar files
    fuzzy match, mtime dedup + BLOCKED-after-2-hits,
    `redact_sensitive_text` (30+ API-key prefix
    regex), real `.docx` / `.xlsx` / `.ipynb`
    extractors via `python-docx` / `openpyxl` /
    `nbformat`.
  - **Phase C** — `detect_xlsx_figs`: two-pass
    header scan (top band + 50-row chunks) for
    `Fig.<name>` / `Table <name>` / `Tab.<n>` /
    `Figure <n>`. The fig-aware
    `extract_xlsx_text` emits one `## Fig:` block
    per panel with full (rows, cols) bbox +
    200-row cap. Verified on the real Nature
    `Source_Data_MOESM3.xlsx` (874 KB, 15 figs
    across `Sfig.2` / `Sfig.3` / `Sfig.4`).
  - **Phase D** — per-fig xlsx + per-fig detector
    run. `ExtractedTable` got `fig_name` + `bbox`
    fields. `parse_xlsx` splits multi-fig sheets
    into per-fig records. `_format_table_label`
    makes detector titles fig-aware
    (`"Fig.S1a in Sfig.2 column 'X' violates Benford's law"`).
    `DetectorToolAdapter` accepts a `table_ids`
    list to scope a detector to a single fig
    (`table_benford({table_ids: ["<x:...:Sfig.2:Fig.S1a>"]})`).
    `ListDataSourcesTool` output includes
    `fig_name` + 1-indexed `bbox`. The LLM can now
    answer "check Fig.S1a only" instead of running
    the detector on all 6 figs at once.

## Quick start

```bash
# venv is reused; install in editable mode
./.venv/Scripts/python.exe -m pip install -e ".[dev]"

# Web server
./.venv/Scripts/python.exe -m uvicorn manusift.web.app:app --port 8765

# Or: chat TUI (LLM agent drives detector tools)
./.venv/Scripts/manusift-chat

# Or: jobs dashboard TUI
./.venv/Scripts/manusift-tui

# Tests + evals
./.venv/Scripts/python.exe -m pytest
./.venv/Scripts/manusift-evals
./.venv/Scripts/manusift-evals-e2e
```

## Web API

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

## Chat TUI

`manusift-chat` opens a textual TUI that lets you converse with an
LLM agent. The agent decides which local detector tool to call.
The TUI features:

- **Cyber/vaporwave splash banner** at the top of the screen
  (Unicode block letters, ANSI 256-color gradient, box-drawing border)
- **Token + cost status bar** with throughput indicator (`12 t/s`)
- **LoadingIndicator** (spinner) that appears while the agent runs
- **2-pane layout**: chat history (60%) + context sidebar (40%)
- **Tool-call visual**: every tool invocation shows `[ tool: NAME ]`
- **Persistent history** to `data/chats/<sid>/messages.jsonl`
- **Cost log** to `data/cost/calls.jsonl`

### Slash commands (14)

| Command           | Purpose                                           |
|-------------------|---------------------------------------------------|
| `/upload <path>`  | load a PDF as the active context                  |
| `/clear`          | clear the on-screen history (file is kept)        |
| `/tools`          | list available tools                              |
| `/skill <name>`   | load a named skill into ctx                       |
| `/skills`         | list all available skills                         |
| `/plan [on/off]`  | show or toggle plan mode                          |
| `/go`             | execute the plan the agent proposed               |
| `/auto-accept`    | toggle auto-accept for tool calls                 |
| `/cost`           | show running token + USD totals                   |
| `/status`         | show session metadata                             |
| `/resume`         | list past chat sessions                           |
| `/model`          | show active LLM client + model                    |
| `/tree`           | show a tree of saved sessions                     |
| `/theme [name]`   | cycle through built-in textual themes             |
| `/help`           | list all slash commands                           |

### Keyboard shortcuts

- `Ctrl+C` — clear input + status
- `q` — quit
- `Shift+Tab` — toggle plan mode (A.1)

History is persisted to `data/chats/<sid>/messages.jsonl`.
Tool-call audit goes to `data/chats/<sid>/tool_calls.jsonl`.

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

See `PLAN.md` for the full blueprint (36 KB). TL;DR:

```
PDF → ingest (PyMuPDF) → 4 detector classes
       (metadata, image_dup, image_forensics, text_patterns)
       + 3rd-party detector plugins (entry_points)
     → LLM enrichment (high/medium severity findings only)
     → HTML report + findings.json + steps/<idx>.json checkpoint
```

The `Tool` Protocol (J1) is the same shape Claude Code uses
(`name` / `description` / `input_schema` / `execute`). Detectors
are double-Protocol: `Detector` for the pipeline, `Tool` for
the LLM agent. They share the same instance via a 1-file
adapter.

## Tests

```bash
./.venv/Scripts/python.exe -m pytest
# 171 passed, 1 skipped in 5.82s

./.venv/Scripts/manusift-evals
# 5 passed, 1 LLM-gated skip (set MANUSIFT_LLM_EVALS=1 to enable)

./.venv/Scripts/manusift-evals-e2e
# 6 passed, 0 skipped
```

## Production-grade checklist

See `PLAN.md` §9 for the full production-grade gap list. The
P0 quick wins are all done (L1–L6). Next:

- **P1**: SQLite job state, Celery + Redis queue, JWT auth,
  Dockerfile + compose, GitHub Actions CI
- **P2**: streaming chat output, plan mode, Skill system
  (SKILL.md), subagents, tool audit log
