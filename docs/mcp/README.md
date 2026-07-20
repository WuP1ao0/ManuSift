# ManuSift MCP — external agent tool surface

Exposes **Domain Kernel tools only** (detectors, ingest, inspection, render,
screen jobs). No agent loop is started inside MCP; the host LLM (Claude Desktop,
Cursor, …) decides which tools to call.

Product **C** of B+C (batch CLI + MCP). This is **not** the optional local
HTTP upload API (`uvicorn` on `127.0.0.1`) — that loopback server is separate
and is not a hosted cloud service.

## Counts

| Surface | Count | How to see |
|---------|------:|------------|
| MCP tools (default) | **~83** | `manusift mcp --list-tools` |
| MCP tools (`--curated`) | **~45** | `manusift mcp --curated --list-tools` |
| Registered detectors | 52 | Package registry (subset of MCP tools) |
| Offline pipeline | 44 | Batch `manusift screen` |

Detectors and MCP tools are different: MCP adds helpers such as
`screen_verdict`, `submit_screen`, `ingest_from_path`, `render_report`,
FS/vault tools, etc. Layering detail: [`docs/DETECTOR_LAYERS.md`](../DETECTOR_LAYERS.md).

## Quick check

```bash
# from repo root, with venv active
manusift-mcp --list-tools
# or
python -m manusift.mcp --list-tools
# optional smaller surface:
manusift mcp --curated --list-tools
```

By default, expect the **full** registered tool list (~83: detectors,
screen jobs, agent utilities). Optional ``--curated`` restricts to the
smaller kernel allow-list in ``manusift.mcp.surface.MCP_DEFAULT_TOOLS`` (~45).

## Three-minute quickstart: `screen_verdict`

The product surface leads with a one-call triage tool — no ingest /
detector choreography required:

1. Point your MCP client at this server (any config below).
2. Call `screen_verdict` with `{"path": "C:/path/to/paper.pdf"}`.
3. Read the verdict:

```json
{
  "verdict": "suspect",
  "score": 0.4,
  "top_issues": [
    {"issue_id": "ISS-…", "severity": "medium", "title": "…",
     "detectors": ["image_dup"], "member_count": 3}
  ],
  "counts_by_severity": {"high": 0, "medium": 3, "low": 1, "info": 2},
  "report_path": "…/data/jobs/<trace_id>/output/report.html",
  "trace_id": "<trace_id>"
}
```

**Verdict rule** (single implementation in `manusift/mcp/screen.py`;
mirrored in the tool description):

- `flagged` — at least one **high**-severity issue.
- `suspect` — no high issue, but ≥ `MANUSIFT_SCREEN_SUSPECT_MEDIUM_ISSUE_THRESHOLD`
  (default **3**) **medium**-severity issues.
- `clean` — otherwise.

Issues are the P1.1 aggregated view (`issues.json`): findings from
several detectors pointing at the same evidence object count once.

**Score** (0-1, severity-weighted, deliberately simple):
`min(1.0, (1.0*high + 0.4*medium + 0.1*low) / 3.0)` — one high issue
scores 0.333, three high issues saturate at 1.0. `info` weighs 0.

`screen_verdict` runs the full pipeline synchronously with LLM
enrichment/adjudication **off** (deterministic, offline; pass
`use_llm: true` to enable enrichment). Called with only a `trace_id`
(no `path`), it reuses the already-analysed artifacts instead of
re-running.

## Async screen jobs (large PDFs)

For real papers the pipeline takes minutes; use the async trio so the
MCP server stays responsive:

```
submit_screen(path)            -> {"job_id": "…", "status": "queued"}
get_job_status(job_id)         -> {status: queued|running|done|failed,
                                   progress_pct, stage, steps_done,
                                   steps_total, ...}   # poll
get_job_result(job_id)         -> same payload as screen_verdict
                                   (or the status payload while running)
```

A raw JSON-RPC call sequence (initialize → submit → poll → result →
sync variant) lives in [`async_calls.example.jsonl`](./async_calls.example.jsonl).

- Progress comes from the pipeline's per-detector hook:
  `progress_pct = floor(100 * steps_done / steps_total)`, monotonic,
  capped at 99 until the run finishes (then 100); `stage` is the last
  finished detector.
