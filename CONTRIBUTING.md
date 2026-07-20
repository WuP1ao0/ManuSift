# Contributing to ManuSift

Thanks for helping improve offline paper-integrity screening.

**Product shape:** batch CLI (`manusift screen`) + MCP Domain Kernel
(`manusift mcp`) — no conversational chat product. Counts live in the
README **Capabilities** table and [`docs/DETECTOR_LAYERS.md`](docs/DETECTOR_LAYERS.md)
(~83 MCP tools default ≠ 52 detectors).

## Development setup

```bash
git clone https://github.com/WuP1ao0/ManuSift.git
cd ManuSift
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
python scripts/install_smoke.py
```

Optional OCR stack (large): `pip install -e ".[ocr]"`.

## Before you open a PR

1. **Secrets**: never commit `.env`, API keys, or private PDFs with PII.
2. **Install smoke**: `python scripts/install_smoke.py` (CLI + offline screen).
3. **Targeted tests** for your change, e.g.  
   `python -m pytest tests/test_install_smoke.py -q`
4. Prefer small, focused diffs. Detector threshold changes should note
   impact on `negative_controls` / fraud fixtures when you have them.

## Code layout (short)

| Path | Role |
|------|------|
| `manusift/pipeline.py` | Offline batch screen |
| `manusift/detectors/` | Detectors (see `docs/DETECTOR_LAYERS.md`) |
| `manusift/mcp/` | MCP Domain Kernel for other agents |
| `manusift/cli.py` | `manusift` console entry |
| `tests/` | Pytest suite |
| `evals/fixtures/` | Tiny sample PDFs for smoke |

## Style

- Python 3.10+; package metadata in `pyproject.toml`.
- Lint: `ruff check manusift tests` (pre-existing debt is OK; don't expand it).
- Domain objects are dataclasses in `manusift/contracts.py` (not free-form dicts).

## Reporting bugs

Prefer the **Bug report** issue template (`.github/ISSUE_TEMPLATE/`). Include:
OS, Python version, install command, full traceback, and a **minimal** PDF if
possible (synthetic preferred).

Security-sensitive reports: see [SECURITY.md](SECURITY.md).

## Version history

User-facing changes: [CHANGELOG.md](CHANGELOG.md). Tagged GitHub Releases may
mirror the same notes for a release cut.
