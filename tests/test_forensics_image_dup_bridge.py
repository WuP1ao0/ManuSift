"""Forensics → image_dup bridge (calibration layer)."""
from __future__ import annotations

from manusift.contracts import Finding
from manusift.report.finding_calibration import (
    bridge_forensics_to_image_dup,
    calibrate_findings,
)


def _forensics(
    *,
    kind: str,
    page_a: int,
    idx_a: int,
    page_b: int,
    idx_b: int,
    severity: str = "medium",
) -> Finding:
    return Finding.make(
        trace_id="t-bridge",
        detector="image_forensics",
        severity=severity,  # type: ignore[arg-type]
        title=f"forensics {kind}",
        evidence="cross-image match",
        location=f"Page {page_a + 1} / image {idx_a} -> Page {page_b + 1} / image {idx_b}",
        raw={
            "kind": kind,
            "image_a": {"page": page_a, "index": idx_a},
            "image_b": {"page": page_b, "index": idx_b},
        },
    )


def test_bridge_emits_image_dup_from_cross_image_sift() -> None:
    src = _forensics(
        kind="cross_image_sift",
        page_a=2,
        idx_a=0,
        page_b=3,
        idx_b=1,
    )
    out = bridge_forensics_to_image_dup([src])
    dups = [f for f in out if f.detector == "image_dup"]
    assert len(dups) == 1
    assert dups[0].raw.get("pass") == "forensics_bridge"
    assert dups[0].raw.get("source_kind") == "cross_image_sift"
    assert dups[0].severity in ("medium", "high")


def test_bridge_dedupes_existing_image_dup_pair() -> None:
    existing = Finding.make(
        trace_id="t-bridge",
        detector="image_dup",
        severity="high",
        title="Near-duplicate",
        evidence="pHash",
        location="p",
        raw={
            "image_a": {"page": 1, "index": 0},
            "image_b": {"page": 2, "index": 0},
            "pass": "primary",
        },
    )
    src = _forensics(
        kind="texture_overlap",
        page_a=2,
        idx_a=0,
        page_b=1,
        idx_b=0,  # reverse order same pair
    )
    out = bridge_forensics_to_image_dup([existing, src])
    dups = [f for f in out if f.detector == "image_dup"]
    assert len(dups) == 1  # only the existing one


def test_bridge_ignores_non_cross_kinds() -> None:
    src = _forensics(
        kind="ela",
        page_a=0,
        idx_a=0,
        page_b=0,
        idx_b=1,
    )
    # ELA is not in bridge set; also pair may be incomplete
    src = Finding.make(
        trace_id="t",
        detector="image_forensics",
        severity="medium",
        title="ELA",
        evidence="e",
        location="loc",
        raw={"kind": "ela"},
    )
    out = bridge_forensics_to_image_dup([src])
    assert all(f.detector != "image_dup" for f in out)


def test_calibrate_findings_runs_bridge() -> None:
    src = _forensics(
        kind="near_texture_overlap",
        page_a=0,
        idx_a=0,
        page_b=1,
        idx_b=0,
    )
    out = calibrate_findings([src], enabled=True)
    assert any(f.detector == "image_dup" for f in out)


def test_bridge_panel_sift_to_panel_duplicate() -> None:
    from manusift.report.finding_calibration import (
        bridge_forensics_to_panel_duplicate,
    )

    src = Finding.make(
        trace_id="t-panel",
        detector="image_forensics",
        severity="medium",
        title="panel sift",
        evidence="match",
        location="Page 3 / image 1 panels ...",
        raw={
            "kind": "panel_sift_match",
            "page": 2,
            "index": 1,
            "panel_a": [10, 10, 100, 80],
            "panel_b": [120, 10, 100, 80],
            "inlier_count": 12,
        },
    )
    out = bridge_forensics_to_panel_duplicate([src])
    panels = [f for f in out if f.detector == "panel_duplicate"]
    assert len(panels) == 1
    assert panels[0].raw.get("pass") == "forensics_bridge"
    assert panels[0].raw.get("source_kind") == "panel_sift_match"
