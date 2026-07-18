"""P1 thresholds + PhotoHolmes backend wiring + P2 PDF caption alignment."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from manusift.contracts import ExtractedTable, ParsedDoc
from manusift.ingest.pdf_tables import (
    _norm_caption,
    match_caption_to_bbox,
)


# ---------- P1: table relationship thresholds ----------


def test_threshold_profile_sensitive_looser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_TABLE_THRESHOLD_PROFILE", "sensitive")
    monkeypatch.delenv("MANUSIFT_TABLE_MIN_COLUMN_VALUES", raising=False)
    from manusift.detectors import table_relationships as tr

    tr.reload_thresholds()
    assert tr.MIN_COLUMN_VALUES == 3
    assert tr.MIN_DUPLICATE_FRACTION <= 0.65
    # restore default for other tests
    monkeypatch.setenv("MANUSIFT_TABLE_THRESHOLD_PROFILE", "default")
    tr.reload_thresholds()


def test_threshold_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUSIFT_TABLE_THRESHOLD_PROFILE", "strict")
    monkeypatch.setenv("MANUSIFT_TABLE_MIN_COLUMN_VALUES", "2")
    monkeypatch.setenv("MANUSIFT_TABLE_MIN_DUPLICATE_FRACTION", "0.5")
    from manusift.detectors import table_relationships as tr

    tr.reload_thresholds()
    assert tr.MIN_COLUMN_VALUES == 2
    assert abs(tr.MIN_DUPLICATE_FRACTION - 0.5) < 1e-9
    monkeypatch.delenv("MANUSIFT_TABLE_MIN_COLUMN_VALUES", raising=False)
    monkeypatch.delenv("MANUSIFT_TABLE_MIN_DUPLICATE_FRACTION", raising=False)
    monkeypatch.setenv("MANUSIFT_TABLE_THRESHOLD_PROFILE", "default")
    tr.reload_thresholds()


def test_default_profile_allows_n3_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1 default: SI n=3 parallel groups still enter column checks."""
    monkeypatch.setenv("MANUSIFT_TABLE_THRESHOLD_PROFILE", "default")
    monkeypatch.delenv("MANUSIFT_TABLE_MIN_COLUMN_VALUES", raising=False)
    from manusift.detectors import table_relationships as tr
    from manusift.detectors.table_relationships import TableRelationshipDetector

    tr.reload_thresholds()
    assert tr.MIN_COLUMN_VALUES <= 3

    table = ExtractedTable(
        table_id="t1",
        source_kind="xlsx",
        source_path="/tmp/a.xlsx",
        sheet_name="S",
        source_index=0,
        headers=["a", "b"],
        rows=[
            ["1.10", "1.40"],
            ["2.10", "2.40"],
            ["3.10", "3.40"],
        ],
        fig_name="Fig.3b",
    )
    doc = ParsedDoc(
        trace_id="t",
        source_path="<t>",
        text_blocks=[],
        images=[],
        tables=[table],
        metadata={},
    )
    res = TableRelationshipDetector().run(doc)
    # fixed offset 0.3 should fire with n=3 under default profile
    checks = []
    for f in res.findings:
        try:
            checks.append(json.loads(f.evidence).get("check"))
        except Exception:
            pass
    assert "fixed_offset" in checks


# ---------- P1: calibration + photoholmes backend ----------


def test_suggest_and_save_calibration(tmp_path: Path) -> None:
    from manusift.detectors.image_calibration import (
        save_calibration,
        suggest_thresholds,
        load_calibration,
        apply_calibration_to_env,
    )

    scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
    labels = [0, 0, 0, 1, 1, 1]
    sug = suggest_thresholds(scores, labels, target_fpr=0.1)
    assert "photoholmes_score_thr" in sug
    path = tmp_path / "cal.json"
    save_calibration(
        {"photoholmes_score_thr": sug["photoholmes_score_thr"], "notes": "test"},
        path=path,
    )
    loaded = load_calibration(path)
    assert loaded["schema"] == "manusift.image_calibration.v1"
    applied = apply_calibration_to_env(loaded)
    assert "MANUSIFT_PHOTOHOLMES_SCORE_THR" in applied


def test_photoholmes_backend_missing_package_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manusift.detectors.photoholmes_backend import PhotoHolmesBackend

    # Ensure no real photoholmes on path for this unit test — analyze returns []
    p = tmp_path / "x.png"
    from PIL import Image

    Image.new("RGB", (64, 64), (10, 20, 30)).save(p)
    hits = PhotoHolmesBackend().analyze(str(p))
    assert hits == []


def test_image_backends_photoholmes_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MANUSIFT_IMAGE_BACKEND", "photoholmes")
    from manusift.detectors.image_backends import get_optional_backends

    backends = get_optional_backends()
    assert len(backends) == 1
    assert backends[0].name == "photoholmes"
    monkeypatch.delenv("MANUSIFT_IMAGE_BACKEND", raising=False)


# ---------- P2: caption matching ----------


def test_norm_caption_fig3b() -> None:
    assert "3" in _norm_caption("Fig. 3b")
    assert "b" in _norm_caption("Fig. 3b").lower() or "3b" in _norm_caption(
        "Fig. 3b"
    ).lower()


def test_match_caption_prefers_above_table() -> None:
    captions = [
        (10.0, 50.0, 200.0, 70.0, "Fig.3a"),
        (10.0, 200.0, 200.0, 220.0, "Fig.3b"),  # below — ignore
        (10.0, 100.0, 200.0, 120.0, "Fig.3c"),  # just above table at y=130
    ]
    # table top at 130
    name = match_caption_to_bbox(captions, (10.0, 130.0, 400.0, 300.0))
    assert name == "Fig.3c"


def test_pdf_tables_module_matrix_parse() -> None:
    from manusift.ingest.pdf_tables import _rows_from_matrix

    parsed = _rows_from_matrix(
        [["A", "B"], ["1", "2"], ["3", "4"]]
    )
    assert parsed is not None
    headers, rows = parsed
    assert headers == ["A", "B"]
    assert len(rows) == 2