- State is persisted per job at
  `<workspace>/_screen_jobs/<job_id>.json` (atomic writes); the
  verdict lands at `<workspace>/<trace_id>/output/screen_verdict.json`.
  Completed jobs survive a server restart; a job caught mid-run by a
  restart is reported as `failed` with
  `error="interrupted: server restarted"` instead of polling forever.
- `job_id` equals the pipeline `trace_id`, so all raw tools
  (`list_findings`, `render_report`, …) work on the same workspace
  once the job is done.


## Claude Desktop

1. Copy [`claude_desktop.example.json`](./claude_desktop.example.json) keys into:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`
2. Edit paths to match your install (venv `manusift-mcp.exe` + workspace dir).
3. Restart Claude Desktop.
4. In a chat, ask to list MCP tools or “run image_dup on this paper after ingest”.

Prefer the console script when available:

```text
.venv/Scripts/manusift-mcp.exe
```

Fallback:

```text
.venv/Scripts/python.exe -m manusift.mcp
```

## Cursor

1. Open Cursor MCP settings (or project `.cursor/mcp.json` if you use project-level MCP).
2. Merge [`cursor.example.json`](./cursor.example.json).
3. Restart Cursor / reload MCP servers.
4. Tools appear under the ManuSift server for agent tool-use.

## Claude Code

One-line registration (user scope):

```bash
# Prefer manusift-mcp on PATH after pip install -e .
claude mcp add manusift -- manusift-mcp
# Windows venv fallback (adjust to your clone):
# claude mcp add manusift -- ".venv\Scripts\manusift-mcp.exe"
```

Or project scope: copy [`claude_code.mcp.json`](./claude_code.mcp.json)
to the project root as `.mcp.json` and restart `claude`.

Verify inside a session: `/mcp` should list `manusift` with ~83 tools
(`screen_verdict`, `submit_screen`, `ingest_from_path`, `image_forensics`,
`table_forensics`, …).

## Codex (OpenAI CLI)

Merge [`codex.config.toml`](./codex.config.toml) into
`~/.codex/config.toml`, restart `codex`, then ask it to ingest a PDF
and run a detector.

## Windows note (UTF-8 stdio)

The server emits UTF-8 (arrows / CJK in instructions and payloads).
On Windows hosts that decode stdio with the system codepage (e.g.
GBK), set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` in the server
`env` (already present in all example configs in this directory).

## Startup time & robustness notes

- First `initialize` can take **10-30 s**: the server eagerly
  imports the native chain (numpy/scipy/imagehash/cv2/torch) on the
  main thread before starting the event loop. This is deliberate --
  lazy native imports inside the running loop deadlock on Windows
  (numpy/scipy C-extension `create_module`). Give your MCP client a
  generous init timeout.
- Heavy tools (image_forensics, table_forensics on big PDFs) run in
  worker threads (`asyncio.to_thread`), so the server stays
  responsive to other requests while they execute.
- Library prints (e.g. the PyMuPDF layout promo) are redirected to
  stderr during tool execution so they cannot corrupt the JSON-RPC
  channel; `pymupdf.no_recommend_layout()` is also called at startup.
- `MANUSIFT_MCP_DEBUG=1` env var: stderr start/done markers per tool
  call + periodic faulthandler thread dumps (debugging hangs).

## Optional flags

| Flag | Meaning |
|------|---------|
| `--list-tools` | Print JSON tool list and exit (no stdio session) |
| `--curated` | Serve only `MCP_DEFAULT_TOOLS` (~45) instead of the full ~83 |
| `--all-tools` | No-op alias for the default full registry |
| `--tools name1,name2` | Allow-list only these tools |
| `--trace-id ID` | Default job / workspace key for tool calls |

Per-call `trace_id` may also be passed in tool arguments; that overrides the server default.

## Workspace paths

Example configs in this directory use portable commands (`manusift-mcp` or
`python -m manusift.mcp`) and `MANUSIFT_WORKSPACE_DIR=./data/jobs`. Point
`MANUSIFT_WORKSPACE_DIR` at a directory **you** control; do not copy
machine-specific absolute paths from old screenshots.

## Notes

- Workspace paths must be writable (`MANUSIFT_WORKSPACE_DIR`).
- Heavy detectors (OCR, Crossref) may need optional deps and network.
- Optional host-agent loop runtime (`create_agent_loop`, not product CLI):
  see `docs/AGENT_RUNTIME_MIGRATION.md` (`MANUSIFT_AGENT_RUNTIME`).
  Conversational chat TUI was removed; use MCP or batch `manusift screen`.
