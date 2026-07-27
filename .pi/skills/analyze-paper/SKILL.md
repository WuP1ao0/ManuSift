---
name: analyze-paper
description: Offline-screen a paper PDF (or continue from a known trace_id) with ManuSift domain tools and summarize findings. Use when the user asks to analyze, screen, or check a paper.
---

# analyze-paper

Screen a paper with the ManuSift domain tools (no report file unless
asked; see the integrity-report skill for the full report).

1. `ingest_from_path(path=<pdf>, data_paths=[...])` → `trace_id`
   (skip if the user supplied an existing trace_id).
2. `list_data_sources(trace_id)` — confirm companion XLSX/CSV/ZIP
   registration; `read_data_source` the relevant tables before drawing
   numeric conclusions.
3. Minimal triage set, expand as material warrants:
   - `metadata` / `pdf_metadata` — document hygiene
   - `image_dup` + `image_forensics` — figure reuse / manipulation
   - `table_forensics` or `table_benford` / `table_duplicate_row` /
     `source_data_audit` — table & Source Data signals
   - `stat_grim` / `stat_pvalue` — reported statistics
   - `ref_duplicate` / `citation_network` — references
4. Summarize with the 5-section review shape (当前状态 / 已检查 /
   关键风险 / 未能测试 / 下一步). Screening signals only — never a
   misconduct verdict.

For a full offline batch run instead, the CLI remains:
`manusift screen <pdf> --no-llm --workspace <dir>`.
