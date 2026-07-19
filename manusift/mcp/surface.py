"""MCP tool surfaces for product shape B+C.

**Default MCP server** exposes **every** registered tool (~80+:
detectors + agent utilities). Prefer that for full Domain Kernel access.

``MCP_DEFAULT_TOOLS`` is the optional **curated** allow-list used only when
the server is started with ``--curated`` (smaller schema for hosts that
prefer a focused subset).
"""
from __future__ import annotations

# Optional curated allow-list (``manusift mcp --curated``).
# Ordered for discoverability when the restricted surface is requested.
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
    # table suite + SI (Source Data xlsx/csv vs PDF tables)
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
    "source_data_consistency",
    # P6 image / stats / cross-paper (also in offline pipeline)
    "cross_paper_image",
    "stat_pvalue_pileup",
    "stat_corr_psd",
    "stat_sprite",
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
