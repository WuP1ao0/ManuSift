# ManuSift — standalone academic-integrity agent (pi SDK)

ManuSift ships its own branded agent (oh-my-pi style, **no fork**) built on
the [pi](https://github.com/earendil-works/pi) SDK
(`@earendil-works/pi-coding-agent`). The Python package remains the
detection kernel (52 detectors, ~82 domain tools); the pi harness provides
the loop, TUI, sessions, and skills.

```
agent/bin/manusift-agent.mjs         standalone entry (pi SDK)
  ├─ InteractiveMode TUI, ManuSift branding (agent/src/branding.ts)
  ├─ systemPromptOverride: integrity-screening prompt
  │    (agent/src/system-prompt.mjs — single source of truth)
  ├─ read-only built-in tools by default (no bash/edit/write; --dev opens them)
  └─ loads the bridge extension + skills from any launch directory

.pi/extensions/manusift/             bridge extension (also works in plain pi)
  ├─ index.ts                        spawns the Python toolserver, registers ~82 tools,
  │                                  /screen full-pipeline command, /manusift status
  ├─ system-prompt.ts                re-export of agent/src/system-prompt.mjs
  └─ gate.ts                         tool-call dedup + caps

python -m manusift.toolserver        JSON-lines stdio bridge (list / call)
```

## Setup

1. Python environment (detection kernel), from the repo root:

   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
   pip install -e .
   ```

2. Agent package (Node.js ≥ 20):

   ```bash
   cd agent && npm install --ignore-scripts
   ```

   (Installing plain pi globally is optional; the standalone agent bundles
   its own copy of the harness.)

3. An LLM provider key for pi (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`);
   see `pi --list-models` and the pi docs.

## Run

```bash
manusift                              # branded TUI (works from any directory)
manusift agent -p "对论文做诚信筛查: C:/papers/paper.pdf"   # one-shot print mode
manusift agent --dev                  # enable full coding tools (bash/edit/write)
```

Inside the TUI:

- `/screen <pdf>` — run the full offline pipeline as a background job;
  the verdict is injected and summarized in the 5-section review shape.
- `/manusift status | restart` — bridge health.

`manusift` prefers the standalone agent (`node agent/bin/manusift-agent.mjs`);
if node or `agent/node_modules` is missing it falls back to wrapping a
globally installed `pi` with the project extension. `MANUSIFT_PI` forces
the plain-pi path.

On session start the extension spawns `python -m manusift.toolserver`
(first start takes 10-30 s: numpy/scipy/torch pre-imports) and registers
every domain tool. You will see `ManuSift: 82 domain tools registered`.

Example prompts:

```
对 C:\papers\paper.pdf 做诚信筛查
Is figure 3 in C:\papers\paper.pdf duplicated?
用中文给 C:\papers\paper.pdf 出一份完整报告
```

Skills (auto-loaded from `.pi/skills/`): `analyze-paper`,
`compare-pdfs`, `integrity-report`, `summarize-findings`.

## Commands & knobs

| What | How |
|------|-----|
| Bridge status | `/manusift status` |
| Restart bridge | `/manusift restart` |
| Python override | `MANUSIFT_PYTHON=<path to python>` (default: `.venv` then PATH) |
| pi executable override | `MANUSIFT_PI=<path to pi>` (default: `pi` on PATH) |
| Safe mode (auto) | standalone agent sets `MANUSIFT_AGENT_SAFE=1` unless `--dev`: built-in bash/edit/write excluded and domain bash/python_exec/web_* not registered |
| Bridge debug | `MANUSIFT_TOOLSERVER_DEBUG=1` (stderr tracing) |
| Workspace | pin `MANUSIFT_WORKSPACE_DIR` so job outputs are easy to find |

## Batch CLI (unchanged)

The offline batch surface does not involve pi:

```bash
manusift screen paper.pdf --no-llm --workspace <dir>
```

## Troubleshooting

- **"toolserver unavailable"** — the Python env lacks `manusift` or its
  dependencies. Activate the venv, `pip install -e .`, then
  `/manusift restart`. Verify with
  `python -m manusift.toolserver --list-tools`.
- **Slow first start** — heavy native imports are front-loaded to avoid
  Windows import deadlocks; later calls are fast.
- **Tools missing from the prompt** — the toolserver had not finished
  starting when the turn began; wait for the registered notification or
  check `/manusift status`.
