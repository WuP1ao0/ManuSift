"""P6.2: p-value pile-up, SPRITE-lite, correlation PSD."""
from __future__ import annotations

import json

from manusift.detectors.stat_extra import (
    CorrelationMatrixPSDDetector,
    PValuePileupDetector,
    SpriteLiteDetector,
)


class FakeTable:
    def __init__(self, headers, rows, sheet_name="", fig_name=""):
        self.headers = list(headers)
        self.rows = [list(r) for r in rows]
        self.sheet_name = sheet_name
        self.fig_name = fig_name


class FakeDoc:
    def __init__(self, tables=None, text=""):
        self.trace_id = "t-p62"
        self.source_path = ""
        if text:
            self.text_blocks = [type("B", (), {"text": text})()]
        else:
            self.text_blocks = []
        self.images = []
        self.metadata = {}
        self.tables = list(tables or [])


def test_pvalue_pileup_flags_near_05_cluster() -> None:
    # 8 exact p in (0.001,0.10], 4 of them in (0.04,0.05]
    ps = [0.012, 0.043, 0.044, 0.045, 0.049, 0.061, 0.072, 0.088]
    text = " ".join(f"p = {p}" for p in ps)
    doc = FakeDoc(text=text)
    r = PValuePileupDetector().run(doc)
    assert r.ok
    assert r.findings
    assert r.findings[0].severity in ("high", "medium")
    raw = r.findings[0].raw or {}
    assert raw.get("check") == "pvalue_pileup"
    assert raw.get("n_in_band", raw.get("n")) >= 4


def test_pvalue_pileup_quiet_on_sparse_p() -> None:
    text = "p = 0.001 and p = 0.20 only"
    r = PValuePileupDetector().run(FakeDoc(text=text))
    assert r.findings == []


def test_sprite_disabled_by_default() -> None:
    text = "M = 3.0, SD = 4.0, n = 10"  # impossible on 1-5
    r = SpriteLiteDetector().run(FakeDoc(text=text))
    assert r.findings == []


def test_sprite_flags_sd_above_max(monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_SPRITE_ENABLED", "1")
    # On 1-5 scale, mean 3, n=10, max SD is about 2.11; SD=3.5 impossible
    text = "mean = 3.0, SD = 3.5, n = 10 for the Likert item."
    r = SpriteLiteDetector().run(FakeDoc(text=text))
    assert r.findings
    assert any("exceeds max feasible" in f.title for f in r.findings)
    assert r.findings[0].severity == "high"


def test_corr_psd_flags_non_psd_matrix() -> None:
    # Classic non-PSD "correlation" matrix
    headers = ["A", "B", "C"]
    rows = [
        [1.0, 0.9, 0.9],
        [0.9, 1.0, 0.9],
        [0.9, 0.9, 1.0],
    ]
    # Actually that one is PSD. Use impossible:
    rows_bad = [
        [1.0, 0.9, -0.9],
        [0.9, 1.0, 0.9],
        [-0.9, 0.9, 1.0],
    ]
    table = FakeTable(
        headers, rows_bad, sheet_name="Correlation matrix"
    )
    r = CorrelationMatrixPSDDetector().run(FakeDoc(tables=[table]))
    assert r.findings
    assert "not positive semi-definite" in r.findings[0].title
    raw = r.findings[0].raw or {}
    assert raw.get("check") == "corr_matrix_not_psd"
    assert float(raw["min_eigenvalue"]) < 0


def test_corr_psd_accepts_valid_matrix() -> None:
    headers = ["A", "B", "C"]
    rows = [
        [1.0, 0.2, 0.1],
        [0.2, 1.0, 0.3],
        [0.1, 0.3, 1.0],
    ]
    table = FakeTable(headers, rows, sheet_name="Pearson correlations")
    r = CorrelationMatrixPSDDetector().run(FakeDoc(tables=[table]))
    assert r.findings == []
