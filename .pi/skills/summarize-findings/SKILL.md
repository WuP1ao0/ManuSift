---
name: summarize-findings
description: Read the latest findings.json for a job and write a one-paragraph user-facing summary. Use when the user asks for a quick plain-language summary of an existing screen.
---

# summarize-findings

The analysis has already run. Locate the job's `findings.json`
(`list_findings(trace_id)` or the job workspace `output/findings.json`),
group by detector, and write a single paragraph the user can paste
into a referee report.

Constraints:

* Cite the detector name in **bold** the first time each one is
  mentioned (e.g. "**metadata** flagged...").
* Overall verdict is one of: "no strong signal found" /
  "needs human review" / "multiple high-concern signals" — pick by the
  count of `high` findings (0 / 1-2 / 3+). Never use absolute words
  like "clean" or "fabricated".
* Keep the paragraph under 200 words.
* Do not invent findings. If `findings.json` is empty or missing, say
  so and stop.
