"""Tests for the T5 numeric-table extractor
(R-2026-06-15).

Covers:

  * ``_row_from_sentence`` -- per-sentence
    regex matching for n / mean / SD /
    p_value / pct / t / F / chi2 / r
  * ``extract_tables_from_text`` -- the
    public API that turns ``TextBlock``s
    into ``ExtractedTable`` records
  * ``extract_tables_from_pdf_path`` -- the
    end-to-end entry point that opens a PDF
  * Defensive tolerance: empty input,
    None input, garbage text
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from manusift.contracts import TextBlock  # noqa: E402
from manusift.ingest.table_extractor import (  # noqa: E402
    _row_from_sentence,
    _split_sentences,
    extract_tables_from_pdf_path,
    extract_tables_from_text,
)


# ---- _row_from_sentence ----


def test_row_extracts_n_mean_sd_pct_pvalue() -> None:
    s = "Group A had n=20 patients, mean=4.20 (SD=0.5), p<0.05."
    r = _row_from_sentence(s, page=1)
    assert r is not None
    assert r.n == "20"
    assert r.mean == "4.20"
    assert r.sd == "0.5"
    assert r.p_value == "0.05"


def test_row_extracts_percentage() -> None:
    s = "Response rate was 95.0% (n=40)."
    r = _row_from_sentence(s, page=1)
    assert r is not None
    assert r.n == "40"
    assert r.pct == "95.0"


def test_row_extracts_t_F_chi2() -> None:
    s = "t(20) = 2.45, F(2,18) = 3.4, chi-square = 5.6"
    r = _row_from_sentence(s, page=1)
    assert r is not None
    assert r.t == "2.45"
    assert r.F == "3.4"
    assert r.chi2 == "5.6"


def test_row_extracts_correlation() -> None:
    s = "Pearson r=0.42, p=0.03"
    r = _row_from_sentence(s, page=1)
    assert r is not None
    assert r.r == "0.42"
    assert r.p_value == "0.03"


def test_row_returns_none_for_garbage() -> None:
    s = "This is just a regular sentence with no stats."
    assert _row_from_sentence(s, page=1) is None


def test_row_returns_none_for_empty() -> None:
    assert _row_from_sentence("", page=1) is None


def test_row_handles_capital_letters() -> None:
    """The pattern must be case-insensitive."""
    s = "N=100, M=4.20, SD=0.5, P<0.05"
    r = _row_from_sentence(s, page=1)
    assert r is not None
    assert r.n == "100"
    assert r.mean == "4.20"
    assert r.sd == "0.5"
    assert r.p_value == "0.05"


# ---- _split_sentences ----


def test_split_sentences_basic() -> None:
    text = "First sentence. Second sentence. Third sentence."
    out = _split_sentences(text)
    assert len(out) == 3
    assert "First" in out[0]
    assert "Second" in out[1]
    assert "Third" in out[2]


def test_split_sentences_handles_no_end_punct() -> None:
    """A paragraph with no terminating period
    is treated as one sentence."""
    text = "no period here"
    out = _split_sentences(text)
    assert len(out) == 1
    assert out[0] == "no period here"


def test_split_sentences_handles_empty() -> None:
    assert _split_sentences("") == []


# ---- extract_tables_from_text ----


def test_extract_tables_from_text_no_input() -> None:
    assert extract_tables_from_text([]) == []


def test_extract_tables_from_text_no_stat() -> None:
    b = TextBlock(
        page=1,
        bbox=(0, 0, 100, 100),
        text="The study protocol was approved by the IRB.",
    )
    assert extract_tables_from_text([b]) == []


def test_extract_tables_from_text_builds_one_table_per_page() -> None:
    b1 = TextBlock(
        page=2,
        bbox=(0, 0, 100, 100),
        text="A total of N=100 patients were randomised. "
        "Mean age 45.6 (SD 12.3). p<0.001.",
    )
    b2 = TextBlock(
        page=3,
        bbox=(0, 0, 100, 100),
        text="Treatment effect was 23.4% vs 12.3%.",
    )
    tables = extract_tables_from_text([b1, b2])
    assert len(tables) == 2
    # Page 2 has n, mean, sd, p_value
    assert "n" in tables[0].headers
    assert "mean" in tables[0].headers
    # Page 3 has pct
    assert "pct" in tables[1].headers


def test_extract_tables_from_text_groups_by_page() -> None:
    """Multiple TextBlocks on the same page
    should produce ONE table whose rows
    include all of them."""
    b1 = TextBlock(
        page=4,
        bbox=(0, 0, 100, 100),
        text="Group 1: n=10, mean=5.0, p=0.04",
    )
    b2 = TextBlock(
        page=4,
        bbox=(0, 0, 100, 100),
        text="Group 2: n=12, mean=4.2, p=0.06",
    )
    tables = extract_tables_from_text([b1, b2])
    assert len(tables) == 1
    assert len(tables[0].rows) == 2


def test_extract_tables_from_text_uses_canonical_column_order() -> None:
    b = TextBlock(
        page=1,
        bbox=(0, 0, 100, 100),
        text="p<0.05, n=20, mean=4.20",
    )
    tables = extract_tables_from_text([b])
    # Order: n, mean, sd, p_value, pct, t, F, chi2, r
    assert tables[0].headers == ["n", "mean", "p_value"]


def test_extract_tables_from_text_source_kind() -> None:
    b = TextBlock(
        page=1,
        bbox=(0, 0, 100, 100),
        text="n=20, mean=4.20",
    )
    tables = extract_tables_from_text([b])
    assert tables[0].source_kind == "pdf_text_stat"
    assert tables[0].table_id == "pdf_text_stat:p1"
    assert tables[0].source_index == 0  # 0-based page


def test_extract_tables_from_text_caps_at_max() -> None:
    blocks = [
        TextBlock(
            page=p,
            bbox=(0, 0, 100, 100),
            text=f"Page {p} has n=10, mean=1.0",
        )
        for p in range(1, 200)
    ]
    tables = extract_tables_from_text(blocks, max_tables=5)
    assert len(tables) <= 5


# ---- Real PDF ----


def test_extract_tables_from_real_frontiers_pdf() -> None:
    """The case_bio_001 PDF is a real Frontiers
    paper; the extractor should find at least
    one stat descriptor in the text layer.
    """
    pdf = (
        PROJECT_ROOT
        / "manusift_benchmarks"
        / "officially_flagged_cases_v2"
        / "cases"
        / "biomedical"
        / "case_bio_001"
        / "paper.pdf"
    )
    if not pdf.exists():
        pytest.skip("case_bio_001 paper.pdf not present")
    tables = extract_tables_from_pdf_path(pdf)
    assert len(tables) >= 1
    # Every synthetic table has source_kind set
    for t in tables:
        assert t.source_kind == "pdf_text_stat"
        assert len(t.headers) > 0
        assert len(t.rows) > 0


def test_extract_tables_from_pdf_handles_missing_path() -> None:
    """A nonexistent path returns an empty list
    (no exception)."""
    tables = extract_tables_from_pdf_path(
        "/nonexistent/path/to/file.pdf"
    )
    assert tables == []
