"""Tests for the LLM-driven narrative report (R-audit, 2026-06).

Two layers:

  1. ``manusift.report.narrative`` -- the
     markdown-to-HTML/PDF renderer. Pure
     function tests; no LLM or PDF runtime
     required for the HTML half. The PDF half
     is best-effort (weasyprint is broken on
     Windows without GTK); tests skip if
     ``build_narrative_report_pdf`` raises
     ``WeasyprintNotInstalled``.

  2. ``manusift.tools.render.RenderReportTool``
     -- the LLM-facing tool. The tool takes
     the LLM's markdown and writes three files
     (``.md`` / ``.html`` / ``.pdf``) to the
     job's workspace. Tests verify that the
     files appear and that the JSON envelope
     includes the right paths.

The end-to-end "LLM writes a
report" flow is exercised in
``test_pilot_mock_e2e.py``
already; this file pins the
**plumbing** of the new
narrative path so regressions
get caught early.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from manusift.config import Settings
from manusift.contracts import JobState
from manusift.report import (
    build_narrative_report_html,
    save_narrative_report,
)
from manusift.tools.render import RenderReportTool
from manusift.tools.tool import ToolContext
from manusift.workspace import JobPaths


# ---------- shared fixtures ----------


SAMPLE_MD = """\
# Integrity Report -- 10.1038/s41565-025-02082-0

**Generated:** 2026-06-11
**Paper:** Test paper (Chen et al., 2026)
**Verdict (preliminary):** **medium concern**
**Total findings:** 42 (15 high, 17 medium, 10 low)

## 1. Executive Summary

This paper shows an unusually high duplicate-image
rate across pages 3, 5, and 7 of the same chart marker.
The pattern is consistent with shared template imagery
rather than fabricated data.

## 2. Paper Under Review

DOI: 10.1038/s41565-025-02082-0
Journal: Nature Nanotechnology

## 3. Diagnostic Surface

- image_dup: 15 findings
- image_forensics: 92 findings

## 4. Key Findings

### 4.1 Marker reuse across pages

finding_id `ac0cf53dd2d20f32` -- the same chart
marker appears on pages 3, 5, 7, 9 of the PDF.

## 5. Knowledge-Base Cross-References

No knowledge base configured.

## 6. Recommended Next Steps

- Compare the duplicated figures to the journal's
  template archive.

## 7. Disclaimer

