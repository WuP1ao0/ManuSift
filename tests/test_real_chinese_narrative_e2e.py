"""E2E: real LLM writes a Chinese narrative report end-to-end.

Same flow as
``test_real_narrative_e2e.py``
but the user prompt asks
for Chinese (``language="zh"``).
Verifies that:

  * the LLM picks the
    Chinese section
    names from the
    skill (执行摘要,
    关键发现,
    知识库交叉引用,
    免责声明)
  * the verdict
    keyword is
    ``高关注`` /
    ``中关注`` /
    ``低关注`` (not
    ``high concern``)
  * the LLM actually
    passes ``language="zh"``
    to ``render_report``
  * the Chinese
    files land at
    ``report.zh.md`` /
    ``report.zh.html``
  * the English files
    (``report.md`` /
    ``report.html``)
    are NOT overwritten
  * the Chinese HTML
    carries
    ``<html lang="zh-Hans">``
    + a CJK font
    fallback chain

Run with::

  .venv/Scripts/python.exe
    tests/test_real_chinese_narrative_e2e.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault(
    "MANUSIFT_WORKSPACE_DIR",
    str(Path(__file__).resolve().parents[1] / "data" / "pilot_jobs"),
)
os.environ.setdefault(
    "MANUSIFT_OBSIDIAN_VAULT_PATH",
    str(
        Path(
            os.environ.get(
                "MANUSIFT_PILOT_VAULT",
                Path(__file__).resolve().parents[1]
                / "docs"
                / "s41565-025-02082-0",
            )
        )
        / "vault"
    ),
)


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

    if not s.has_anthropic:
        print("ERROR: no ANTHROPIC_API_KEY in .env.")
        return

    from manusift.tools import (
        iter_registered_tools,
        ToolContext,
    )
    from manusift.llm.client import AnthropicLLM
    tools = list(iter_registered_tools())
    print(f"=== {len(tools)} tools registered ===")
    print()

    # Reuse the
    # same pilot
    # trace
    # id (we
    # already
    # have
    # an
    # English
    # report
    # there).
    trace_id = "e6f244000eac"
    ctx = ToolContext(trace_id=trace_id, current_pdf=None)
    llm = AnthropicLLM(s)

    user_prompt = (
        "请使用 /skill integrity_report 工作流,"
        "并通过将 language 参数设为 \"zh\" 来生成"
        "一份中文版的完整性审查报告。报告针对当前"
        "绑定的 PDF (trace_id="
        + trace_id
        + ")。请按步骤操作: 调用 list_findings"
        " 获取发现列表, 调用 read_finding 查看"
        "前 3 个高优先级发现的详情, 调用 "
        "search_vault 和 read_note 来交叉引用本地"
        "知识库中匹配的案例笔记, 最后调用 "
        "render_report 并传入 language=\"zh\""
        " 参数和完整的中文 markdown。markdown"
        " 应当遵循7 章节结构 (执行摘要, 论文概况, "
        "诊断维度, 关键发现, 知识库交叉引用, "
        "建议的下一步, 免责声明),使用中文 verdict "
        "关键词 (**高关注**/**中关注**/**低关注**)。"
        "保持谨慎措辞: 这只是筛查信号, 而非最终"
        "判定。"
    )

    from manusift.agent import AgentLoop
    loop = AgentLoop(client=llm, tools=tools, ctx=ctx)
    print(f"=== Agent loop running ({len(user_prompt)} chars prompt, zh) ===")
    chunks = []
    tool_calls_made = []
    final_text = ""
    t0 = time.time()
    for resp in loop.run_stream(user_prompt):
        chunks.append(resp)
        for tc in resp.tool_calls:
            tool_calls_made.append({
                "name": tc.get("name"),
                "input": tc.get("input", {}),
            })
        final_text = resp.text
    elapsed = time.time() - t0
    print(f"  elapsed: {elapsed:.1f}s, chunks: {len(chunks)}, tool calls: {len(tool_calls_made)}")
    print()
    print(f"=== Tool calls ({len(tool_calls_made)}) ===")
    for i, tc in enumerate(tool_calls_made):
        inp = json.dumps(tc['input'], ensure_ascii=False)
        print(f"  [{i+1}] {tc['name']!r}  input={inp[:100]}")

    # Did the
    # LLM
    # call
    # render_report
    # with
    # language="zh"?
    render_calls = [
        tc for tc in tool_calls_made
        if tc["name"] == "render_report"
    ]
    if render_calls:
        print()
        print(f"=== render_report was called {len(render_calls)} time(s) ===")
        last = render_calls[-1]
        lang = last["input"].get("language", "(default)")
        md = last["input"].get("markdown", "")
        print(f"  last call language: {lang!r}")
        print(f"  last call markdown length: {len(md)}")
        print(f"  first 400 chars:")
        print(md[:400])

    # Save log
    out_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pilot_chinese_narrative_log.json").write_text(
        json.dumps({
            "trace_id": trace_id,
            "elapsed": elapsed,
            "tool_calls": tool_calls_made,
            "chunks": len(chunks),
            "final_text": final_text,
            "render_report_called": len(render_calls),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"=== Saved log: {out_dir / 'pilot_chinese_narrative_log.json'} ===")

    # Inspect
    # the
    # job
    # dir.
    job_dir = Path(s.workspace_dir) / trace_id
    print(f"=== Job dir: {job_dir} ===")
    files = sorted(job_dir.iterdir())
    for f in files:
        if f.is_file():
            print(f"  {f.name}: {f.stat().st_size} bytes")

    # Verify
    # the
    # Chinese
    # files
    # exist
    # and
    # carry
    # the
    # right
    # HTML.
    zh_md = job_dir / "report.zh.md"
    zh_html = job_dir / "report.zh.html"
    en_md = job_dir / "report.md"
    print()
    print(f"=== Verification ===")
    if zh_md.exists():
        md_text = zh_md.read_text(encoding="utf-8")
        print(f"  report.zh.md exists: {len(md_text)} chars")
        print(f"    contains 执行摘要: {'执行摘要' in md_text}")
        print(f"    contains 关键发现: {'关键发现' in md_text}")
        print(f"    contains 知识库交叉引用: {'知识库交叉引用' in md_text}")
        print(f"    contains 免责声明: {'免责声明' in md_text}")
        print(f"    contains verdict 高关注: {'**高关注**' in md_text or '高关注' in md_text}")
    else:
        print("  report.zh.md MISSING")
    if zh_html.exists():
        html = zh_html.read_text(encoding="utf-8")
        print(f"  report.zh.html exists: {len(html)} chars")
        has_lang = '<html lang="zh-Hans">' in html
        has_font = 'PingFang SC' in html
        print(f"    contains <html lang zh-Hans: {has_lang}")
        print(f"    contains PingFang SC: {has_font}")
    else:
        print("  report.zh.html MISSING")
    if en_md.exists():
        print(f"  report.md (English) preserved: {en_md.stat().st_size} bytes")
    else:
        print("  report.md (English) MISSING")


if __name__ == "__main__":
    main()
