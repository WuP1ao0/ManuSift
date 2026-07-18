"""Curated MCP tool surface for product shape B+C.

Other agents should call a small Domain Kernel surface, not the full
~66-tool registry (schema bloat / model confusion). Full registry remains
available via ``manusift mcp --all-tools``.
"""
from __future__ import annotations

# Ordered for discoverability in MCP clients.
MCP_DEFAULT_TOOLS: list[str] = [
    # product surface (P3): one-call triage + async jobs
    "screen_verdict",
    "submit_screen",
    "get_job_status",
    "get_job_result",
    # lifecycle
    "ingest_from_path",
    "list_data_sources",
    "read_data_source",
    "source_data_audit",
    "list_findings",
    "read_finding",
    "list_dir",
    "render_report",
    # metadata
    "metadata",
    "pdf_metadata",
    "supplementary",
    # image suite (SIFT primary lives inside image_forensics + standalone)
    "image_dup",
    "image_forensics",
    "image_sift_copymove",
    "panel_dup",
    "page_raster_dup",
    "ai_generated_figure",
    # table suite
    "table_forensics",
    "table_benford",
    "table_duplicate_row",
    "table_near_duplicate_row",
    "table_cross_copy",
    "table_outlier",
    "table_round_bias",
    "table_relationships",
    "table_file_metadata",
    "table_highlight_focus",
    # stats / text / refs
    "stat_grim",
    "stat_pvalue",
    "figure_grim",
    "figure_stat_text",
    "text_patterns",
    "text_tortured_phrases",
    "ref_duplicate",
    "compliance",
    "data_availability_concern",
]