This is a screening signal, not a determination.
"""


@pytest.fixture
def job_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JobPaths:
    """Point the global settings at a fresh tmp workspace
    and return the JobPaths for a synthetic job.

    The RenderReportTool reads ``Settings().workspace_dir``
    on every call so the test's tmp workspace takes
    effect immediately, no cache invalidation needed.
    """
    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs")
    )
    return JobPaths.for_trace("report-test", tmp_path / "jobs")


# ---------- 1. markdown -> HTML ----------


def test_narrative_html_extracts_title() -> None:
    """The first H1 becomes
    the <title> tag."""
    html = build_narrative_report_html(
        "# Hello World\n\nBody.\n"
    )
    assert "<title>Hello World</title>" in html


def test_narrative_html_renders_standard_markdown() -> None:
    """Headings, paragraphs,
    lists, bold, code
    blocks all render."""
    html = build_narrative_report_html(SAMPLE_MD)
    assert "<h1" in html
    assert "Integrity Report" in html
    assert "<h2" in html
    assert "Executive Summary" in html
    # Bullet list.
    assert "<li>image_dup" in html
    # Bold (the
    # verdict
    # keyword
    # is
    # wrapped
    # in
    # a
    # CSS
    # class).
    assert "medium concern" in html
    assert "verdict-medium" in html
    # Fenced code block.
    assert "<pre>" in html or "<code>" in html


def test_narrative_html_styles_verdict_keyword() -> None:
    """``**low|medium|high concern**`` in the
    meta paragraph is wrapped in a colored span
    so the CSS class fires."""
    html = build_narrative_report_html(
        "# X\n\nhigh concern\n"
    )
    # We need the
    # bold-wrapped
    # form for
    # the
    # regex
    # to match.
    html = build_narrative_report_html(
        "# X\n\n**high concern**\n"
    )
    assert 'class="verdict-high"' in html
    assert "high concern" in html


def test_narrative_html_footer_has_trace_id_and_timestamp() -> None:
    """The page footer
    echoes the trace id
    + a generated-at
    timestamp so the
    user can identify
    which run produced
    it."""
    html = build_narrative_report_html(
        "# X\n\nbody\n", trace_id="abc12345"
    )
    assert "abc12345" in html
    assert "generated:" in html


def test_narrative_html_no_title_falls_back() -> None:
    """If the markdown has
    no H1 the renderer
    does not crash; it
    uses a constant
    title."""
    html = build_narrative_report_html(
        "Just a paragraph, no heading.\n"
    )
    assert "ManuSift integrity report" in html


# ---------- 2. RenderReportTool ----------


def test_render_tool_writes_md_html_pdf(
    job_paths: JobPaths,
) -> None:
    """The tool writes
    ``report.md``,
    ``report.html``, and
    (best-effort)
    ``report.pdf`` to
    the job workspace,
    then returns a JSON
    envelope with the
    absolute paths."""
    # Ensure
    # the
    # job
    # dir
    # exists.
    job_paths.ensure()
    t = RenderReportTool()
    ctx = None  # The
    # tool
    # only
    # reads
    # from
    # the
    # global
    # settings
    # + JobPaths.
    result = t.execute(
        {
            "trace_id": "report-test",
            "markdown": SAMPLE_MD,
            "include_pdf": True,
        },
        ctx,
    )
    envelope = json.loads(result)
    md = Path(envelope["markdown_path"])
    html = Path(envelope["html_path"])
    assert md.exists()
    assert html.exists()
    # The
    # markdown
    # file
    # contains
    # exactly
    # what
    # we
    # passed
    # in.
    assert md.read_text(encoding="utf-8") == SAMPLE_MD
    # The
    # HTML
    # file
    # is
    # not
    # empty
    # and
    # contains
    # the
    # heading.
    html_text = html.read_text(encoding="utf-8")
    assert "Executive Summary" in html_text
    # Word
    # count
    # in
    # the
    # envelope
    # is
    # a
    # quick
    # sanity
    # check.
    assert envelope["word_count"] > 100


def test_render_tool_writes_structured_trace_and_evidence_assets(
    job_paths: JobPaths,
    tmp_path: Path,
) -> None:
    """The final report is a workspace bundle, not only
    a rendered HTML file: downstream review tools need
    stable JSON entry points and an evidence asset
    manifest beside the human-readable report.
    """
    job_paths.ensure()
    source_asset = tmp_path / "figure-panel.png"
    source_asset.write_bytes(b"fake-png")
    ctx = ToolContext(
        trace_id="report-test",
        current_pdf=str(tmp_path / "paper.pdf"),
        metadata={
            "pdf_path": str(tmp_path / "paper.pdf"),
            "data_sources": [
                {
                    "id": "raw_csv",
                    "path": str(tmp_path / "raw data.csv"),
                    "kind": "csv",
                }
            ],
            "tool_calls": [
                {"tool": "metadata", "ok": True, "duration_ms": 12},
                {"tool": "read_data_source", "ok": True, "duration_ms": 7},
            ],
            "evidence_assets": [
                {
                    "id": "fig-a",
                    "path": str(source_asset),
                    "kind": "image",
                }
            ],
        },
    )
    result = RenderReportTool().execute(
        {
            "trace_id": "report-test",
            "markdown": SAMPLE_MD,
            "include_pdf": False,
        },
        ctx,
    )
    envelope = json.loads(result)

    report_json = Path(envelope["report_json_path"])
    raw_trace = Path(envelope["raw_trace_path"])
    tool_summary = Path(envelope["tool_summary_path"])
    evidence_manifest = Path(envelope["evidence_manifest_path"])
    copied_asset = job_paths.output_dir / "evidence_assets" / source_asset.name

    assert report_json.exists()
    assert raw_trace.exists()
    assert tool_summary.exists()
    assert evidence_manifest.exists()
    assert copied_asset.exists()

    report_payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert report_payload["trace_id"] == "report-test"
    assert report_payload["paths"]["html"] == envelope["html_path"]
    assert report_payload["source_pdf"] == str(tmp_path / "paper.pdf")
    assert report_payload["data_sources"][0]["id"] == "raw_csv"

    trace_payload = json.loads(raw_trace.read_text(encoding="utf-8"))
    assert trace_payload["render_input"]["markdown_sha256"]
    assert "markdown" not in trace_payload["render_input"]
    assert trace_payload["context"]["metadata"]["pdf_path"].endswith("paper.pdf")

    summary_payload = json.loads(tool_summary.read_text(encoding="utf-8"))
    assert summary_payload["total_calls"] == 2
    assert summary_payload["counts_by_tool"] == {
        "metadata": 1,
        "read_data_source": 1,
    }

    manifest_payload = json.loads(evidence_manifest.read_text(encoding="utf-8"))
    assert manifest_payload["assets"][0]["copied_path"] == str(copied_asset)


def test_render_tool_missing_trace_id_returns_error(
    job_paths: JobPaths,
) -> None:
    """trace_id is required."""
    t = RenderReportTool()
    result = t.execute({"markdown": "# x\n"}, None)
    envelope = json.loads(result)
    assert "error" in envelope


def test_render_tool_missing_markdown_returns_error(
    job_paths: JobPaths,
) -> None:
    """markdown is required."""
    t = RenderReportTool()
    result = t.execute(
        {"trace_id": "report-test"}, None
    )
    envelope = json.loads(result)
    assert "error" in envelope


def test_render_tool_skip_pdf(
    job_paths: JobPaths,
) -> None:
    """When include_pdf is
    False the tool writes
    only .md + .html and
    the envelope shows
    pdf_path = null."""
    job_paths.ensure()
    t = RenderReportTool()
    result = t.execute(
        {
            "trace_id": "report-test",
            "markdown": "# x\n\nbody",
            "include_pdf": False,
        },
        None,
    )
    envelope = json.loads(result)
    assert envelope["pdf_path"] is None
    assert Path(envelope["markdown_path"]).exists()
    assert Path(envelope["html_path"]).exists()


def test_render_tool_describes_itself() -> None:
    """The LLM-facing
    description mentions
    the key sections so
    the LLM does not
    invent new section
    names."""
    t = RenderReportTool()
    d = t.description()
    assert "Executive Summary" in d
    assert "Key Findings" in d
    assert "Disclaimer" in d


def test_render_tool_description_is_html_first_and_not_mojibake() -> None:
    """The LLM-facing
    description should match
    the chat workflow's
    deliverable: a final HTML
    report. It must not carry
    mojibake Chinese examples,
    because those examples are
    copied into the model's
    tool-selection context."""
    t = RenderReportTool()
    d = t.description()
    assert "final HTML report" in d
    assert "HTML/PDF" not in d
    assert "\u59a4?" not in d
    assert "\u95b8?" not in d
    assert "\u5a11?" not in d
    assert "\u5a34?" not in d
    assert "\u951f?" not in d


def test_render_tool_input_schema_pins_required() -> None:
    """trace_id and markdown
    are both in the
    ``required`` list so
    the LLM cannot forget
    them."""
    t = RenderReportTool()
    s = t.input_schema()
    assert "trace_id" in s["properties"]
    assert "markdown" in s["properties"]
    assert set(s["required"]) == {
        "trace_id",
        "markdown",
    }


# ---------- 3. save_narrative_report directly ----------


def test_save_narrative_report_returns_paths(
    job_paths: JobPaths,
) -> None:
    """Direct invocation
    of the lower-level
    helper returns the
    same shape as the
    tool's JSON."""
    out = save_narrative_report(
        SAMPLE_MD,
        out_dir=job_paths.root,
        trace_id="report-test",
    )
    assert "md" in out
    assert "html" in out
    assert "pdf" in out
    assert Path(out["md"]).exists()
    assert Path(out["html"]).exists()
    # pdf
    # may
    # be
    # None
    # on
    # Windows
    # without
    # GTK;
    # if
    # it
    # is
    # set,
    # the
    # file
    # must
    # exist.
    if out["pdf"] is not None:
        assert Path(out["pdf"]).exists()


