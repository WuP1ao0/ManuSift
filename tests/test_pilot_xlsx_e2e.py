"""Real pilot: parse the user's PDF + 8 companion XLSX and run the
table-statistics detectors.

This is the end-to-end
verification that the
new data-source
pipeline actually
analyses real Nature
source-data.

Run with::

  .venv/Scripts/python.exe
    tests/test_pilot_xlsx_e2e.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
os.chdir(str(Path(__file__).resolve().parents[1]))
os.environ["MANUSIFT_WORKSPACE_DIR"] = str(
    Path(__file__).resolve().parents[1] / "data" / "pilot_jobs"
)
os.environ["MANUSIFT_OBSIDIAN_VAULT_PATH"] = str(
    Path(
        os.environ.get(
            "MANUSIFT_PILOT_VAULT",
            Path(__file__).resolve().parents[1]
            / "docs"
            / "s41565-025-02082-0",
        )
    )
    / "vault"
)


TRACE_ID = "e6f244000eac"


def main() -> None:
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    print(f"=== Settings ===")
    print(f"  workspace: {s.workspace_dir}")
    print(f"  has_anthropic: {s.has_anthropic}")
    print(f"  obsidian vault: {s.obsidian_vault_path}")
    print()

    job_dir = s.workspace_dir / TRACE_ID
    pdf = job_dir / "original.pdf"
    if not pdf.exists():
        print(f"ERROR: {pdf} not found.")
        return

    # 1. Re-parse
    # PDF
    # with
    # the
    # 8 XLSX
    # in
    # materials/.
    print("=== 1. PDF parse (with companion XLSX) ===")
    from manusift.ingest.pdf import parse_pdf

    t0 = time.time()
    doc = parse_pdf(
        pdf,
        trace_id=TRACE_ID,
        workspace_dir=s.workspace_dir,
    )
    elapsed = time.time() - t0
    print(f"  parse time: {elapsed:.1f}s")
    print(f"  tables found: {len(doc.tables)}")
    for t in doc.tables[:20]:
        print(
            f"    {t.table_id} kind={t.source_kind} "
            f"sheet={t.sheet_name!r} rows={len(t.rows)} "
            f"cols={len(t.headers)} src={Path(t.source_path).name}"
        )
    print()

    # 2. Run the
    # four
    # table-stat
    # detectors
    # directly.
    print("=== 2. Table-statistics detectors ===")
    from manusift.detectors.table_stats import (
        BenfordDetector,
        DuplicateRowDetector,
        OutlierDetector,
        RoundBiasDetector,
    )
    detectors = [
        BenfordDetector(),
        DuplicateRowDetector(),
        OutlierDetector(),
        RoundBiasDetector(),
    ]
    all_findings: list[tuple[str, object]] = []
    for det in detectors:
        t0 = time.time()
        result = det.run(doc)
        elapsed = time.time() - t0
        print(
            f"  {det.name}: {len(result.findings)} findings "
            f"({elapsed:.2f}s) ok={result.ok}"
        )
        all_findings.extend((det.name, f) for f in result.findings)

    # 3. Summarise.
    print()
    print("=== 3. Summary ===")
    print(f"  total findings: {len(all_findings)}")
    by_sev: dict[str, int] = {}
    for _, f in all_findings:
        sev = (
            f.severity.value if hasattr(f.severity, "value") else f.severity
            if hasattr(f.severity, "value")
            else f.severity
        )
        by_sev[sev] = by_sev.get(sev, 0) + 1
    for sev, n in sorted(by_sev.items()):
        print(f"    {sev}: {n}")

    # 4. Save to
    # disk.
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trace_id": TRACE_ID,
        "n_tables": len(doc.tables),
        "n_findings": len(all_findings),
        "by_severity": by_sev,
        "findings": [
            {
                "detector": det,
                "finding_id": f.finding_id,
                "severity": f.severity.value if hasattr(f.severity, "value") else f.severity,
                "title": f.title,
                "evidence": f.evidence[:500],
                "location": f.location,
            }
            for det, f in all_findings
        ],
    }
    out_path = out_dir / "pilot_xlsx_findings.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"=== Saved: {out_path} ===")

    # 5. Show
    # top
    # 5
    # findings.
    print()
    print("=== 5. Top findings ===")
    sev_order = {"high": 0, "medium": 1, "low": 2}
    sorted_findings = sorted(
        all_findings,
        key=lambda p: (
            sev_order.get(
                p[1].severity.value
                if hasattr(p[1].severity, "value")
                else p[1].severity,
                9,
            ),
            p[0],
        ),
    )
    for det, f in sorted_findings[:8]:
        sev = (
            f.severity.value if hasattr(f.severity, "value") else f.severity
            if hasattr(f.severity, "value")
            else f.severity
        )
        title = f.title[:80]
        print(f"  [{sev:6s}] {det:20s} {title}")


if __name__ == "__main__":
    main()