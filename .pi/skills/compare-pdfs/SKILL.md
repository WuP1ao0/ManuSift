---
name: compare-pdfs
description: Run ManuSift screening on two PDFs and produce a side-by-side comparison table. Use when the user wants to compare two papers for borrowed or duplicated content.
---

# compare-pdfs

Compare two PDFs side by side. Steps:

1. `ingest_from_path` each PDF separately → two trace_ids.
2. For each relevant detector family, run it on both papers and record
   the findings count by severity (low / medium / high).
3. Build a markdown table with the detectors as rows and the two
   papers as columns. Cell values are the count of `high` findings.
4. After the table, write 2-3 sentences flagging the largest
   asymmetries (a detector that fires on B but not A, or vice versa).

The user is typically trying to answer "did the candidate borrow from
the baseline?". Frame every observation as a screening signal that
warrants manual review, never as a verdict.