# ---------- 5. i18n: Chinese report ----------


CHINESE_SAMPLE_MD = """\
# 完整性审查报告 - 测试论文

**生成时间:** 2026-06-11
**论文信息:** 测试用 OA 治疗纳米药物论文 (Chen et al., 2026)
**初步判定:** **高关注**
**发现总数:** 15 (高: 15)

## 1. 执行摘要

这是一份筛查信号报告，而非最终判定。检测到同一页面存在 15 张完全相同的图像
(pHash `ac0cf53dd2d20f32`)，提示可能存在图像复用。

## 2. 论文概况

DOI: 10.1038/s41565-025-02082-0
期刊: 自然-纳米技术

## 3. 诊断维度

- image_dup: 15 项
- image_forensics: 92 项

## 4. 关键发现

### 4.1 同一页面 15 张相同图像 (高)

Page 3 含有 6 张相同的图像 (p4, p6, p8, p10, p23, p25)，pHash 全部相同。

## 5. 知识库交叉引用

未配置知识库。

## 6. 建议的下一步

- 人工比对第 3 页的图像面板。

## 7. 免责声明

本报告为自动化筛查信号，而非学术不端的判定。"""


def test_zh_html_lang_attribute() -> None:
    """The <html lang> tag
    flips to ``zh-Hans``
    when ``language="zh"``
    so screen readers +
    browser font
    selection work."""
    html = build_narrative_report_html(
        CHINESE_SAMPLE_MD, language="zh"
    )
    assert '<html lang="zh-Hans">' in html


