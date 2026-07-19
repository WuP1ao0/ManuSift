# Report layer — primary path vs secondary

> P2 redundancy pass. Open-source pattern: **single facade / primary
> pipeline** (Django dual-support then document deprecation of side
> modules; keep secondary formats callable without implying dual
> maintenance).

## Primary path (batch CLI / MCP screen)

```text
findings.json
    → manusift.report.investigation_pairs.write_investigation_pairs
       (investigation_pairs.html / .md / .json)
    → manusift.report.llm_report.write_llm_reports   # optional LLM packaging
       (also calls investigation_pairs + plain_investigation)
```

Entry points that use this path:

- `manusift.report.from_findings` (CLI regenerate)
- `manusift.report.llm_report.write_llm_reports` (pipeline tail when LLM on)
- `manusift.mcp.screen` (reads findings / pairs helpers)
- Job workspace paths: `JobPaths.investigation_pairs_*`

## Evidence report bundle (secondary, explicit)

Full visual/numerical evidence pack (optional, heavier):

```text
findings.json
    → manusift.report.orchestrator.build_evidence_report
       → evidence_builder.build_evidence_index
       → evidence_report render md/html
```

Also: `python -m manusift.report.evidence_cli`.

## Secondary / specialized (not the batch default)

| Module | Role | Status |
|--------|------|--------|
| `report/builder.py` | Early HTML findings dump | **Secondary** — prefer investigation_pairs |
| `report/narrative.py` | LLM narrative HTML/PDF | **Secondary** — optional enrichment |
| `report/plain_investigation.py` | Plain language investigation | **Secondary** — written by llm_report when enabled |
| `report/data_evidence.py` | Per-finding numerical explainers | Support for evidence bundle |
| `report/visual_evidence.py` | Crops / overlays | Support for evidence bundle |
| `report/evidence.py` | Evidence DTOs | Shared types |

## Guidance

1. New batch/MCP features should write or extend **investigation_pairs**.
2. Do not add parallel “main HTML report” paths under `builder.py`.
3. Evidence orchestrator stays for deep forensic packs, not every screen.

See also `docs/DETECTOR_LAYERS.md` for detector ownership.
