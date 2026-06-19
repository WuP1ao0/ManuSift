"""Tests for the direct-fs tools (R-audit 2026-06-10).

Before this audit the
user had to manually
run ``manusift ingest
<path>`` or click ``/load
<path>`` in the TUI before
the agent could see a PDF.
The user reported this as
a UX gap versus Claude
Code: "I gave you the
file path, why can't you
just read it?".

This file pins the new
contracts:

  * ``read_file`` returns
    the text content of a
    file at an absolute
    path; rejects PDFs,
    rejects relative
    paths, rejects files
    larger than 200 KB.
  * ``ingest_from_path``
    parses a PDF and
    returns a new
    ``trace_id``; rejects
    non-PDFs, rejects
    files without the
    %PDF- magic number.
  * ``list_dir`` lists a
    directory's contents
    (skipping dotfiles).
  * All three are gated
    by
    ``MANUSIFT_ALLOW_DIRECT_FS``
    (default ``True``);
    set it to ``False`` to
    disable.
  * The tools are
    registered in the
    global tool registry.
"""
from __future__ import annotations

import json
import os
import zipfile

os.chdir(r"C:/Users/22509/Desktop/ManuSift1")


# ---------- 1. read_file ----------


def test_read_file_returns_text_content(tmp_path) -> None:
    """``read_file`` returns
    the text content of a
    file at an absolute
    path."""
    from manusift.tools.direct_fs import ReadFileTool
    from manusift.tools.tool import ToolContext

    sample = tmp_path / "notes.md"
    sample.write_text(
        "# Hello\n\nThis is a test.\n", encoding="utf-8"
    )
    tool = ReadFileTool()
    out = json.loads(
        tool.execute(
            {"path": str(sample)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert "Hello" in out["content"]
    assert "This is a test." in out["content"]


def test_read_file_rejects_relative_path(tmp_path) -> None:
    """Relative paths are
    rejected (defence in
    depth against cwd-
    relative traversal)."""
    from manusift.tools.direct_fs import ReadFileTool
    from manusift.tools.tool import ToolContext

    tool = ReadFileTool()
    out = json.loads(
        tool.execute(
            {"path": "relative/path.md"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "absolute" in out["error"]


def test_read_file_rejects_pdf(tmp_path) -> None:
    """PDFs are rejected
    with a helpful pointer
    to ``ingest_from_path``."""
    from manusift.tools.direct_fs import ReadFileTool
    from manusift.tools.tool import ToolContext

    sample = tmp_path / "paper.pdf"
    sample.write_bytes(b"%PDF-1.4 fake")
    tool = ReadFileTool()
    out = json.loads(
        tool.execute(
            {"path": str(sample)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "ingest_from_path" in out["error"]


def test_read_file_rejects_oversize(tmp_path) -> None:
    """Files larger than
    200 KB are rejected."""
    from manusift.tools.direct_fs import ReadFileTool
    from manusift.tools.tool import ToolContext

    sample = tmp_path / "huge.txt"
    sample.write_bytes(b"x" * 300_000)
    tool = ReadFileTool()
    out = json.loads(
        tool.execute(
            {"path": str(sample)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "200" in out["error"] or "cap" in out["error"]


# ---------- 2. ingest_from_path ----------


def test_ingest_from_path_rejects_non_pdf(tmp_path) -> None:
    """Non-PDF files are
    rejected (with a
    pointer to
    ``read_file``)."""
    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    sample = tmp_path / "data.csv"
    sample.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    tool = IngestFromPathTool()
    out = json.loads(
        tool.execute(
            {"path": str(sample)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "read_file" in out["error"]


def test_ingest_from_path_rejects_bad_magic(tmp_path) -> None:
    """Files ending in
    .pdf but with a wrong
    magic number are
    rejected."""
    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    sample = tmp_path / "fake.pdf"
    sample.write_bytes(b"NOT A PDF\n" + b"x" * 1000)
    tool = IngestFromPathTool()
    out = json.loads(
        tool.execute(
            {"path": str(sample)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "magic" in out["error"].lower()


def test_ingest_from_path_happy_path(tmp_path) -> None:
    """A real PDF at the
    given path is parsed
    and a fresh trace_id
    is returned. We use
    a minimal valid PDF
    fixture to keep the
    test offline."""
    import fitz
    # Build a tiny PDF
    # in-memory so we do
    # not depend on the
    # test fixtures
    # dir.
    pdf_path = tmp_path / "tiny.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (50, 50),
        "Hello PDF",
        fontsize=12,
    )
    doc.save(str(pdf_path))
    doc.close()
    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    tool = IngestFromPathTool()
    out = json.loads(
        tool.execute(
            {"path": str(pdf_path)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True, out
    assert "trace_id" in out
    assert len(out["trace_id"]) > 5
    assert "next_step" in out
    # The new
    # trace_id
    # should
    # be
    # different
    # from
    # the
    # input
    # ctx.
    assert out["trace_id"] != "t"


def test_ingest_from_path_reports_data_sources(
    tmp_path, monkeypatch
) -> None:
    """The ingest summary tells the LLM when companion
    data sources were parsed, so chat-tui can route to
    table/data-source tools after a user pastes a PDF path."""
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

    from manusift.contracts import ExtractedTable, ParsedDoc
    from manusift.ingest import pdf as pdf_mod

    def _fake_parse_pdf(path, trace_id, workspace_dir=None):
        return ParsedDoc(
            trace_id=trace_id,
            source_path=str(path),
            text_blocks=[],
            images=[],
            metadata={"page_count": 1},
            tables=[
                ExtractedTable(
                    table_id="source-fig1",
                    source_kind="xlsx",
                    source_path=str(tmp_path / "Source_Data_Fig1.xlsx"),
                    sheet_name="Fig. 1",
                    source_index=0,
                    headers=["group", "value"],
                    rows=[["A", "1"], ["B", "2"]],
                )
            ],
        )

    monkeypatch.setattr(pdf_mod, "parse_pdf", _fake_parse_pdf)

    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    out = json.loads(
        IngestFromPathTool().execute(
            {"path": str(pdf_path)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["data_source_count"] == 1
    assert out["data_sources"][0]["table_id"] == "source-fig1"
    assert out["data_sources"][0]["source_kind"] == "xlsx"
    assert out["data_sources"][0]["row_count"] == 2
    assert "table_benford" in out["next_step"]


def test_ingest_from_path_accepts_separate_data_paths(
    tmp_path, monkeypatch
) -> None:
    """A user may paste a PDF
    path and a separate
    original-data folder.
    ``data_paths`` should be
    copied into the job's
    materials folder before
    parsing so the ingest
    summary exposes those
    tables as data sources."""
    import fitz

    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    paper_dir = tmp_path / "paper"
    data_dir = tmp_path / "raw_data"
    paper_dir.mkdir()
    data_dir.mkdir()
    pdf = paper_dir / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Paper with separate source data.")
    doc.save(str(pdf))
    doc.close()
    csv_path = data_dir / "source.csv"
    csv_path.write_text(
        "group,value\nA,1\nB,2\nB,2\n",
        encoding="utf-8",
    )

    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    out = json.loads(
        IngestFromPathTool().execute(
            {
                "path": str(pdf),
                "data_paths": [str(data_dir)],
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["data_source_count"] >= 1
    assert any(
        ds["source_path"].endswith("source.csv")
        for ds in out["data_sources"]
    )
    copied = (
        tmp_path
        / "ws"
        / out["trace_id"]
        / "materials"
        / "source.csv"
    )
    assert copied.exists()


def test_ingest_from_path_accepts_zip_data_paths(
    tmp_path, monkeypatch
) -> None:
    """A supplementary ZIP passed as ``data_paths`` should
    become normal parsed data sources, not an opaque archive
    that table tools cannot read.
    """
    import fitz

    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    pdf = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((40, 40), "Supplementary ZIP test")
    doc.save(str(pdf))
    doc.close()

    archive = tmp_path / "supplementary.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "source_data/fig1.csv",
            "group,value\nA,1\nB,2\n",
        )

    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    out = json.loads(
        IngestFromPathTool().execute(
            {
                "path": str(pdf),
                "data_paths": [str(archive)],
            },
            ToolContext(trace_id="t"),
        )
    )

    assert out["ok"] is True, out
    assert out["data_source_count"] >= 1
    assert any(
        ds["source_kind"] == "csv"
        and "fig1.csv" in ds["source_path"]
        for ds in out["data_sources"]
    )


def test_ingest_from_path_reports_data_copy_failures(
    tmp_path, monkeypatch
) -> None:
    """If a companion data file cannot be copied into the
    job materials directory, the LLM should see that failure
    in ``ignored_data_paths`` instead of silently losing the
    source data.
    """
    import fitz

    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    paper_dir = tmp_path / "paper"
    data_dir = tmp_path / "raw_data"
    paper_dir.mkdir()
    data_dir.mkdir()
    pdf = paper_dir / "paper.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Paper with locked data.")
    doc.save(str(pdf))
    doc.close()
    csv_path = data_dir / "locked.csv"
    csv_path.write_text("group,value\nA,1\n", encoding="utf-8")

    from manusift.tools import direct_fs
    real_copy2 = direct_fs.shutil.copy2

    def _copy2(src, dst, *args, **kwargs):
        if str(src).endswith("locked.csv"):
            raise PermissionError("file is locked")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(direct_fs.shutil, "copy2", _copy2)

    from manusift.tools.direct_fs import IngestFromPathTool
    from manusift.tools.tool import ToolContext

    out = json.loads(
        IngestFromPathTool().execute(
            {
                "path": str(pdf),
                "data_paths": [str(data_dir)],
            },
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    assert out["ignored_data_paths"] == [
        {
            "path": str(csv_path),
            "reason": "copy failed: file is locked",
        }
    ]


# ---------- 3. list_dir ----------


def test_list_dir_returns_entries(tmp_path) -> None:
    """``list_dir`` returns
    a JSON list of
    ``{name, type, size}``
    entries."""
    from manusift.tools.direct_fs import ListDirTool
    from manusift.tools.tool import ToolContext

    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    (tmp_path / "b.md").write_text("md", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / ".hidden").write_text("h", encoding="utf-8")
    tool = ListDirTool()
    out = json.loads(
        tool.execute(
            {"path": str(tmp_path)},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is True
    names = {e["name"] for e in out["entries"]}
    assert "a.txt" in names
    assert "b.md" in names
    assert "subdir" in names
    # Hidden
    # files
    # are
    # skipped.
    assert ".hidden" not in names


def test_list_dir_rejects_relative_path(tmp_path) -> None:
    """Relative paths are
    rejected (consistent
    with ``read_file`` /
    ``ingest_from_path``)."""
    from manusift.tools.direct_fs import ListDirTool
    from manusift.tools.tool import ToolContext

    tool = ListDirTool()
    out = json.loads(
        tool.execute(
            {"path": "relative"},
            ToolContext(trace_id="t"),
        )
    )
    assert out["ok"] is False
    assert "absolute" in out["error"]


# ---------- 4. allow_direct_fs gate ----------


def test_allow_direct_fs_gate_disables_all_three(tmp_path) -> None:
    """When
    ``MANUSIFT_ALLOW_DIRECT_FS=False``
    all three tools
    refuse to operate."""
    import importlib

    from manusift import config as _config
    from manusift.config import get_settings

    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    s.__class__.model_config["env_prefix"] = "MANUSIFT_"
    # Patch
    # the
    # setting
    # for
    # this
    # test.
    monkey = type("M", (), {})()
    import os as _os
    _os.environ["MANUSIFT_ALLOW_DIRECT_FS"] = "false"
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.tools.direct_fs import (
        IngestFromPathTool,
        ListDirTool,
        ReadFileTool,
    )
    from manusift.tools.tool import ToolContext
    sample = tmp_path / "x.txt"
    sample.write_text("hi", encoding="utf-8")
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 1000)
    for tool in (ReadFileTool(), IngestFromPathTool(), ListDirTool()):
        out = json.loads(
            tool.execute(
                {"path": str(sample)},
                ToolContext(trace_id="t"),
            )
        )
        assert out["ok"] is False
        assert "disabled" in out["error"]
    # Restore
    # the
    # default.
    _os.environ.pop("MANUSIFT_ALLOW_DIRECT_FS", None)
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()


# ---------- 5. Tool registration ----------


def test_direct_fs_tools_registered() -> None:
    """The 3 direct-fs tools
    are in the global
    registry."""
    from manusift.tools import iter_registered_tools

    names = {t.name for t in iter_registered_tools()}
    assert "read_file" in names
    assert "ingest_from_path" in names
    assert "list_dir" in names


# ---------- 6. Settings ----------


def test_allow_direct_fs_default_true() -> None:
    """The
    ``allow_direct_fs``
    setting defaults to
    ``True`` so users do
    not have to opt in."""
    import os as _os
    _os.environ.pop("MANUSIFT_ALLOW_DIRECT_FS", None)
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    s = get_settings()
    assert s.allow_direct_fs is True