def test_zh_cjk_font_fallback() -> None:
    """The CSS body font
    includes a CJK
    fallback chain so
    the user's browser
    can find a font on
    any platform (macOS,
    Windows, Linux,
    without CJK
    installed)."""
    html = build_narrative_report_html(
        CHINESE_SAMPLE_MD, language="zh"
    )
    assert "PingFang SC" in html
    assert "Microsoft YaHei" in html
    assert "Noto Sans CJK" in html


def test_zh_verdict_keyword_styled() -> None:
    """Chinese high / medium /
    low attention labels in the
    markdown body become
    coloured ``<strong>``
    spans via the
    same CSS classes
    used for English."""
    for level, expected_class in (
        ("\u9ad8", "verdict-high"),
        ("\u4e2d", "verdict-medium"),
        ("\u4f4e", "verdict-low"),
    ):
        md = f"# t\n\n**{level}\u5173\u6ce8**\n\nbody"
        html = build_narrative_report_html(
            md, language="zh"
        )
        assert expected_class in html, (
            f"{level}\u5173\u6ce8 did not produce "
            f"{expected_class}; got:\n{html[:400]}"
        )


def test_zh_footer_labels() -> None:
    """The page footer
    shows Chinese labels
    (追踪 ID / 生成时间)
    instead of
    ``trace_id`` /
    ``generated`` when
    ``language="zh"``."""
    html = build_narrative_report_html(
        CHINESE_SAMPLE_MD,
        trace_id="zh-test-001",
        language="zh",
    )
    assert "追踪 ID" in html
    assert "生成时间" in html
    # The English
    # footer words
    # should NOT appear
    # in the Chinese
    # footer. (We check
    # only the footer
    # line; the body
    # can contain
    # English words
    # like DOI if the
    # LLM chose to keep
    # them.)
    # Find the
    # <div class="meta">
    # block.
    import re
    m = re.search(
        r'<div class="meta">(.*?)</div>', html, re.DOTALL
    )
    assert m
    footer = m.group(1)
    assert "trace_id" not in footer
    assert "generated" not in footer


def test_zh_save_uses_zh_suffix() -> None:
    """``save_narrative_report(language="zh")`` writes
    ``report.zh.md`` +
    ``report.zh.html``,
    NOT ``report.md`` /
    ``report.html``, so
    the two locales
    coexist."""
    out = save_narrative_report(
        CHINESE_SAMPLE_MD,
        out_dir=job_paths_for_zh().root,
        trace_id="zh-test",
        language="zh",
    )
    md = Path(out["md"])
    html = Path(out["html"])
    assert md.name == "report.zh.md"
    assert html.name == "report.zh.html"
    assert md.exists()
    assert html.exists()
    # And the
    # non-zh files
    # are NOT
    # created.
    root = md.parent
    assert not (root / "report.md").exists()
    assert not (root / "report.html").exists()


def test_en_save_does_not_use_zh_suffix() -> None:
    """The English
    fallback still
    writes ``report.md``
    (no suffix) so
    callers that don't
    pass a language
    keep the original
    contract."""
    out = save_narrative_report(
        SAMPLE_MD,
        out_dir=job_paths_for_zh().root,
        trace_id="en-test",
    )
    md = Path(out["md"])
    assert md.name == "report.md"


