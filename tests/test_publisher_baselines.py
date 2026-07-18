"""P1.3 publisher/template baseline whitelist (high -> medium demotion)."""
from __future__ import annotations

import json

import pytest

from manusift.contracts import Finding
from manusift.report.finding_calibration import (
    _load_publisher_baselines,
    calibrate_findings,
    resolve_publisher,
)


def _f(
    *,
    detector: str,
    severity: str = "high",
    title: str = "t",
    raw: dict | None = None,
) -> Finding:
    return Finding.make(
        trace_id="t-pub",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence="e",
        location="loc",
        raw=raw or {},
    )


def _demoted(out: list[Finding], idx: int = 0) -> Finding:
    f = out[idx]
    assert f.severity == "medium"
    pb = (f.raw or {}).get("publisher_baseline")
    assert isinstance(pb, dict)
    assert pb["rule_id"]
    assert pb["prior_severity"] == "high"
    assert pb["severity"] == "medium"
    assert pb["reason"]
    cal = (f.raw or {}).get("calibration")
    assert isinstance(cal, dict)
    assert any(
        r.startswith("publisher_baseline:") for r in cal.get("reasons", [])
    )
    return f


# --- one hit per rule family -----------------------------------------------


def test_ref_duplicate_conflicting_metadata_demoted() -> None:
    f = _f(
        detector="ref_duplicate",
        title="Duplicate reference: doi:10.1371/journal.pone.0262764 "
        "appears with conflicting metadata (surname)",
    )
    out = calibrate_findings([f])
    assert len(out) == 1
    _demoted(out)


def test_ref_duplicate_without_conflict_untouched() -> None:
    f = _f(
        detector="ref_duplicate",
        title="Duplicate reference: doi:10.1371/journal.pone.0262764 "
        "appears 2 times",
    )
    out = calibrate_findings([f])
    assert out[0].severity == "high"
    assert "publisher_baseline" not in (out[0].raw or {})


@pytest.mark.parametrize(
    "kind,title",
    [
        ("full_image_duplicate", "Identical image file reused 7 times"),
        ("cross_image_sift", "Cross-image local feature match (51 RANSAC inliers)"),
        ("texture_overlap", "Near-identical local image texture reused"),
        ("near_texture_overlap", "Near-identical local image texture reused"),
        ("panel_sift_match", "Panel-to-panel SIFT match (80 inliers)"),
    ],
)
def test_image_forensics_baseline_kinds_demoted(kind: str, title: str) -> None:
    f = _f(detector="image_forensics", title=title, raw={"kind": kind})
    out = calibrate_findings([f])
    _demoted(out)


def test_image_forensics_unlisted_kind_untouched() -> None:
    f = _f(
        detector="image_forensics",
        title="Copy-move region detected",
        raw={"kind": "copy_move"},
    )
    out = calibrate_findings([f])
    assert out[0].severity == "high"
    assert "publisher_baseline" not in (out[0].raw or {})


@pytest.mark.parametrize(
    "detector,title,raw",
    [
        (
            "panel_duplicate",
            "Panels 1 and 2 in image 4 on page 9 are near-duplicates "
            "(SSIM=0.969, pHash=0)",
            {},
        ),
        ("panel_dup", "Near-duplicate panel detected", {"hamming": 0}),
        (
            "image_dup",
            "Near-duplicate image / region (forensics bridge)",
            {"pass": "forensics_bridge", "source_kind": "cross_image_sift"},
        ),
        (
            "page_raster_dup",
            "Near-duplicate figure region detected (page raster)",
            {"hamming": 4},
        ),
        ("table_near_duplicate_row", "Table.2 in page_8 has 6 near-duplicate row pair(s)", {}),
        ("table_duplicate_row", "Table #3 has 3 duplicate row group(s)", {}),
        ("table_cross_copy", "1 row pattern(s) reused across multiple tables/sheets", {}),
    ],
)
def test_detector_wide_baseline_rules_demoted(
    detector: str, title: str, raw: dict
) -> None:
    f = _f(detector=detector, title=title, raw=raw)
    out = calibrate_findings([f])
    _demoted(out)


