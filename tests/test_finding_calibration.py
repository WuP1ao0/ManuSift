"""P0 finding calibration: severity recalibration + cluster demotion."""
from __future__ import annotations

from collections import Counter

from manusift.contracts import Finding
from manusift.report.finding_calibration import (
    calibrate_findings,
    calibration_stats,
)


def _f(
    *,
    detector: str = "table_relationships",
    severity: str = "high",
    title: str = "t",
    location: str = "loc",
    raw: dict | None = None,
    fid: str | None = None,
) -> Finding:
    f = Finding.make(
        trace_id="t-cal",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence="e",
        location=location,
        raw=raw or {},
    )
    if fid:
        object.__setattr__(f, "finding_id", fid)
    return f


def test_count_preserved() -> None:
    findings = [
        _f(
            severity="high",
            location="A, column 1 to B, column 1",
            raw={
                "check": "cross_table_repeated_values",
                "n": 100,
                "left_table": "Fig.S1a",
                "right_table": "Fig.S1c",
                "left_column": "a",
                "right_column": "c",
            },
        )
        for _ in range(5)
    ]
    out = calibrate_findings(findings)
    assert len(out) == len(findings)


def test_empty_column_immune_for_fabrication_checks() -> None:
    """Nature Source Data blank rep headers must not bury fixed_offset."""
    f = _f(
        severity="high",
        location="Table #1, columns 1 and 2",
        raw={
            "check": "fixed_offset",
            "n": 20,
            "offset": 0,
            "left_column": "",
            "right_column": "",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity == "high"
    reasons = out.raw.get("calibration", {}).get("reasons") or []
    assert "empty_header_immune_fabrication_check" in reasons
    assert "empty_or_placeholder_column" not in reasons


def test_empty_column_still_demotes_weak_non_fabrication() -> None:
    f = _f(
        severity="high",
        location="T, columns 1 and 2",
        raw={
            "check": "arithmetic_progression",
            "n": 20,
            "step": 1,
            "column": "",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity in ("medium", "low")
    assert "empty_or_placeholder_column" in (
        out.raw.get("calibration", {}).get("reasons") or []
    )


def test_clean_nonzero_offset_stays_high() -> None:
    """A = B + clean offset with solid n is a high fabrication signal."""
    f = _f(
        severity="high",
        location="T, columns 1 and 2",
        raw={
            "check": "fixed_offset",
            "n": 30,
            "offset": 2.5,
            "left_column": "a",
            "right_column": "b",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity == "high"
    reasons = out.raw.get("calibration", {}).get("reasons") or []
    assert "clean_nonzero_offset_boost_high" in reasons or not reasons


def test_messy_nonzero_offset_cap_medium() -> None:
    f = _f(
        severity="high",
        location="T, columns 1 and 2",
        raw={
            "check": "fixed_offset",
            "n": 30,
            "offset": 0.137924,  # not on a clean Excel grid
            "left_column": "a",
            "right_column": "b",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity != "high"
    assert "nonzero_offset_cap_medium" in out.raw["calibration"]["reasons"]


def test_weak_check_cap() -> None:
    f = _f(
        severity="high",
        location="A, column 1 to B, column 1",
        raw={
            "check": "cross_table_matching_decimal_tails",
            "n": 40,
            "matching_pairs": 20,  # only 50% — not perfect
            "match_fraction": 0.5,
            "left_table": "A",
            "right_table": "B",
            "left_column": "x",
            "right_column": "y",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity in ("medium", "low")


def test_perfect_decimal_tail_boosts_high() -> None:
    f = _f(
        severity="medium",
        location="A, column 1 to B, column 1",
        raw={
            "check": "matching_decimal_tails",
            "n": 12,
            "matching_pairs": 12,
            "match_fraction": 1.0,
            "left_column": "rep1",
            "right_column": "rep2",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity == "high"
    assert "perfect_decimal_tail_boost_high" in out.raw["calibration"]["reasons"]


def test_cluster_satellite_demotion() -> None:
    """Many column variants of same table pair → only top-K stay high."""
    findings = []
    for i in range(12):
        findings.append(
            _f(
                severity="high",
                fid=f"id{i:02d}",
                location=f"Fig.S1a in Sfig.2, column {i+1} to Fig.S1c in Sfig.2, column {i+1}",
                raw={
                    "check": "cross_table_repeated_values",
                    "n": 100 - i,  # decreasing n
                    "left_table": "Fig.S1a in Sfig.2",
                    "right_table": "Fig.S1c in Sfig.2",
                    "left_column": f"c{i}",
                    "right_column": f"d{i}",
                },
            )
        )
    out = calibrate_findings(findings)
    highs = [f for f in out if f.severity == "high"]
    assert len(highs) <= 3  # MAX_HIGH default 2, TOP_K 3
    # largest n should remain high (or at least highest rank)
    by_id = {f.finding_id: f for f in out}
    assert by_id["id00"].severity == "high"
    # late satellites demoted
    assert by_id["id10"].severity in ("medium", "low")


def test_disable_env(monkeypatch) -> None:
    monkeypatch.setenv("MANUSIFT_FINDING_CALIBRATE", "0")
    f = _f(
        severity="high",
        raw={
            "check": "cross_table_matching_decimal_tails",
            "n": 10,
            "left_table": "A",
            "right_table": "B",
        },
    )
    out = calibrate_findings([f])[0]
    assert out.severity == "high"


def test_pilot_acceptance_bounds() -> None:
    """Offline acceptance on Nature pilot findings if present."""
    from pathlib import Path

    from manusift.report.investigation_pairs import findings_from_json

    path = Path(
        "docs/s41565-025-02082-0/pilot_artifacts/"
        "deep_screen_with_llm/536c86c868db/findings.json"
    )
    if not path.is_file():
        return
    _tid, findings, _llm = findings_from_json(path)
    # strip prior calibration if re-running
    cleaned = []
    for f in findings:
        raw = dict(f.raw) if isinstance(f.raw, dict) else {}
        raw.pop("calibration", None)
        cleaned.append(
            Finding(
                finding_id=f.finding_id,
                trace_id=f.trace_id,
                detector=f.detector,
                severity=f.severity,
                title=f.title,
                evidence=f.evidence,
                location=f.location,
                raw=raw,
                llm_verdict=f.llm_verdict,
                llm_skipped=f.llm_skipped,
            )
        )
    base_high = sum(1 for f in cleaned if f.severity == "high")
    out = calibrate_findings(cleaned)
    stats = calibration_stats(out)
    # Calibration never drops findings, but it may ADD bridge
    # findings (forensics → image_dup / panel_duplicate
    # mirrors, see HANDOFF §5.1), so the length invariant is
    # "not smaller", not "equal".
    assert len(out) >= len(cleaned)
    # Excel-fabrication boosts (clean nonzero offset, perfect tails,
    # empty-header immune) raise high slightly; keep a soft ceiling.
    assert stats["high"] <= 280
    tr_high = sum(
        1
        for f in out
        if f.detector == "table_relationships" and f.severity == "high"
    )
    assert tr_high <= 280
    # must improve if baseline was heavily inflated
    if base_high > 280:
        assert stats["high"] < base_high
    assert stats["demoted"] > 0
