---
name: integrity-report
description: Generate a bilingual (en/zh) narrative integrity report by calling ManuSift tools and writing markdown rendered via render_report. Use when the user asks for a full report, 完整报告, or deep review deliverable.
---

# integrity-report

Produce a **narrative** integrity report for the ingested PDF (use the
active trace_id). This is a human-readable document following academic
integrity investigation conventions — not a `findings.json` dump.

The report is **bilingual**: default `en`; produce `zh` when the user
works in Chinese or asks for a Chinese report.

## Step 1 — Collect evidence (in this order)

1. `metadata` — PDF producer / creator / dates.
2. `list_findings` with no filter — full inventory, counts by severity.
3. `list_findings` filtered by `severity=high`; `read_finding` the top
   3-5 by hand.
4. If a knowledge base is configured, `search_vault` with 1-3 topical
   queries (DOI, first author, "editorial"); `read_note` best hit.
5. Optionally `extract_table_from_image` / `image_similarity_matrix`
   for figures needing closer inspection.

## Step 2 — Write the markdown

Use these exact section headings (renderer anchors — do not rephrase):

English (`language="en"`):

```markdown
# Integrity Report -- <DOI or filename>

**Generated:** <UTC ISO timestamp>
**Paper:** <title, authors, journal, year>
**Verdict (preliminary):** <**low concern** / **medium concern** / **high concern**>
**Total findings:** <int> (<high> high, <medium> medium, <low> low)

## 1. Executive Summary
## 2. Paper Under Review
## 3. Diagnostic Surface
## 4. Key Findings
## 5. Knowledge-Base Cross-References
## 6. Recommended Next Steps
## 7. Disclaimer
```

Chinese (`language="zh"`): title `完整性审查报告`, verdict one of
`**低关注**` / `**中关注**` / `**高关注**`, headings:
`## 1. 执行摘要` / `## 2. 论文概况` / `## 3. 诊断维度` /
`## 4. 关键发现` / `## 5. 知识库交叉引用` / `## 6. 建议的下一步` /
`## 7. 免责声明`.

Content rules:

* **1 Executive Summary** — 2-3 paragraphs (~200-300 words): concern
  level, top 3 signals with finding ids, one-sentence caveat that this
  is a screening signal, not a determination.
* **2 Paper Under Review** — DOI, citation, journal, dates (from
  `metadata`).
* **3 Diagnostic Surface** — which detector categories ran, findings
  per category.
* **4 Key Findings** — for each top high finding: finding_id, detector
  name, one paragraph, plus one sentence on what evidence would
  overturn it. Summarise the long tail ("an additional N
  medium-severity findings...") instead of enumerating.
* **5 Knowledge-Base Cross-References** — vault hits or the empty-state
  line ("No knowledge base configured." / "未配置知识库。").
* **6 Recommended Next Steps** — 3-5 concrete manual-review actions.
* **7 Disclaimer** — cautious phrasing; never "fraud" / "misconduct" /
  "fabricated" ("造假" / "学术不端" / "捏造"); use "warrants manual
  review" / "screening signal" ("建议人工复核" / "筛查信号").

Verdict keyword spelling matters (renderer colours the exact forms).
600-1500 words total. Markdown headings only; fenced code blocks for
quoted JSON; cite finding ids as `finding_<id>`.

## Step 3 — Render

Call `render_report(trace_id=..., markdown=...)` EXACTLY ONCE
(add `language="zh"` for Chinese). The tool saves report.md /
report.html (and PDF when available) under the job workspace and
returns absolute paths.

## Step 4 — Confirm

One-line confirmation with the absolute report.html path.

## Error handling

* `metadata` empty → note it in section 2 and continue.
* `list_findings` empty → verdict "low concern" / "低关注"; section 4
  becomes a one-paragraph "No integrity signals detected."
  ("未发现完整性异常信号。").
* `render_report` errors → report the error; suggest re-running after
  the underlying call succeeds.