def test_medium_finding_not_boosted_or_recorded() -> None:
    f = _f(detector="panel_dup", severity="medium", title="Near-duplicate panel detected")
    out = calibrate_findings([f])
    assert out[0].severity == "medium"
    assert "publisher_baseline" not in (out[0].raw or {})


def test_unknown_detector_untouched() -> None:
    f = _f(detector="stat_grim", title="GRIM inconsistency")
    out = calibrate_findings([f])
    assert out[0].severity == "high"


# --- publisher scoping ------------------------------------------------------


def _write_rules(tmp_path, rules) -> str:
    p = tmp_path / "baselines.json"
    p.write_text(json.dumps({"rules": rules}), encoding="utf-8")
    return str(p)


def test_publisher_scoped_rule_applies_on_match(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "MANUSIFT_PUBLISHER_BASELINES",
        _write_rules(
            tmp_path,
            [
                {
                    "rule_id": "scoped",
                    "detector": "stat_grim",
                    "match": {},
                    "publisher": "plos",
                    "action": "demote_high_to_medium",
                    "rationale": "scoped test rule",
                }
            ],
        ),
    )
    f = _f(detector="stat_grim", title="GRIM inconsistency")
    hit = calibrate_findings([f], publisher="Public Library of Science (PLoS)")
    assert hit[0].severity == "medium"
    assert (hit[0].raw or {})["publisher_baseline"]["rule_id"] == "scoped"
    miss = calibrate_findings([f], publisher="BMJ")
    assert miss[0].severity == "high"


def test_publisher_scoped_rule_skipped_when_publisher_unknown(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "MANUSIFT_PUBLISHER_BASELINES",
        _write_rules(
            tmp_path,
            [
                {
                    "rule_id": "scoped",
                    "detector": "stat_grim",
                    "match": {},
                    "publisher": "plos",
                    "action": "demote_high_to_medium",
                    "rationale": "scoped test rule",
                }
            ],
        ),
    )
    out = calibrate_findings([_f(detector="stat_grim")])
    assert out[0].severity == "high"


# --- robustness -------------------------------------------------------------


def test_missing_rules_file_silently_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "MANUSIFT_PUBLISHER_BASELINES", str(tmp_path / "nope.json")
    )
    out = calibrate_findings([_f(detector="panel_dup")])
    assert out[0].severity == "high"


def test_corrupt_rules_file_silently_skipped(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "baselines.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("MANUSIFT_PUBLISHER_BASELINES", str(bad))
    out = calibrate_findings([_f(detector="panel_dup")])
    assert out[0].severity == "high"


def test_rules_not_a_list_silently_skipped(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "baselines.json"
    bad.write_text(json.dumps({"rules": "nope"}), encoding="utf-8")
    monkeypatch.setenv("MANUSIFT_PUBLISHER_BASELINES", str(bad))
    assert _load_publisher_baselines() == []
    out = calibrate_findings([_f(detector="panel_dup")])
    assert out[0].severity == "high"


# --- publisher resolution ---------------------------------------------------


def test_resolve_publisher_from_doi_prefix() -> None:
    assert (
        resolve_publisher(metadata={"doi": "10.1371/journal.pone.0262764"})
        == "plos"
    )
    assert (
        resolve_publisher(text="doi: 10.1136/bmjopen-2020-038879") == "bmj"
    )
    assert (
        resolve_publisher(
            findings=[
                _f(
                    detector="ref_duplicate",
                    title="Duplicate reference: doi:10.7759/cureus.12586 "
                    "appears with conflicting metadata (surname)",
                )
            ]
        )
        == "cureus"
    )
    assert resolve_publisher(publisher="Frontiers") == "frontiers"
    assert resolve_publisher(metadata={}) == ""


def test_count_preserved_with_baselines() -> None:
    findings = [
        _f(detector="panel_dup", title="Near-duplicate panel detected"),
        _f(detector="ref_duplicate", title="Duplicate reference: doi:10.1371/x appears with conflicting metadata (year)"),
        _f(detector="stat_grim", title="GRIM inconsistency"),
    ]
    out = calibrate_findings(findings)
    assert len(out) == len(findings)
    assert [f.severity for f in out] == ["medium", "medium", "high"]