def test_zh_endpoint_serves_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Chinese
    ``/report.zh.md``
    endpoint returns
    the Chinese markdown
    with the right
    Content-Type."""
    from starlette.testclient import TestClient
    from manusift.web.app import create_app

    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs")
    )
    paths = JobPaths.for_trace(
        "zh-endpoint-test", tmp_path / "jobs"
    )
    paths.ensure()
    (paths.output_dir / "report.zh.md").write_text(
        CHINESE_SAMPLE_MD, encoding="utf-8"
    )
    app = create_app()
    with TestClient(app) as client:
        r = client.get(
            "/api/jobs/zh-endpoint-test/report.zh.md"
        )
        assert r.status_code == 200
        assert "完整性审查报告" in r.text
        assert "高关注" in r.text


def test_zh_endpoint_404_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If no Chinese
    report has been
    generated, the
    Chinese endpoint
    returns 404 (not
    200 with the
    English content)."""
    from starlette.testclient import TestClient
    from manusift.web.app import create_app

    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs")
    )
    paths = JobPaths.for_trace(
        "no-zh-yet", tmp_path / "jobs"
    )
    paths.ensure()
    app = create_app()
    with TestClient(app) as client:
        r = client.get(
            "/api/jobs/no-zh-yet/report.zh.md"
        )
        assert r.status_code == 404


def test_render_tool_chinese(
    job_paths: JobPaths,
) -> None:
    """The
    ``RenderReportTool``
    routes Chinese
    reports to
    ``report.zh.md``
    and includes
    ``language: "zh"``
    in its JSON
    envelope."""
    job_paths.ensure()
    t = RenderReportTool()
    result = t.execute(
        {
            "trace_id": "report-test",
            "markdown": CHINESE_SAMPLE_MD,
            "language": "zh",
            "include_pdf": False,
        },
        None,
    )
    envelope = json.loads(result)
    assert envelope["language"] == "zh"
    assert envelope["markdown_path"].endswith("report.zh.md")
    assert envelope["html_path"].endswith("report.zh.html")
    assert Path(envelope["markdown_path"]).exists()
    assert Path(envelope["html_path"]).exists()


def test_render_tool_unknown_language_falls_back_to_english(
    job_paths: JobPaths,
) -> None:
    """``language="klingon"``
    is silently coerced
    to ``"en"`` rather
    than 400-erroring,
    so old callers keep
    working."""
    job_paths.ensure()
    t = RenderReportTool()
    result = t.execute(
        {
            "trace_id": "report-test",
            "markdown": "# t\n\nbody",
            "language": "klingon",
            "include_pdf": False,
        },
        None,
    )
    envelope = json.loads(result)
    assert envelope["language"] == "en"
    assert envelope["markdown_path"].endswith("report.md")


def job_paths_for_zh() -> JobPaths:
    """Per-test fixture for
    the Chinese
    save-tests: a fresh
    JobPaths rooted at a
    tmp dir so the
    suffix-test does not
    collide with the
    English-job fixture."""
    import tempfile

    return JobPaths.for_trace(
        "zh-test", Path(tempfile.mkdtemp()) / "jobs"
    )


# ---------- 4. markdown endpoint (sanity) ----------


def test_report_md_endpoint_404_before_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTTP endpoint
    returns 404 if the
    LLM has not yet
    written ``report.md``
    -- only the
    flat-dump ``report.html``
    exists from the
    pipeline."""
    from starlette.testclient import TestClient
    from manusift.web.app import create_app

    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs")
    )
    # JobPaths
    # for
    # a
    # tid
    # that
    # has
    # nothing
    # on
    # disk
    # yet.
    JobPaths.for_trace(
        "no-such-tid", tmp_path / "jobs"
    ).ensure()
    # Drop
    # report.md
    # (it
    # wouldn't
    # exist
    # anyway
    # but
    # be
    # explicit).
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/no-such-tid/report.md")
        assert r.status_code == 404


def test_report_endpoint_serves_html_after_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the pipeline
    runs, the
    ``/api/jobs/<tid>/report``
    endpoint serves the
    HTML content (whether
    it is the flat-dump
    or the LLM-written
    narrative -- both
    are written to the
    same path)."""
    from starlette.testclient import TestClient
    from manusift.web.app import create_app

    monkeypatch.setenv(
        "MANUSIFT_WORKSPACE_DIR", str(tmp_path / "jobs")
    )
    paths = JobPaths.for_trace(
        "has-report", tmp_path / "jobs"
    )
    paths.ensure()
    paths.report_html.write_text(
        "<html><body>Hello</body></html>",
        encoding="utf-8",
    )
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/jobs/has-report/report")
        assert r.status_code == 200
        assert "Hello" in r.text
