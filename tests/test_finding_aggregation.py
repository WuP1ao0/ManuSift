"""Tests for finding aggregation (P1.1).

The aggregator is a view layer: it must group findings that point at the
same evidence object into one issue, never drop or rewrite a finding,
and be fully deterministic.
"""
from __future__ import annotations

from manusift.contracts import Finding
from manusift.report.finding_aggregation import (
    Issue,
    aggregate_findings,
)


def _mk(
    finding_id: str,
    detector: str,
    severity: str = "medium",
    raw: dict | None = None,
    location: str = "",
    title: str = "t",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        trace_id="trace-test",
        detector=detector,
        severity=severity,  # type: ignore[arg-type]
        title=title,
        evidence="e",
        location=location,
        raw=raw or {},
    )


def _img(page: int, index: int, phash: str | None = None) -> dict:
    d: dict = {"page": page, "index": index}
    if phash:
        d["phash"] = phash
    return d


def _issue_of(issues: list[Issue], finding_id: str) -> Issue:
    for i in issues:
        if finding_id in i.finding_ids:
            return i
    raise AssertionError(f"{finding_id} not in any issue")


# ---------------------------------------------------------------------------
# image grouping
# ---------------------------------------------------------------------------


def test_same_image_multi_channel_collapses_to_one_issue():
    """image_dup + forensics SIFT + ELA + panel SIFT on the same image
    pair must land in a single issue."""
    findings = [
        _mk(
            "f01",
            "image_dup",
            "high",
            raw={"image_a": _img(0, 0), "image_b": _img(1, 0)},
        ),
        _mk(
            "f02",
            "image_forensics",
            "medium",
            raw={
                "kind": "cross_image_sift",
                "image_a": _img(0, 0),
                "image_b": _img(1, 0),
            },
        ),
        _mk(
            "f03",
            "image_forensics",
            "low",
            raw={"kind": "ela", "page": 0, "index": 0},
        ),
        _mk(
            "f04",
            "image_forensics",
            "medium",
            raw={
                "kind": "panel_sift_match",
                "page": 1,
                "index": 0,
                "panel_a": [0, 0, 10, 10],
                "panel_b": [5, 5, 10, 10],
            },
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.kind == "image"
    assert issue.member_count == 4
    assert set(issue.finding_ids) == {"f01", "f02", "f03", "f04"}
    assert issue.detectors == ("image_dup", "image_forensics")


def test_disjoint_image_pairs_do_not_merge():
    findings = [
        _mk(
            "f01",
            "image_dup",
            raw={"image_a": _img(0, 0), "image_b": _img(1, 0)},
        ),
        _mk(
            "f02",
            "image_dup",
            raw={"image_a": _img(5, 0), "image_b": _img(6, 0)},
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2
    assert _issue_of(issues, "f01") is not _issue_of(issues, "f02")


def test_pairs_sharing_one_image_merge_transitively():
    """(A-B) and (B-C) pairs collapse into one cluster via union-find."""
    findings = [
        _mk(
            "f01",
            "image_dup",
            raw={"image_a": _img(0, 0), "image_b": _img(1, 0)},
        ),
        _mk(
            "f02",
            "image_forensics",
            raw={
                "kind": "texture_overlap",
                "image_a": _img(1, 0),
                "image_b": _img(2, 0),
            },
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 1
    assert issues[0].member_count == 2


def test_phash_bridge_links_near_equal_hashes():
    """Endpoints whose pHashes nearly match merge even when page/index
    disagree."""
    findings = [
        _mk(
            "f01",
            "image_forensics",
            "low",
            raw={"kind": "ela", "page": 0, "index": 0, "phash": "80bf30e70d7903de"},
        ),
        _mk(
            "f02",
            "image_forensics",
            "low",
            raw={"kind": "ela", "page": 3, "index": 1, "phash": "80bf30e70d7903de"},
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 1


def test_panel_duplicate_location_fallback_groups_by_image():
    """panel_duplicate findings carry no raw identity; the
    ``image N on page M`` location convention must still group them."""
    findings = [
        _mk(
            "f01",
            "panel_duplicate",
            "high",
            location="image 3 on page 0, panels ((1, 2, 3, 4), (5, 6, 7, 8))",
        ),
        _mk(
            "f02",
            "image_forensics",
            "low",
            raw={"kind": "ela", "page": 0, "index": 2},  # image 3 on page 0
        ),
        _mk(
            "f03",
            "panel_duplicate",
            "high",
            location="image 1 on page 4, panels ((1, 2, 3, 4), (5, 6, 7, 8))",
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2
    assert _issue_of(issues, "f01") is _issue_of(issues, "f02")
    assert _issue_of(issues, "f03") is not _issue_of(issues, "f01")


def test_page_raster_dup_groups_page_pairs():
    findings = [
        _mk(
            "f01",
            "page_raster_dup",
            "medium",
            raw={
                "page_a": 0,
                "page_b": 2,
                "phash_a": "8346ce5f8b275fcf",
                "phash_b": "13e69a570b275fcf",
            },
        ),
        _mk(
            "f02",
            "page_raster_dup",
            "low",
            raw={
                "page_a": 0,
                "page_b": 3,
                "phash_a": "8346ce5f8b275fcf",
                "phash_b": "13e69a570b275fff",
            },
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 1
    assert issues[0].kind == "image"
    assert issues[0].member_count == 2


def test_imageless_image_detector_falls_back_to_detector_issue():
    """Findings without any image identity (summary rows, AI-figure
    flags) group into one issue per detector."""
    findings = [
        _mk("f01", "image_forensics", "low", raw={"kind": "image_forensics_summary"}),
        _mk("f02", "image_forensics", "medium", raw={"kind": "image_forensics_summary"}),
        _mk("f03", "ai_generated_figure", "low", location="images"),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2
    assert _issue_of(issues, "f01") is _issue_of(issues, "f02")


# ---------------------------------------------------------------------------
# severity / issue fields
# ---------------------------------------------------------------------------


def test_severity_is_max_of_members():
    findings = [
        _mk("f01", "image_dup", "low", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f02", "image_dup", "high", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f03", "image_dup", "medium", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
    ]
    (issue,) = aggregate_findings(findings)
    assert issue.severity == "high"
    assert issue.member_count == 3
    assert issue.issue_id.startswith("ISS-")
    d = issue.to_dict()
    assert d["member_count"] == 3
    assert sorted(d["finding_ids"]) == ["f01", "f02", "f03"]


# ---------------------------------------------------------------------------
# non-destructive + determinism
# ---------------------------------------------------------------------------


def test_input_list_is_not_modified():
    findings = [
        _mk("f01", "image_dup", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f02", "text_patterns", "low", raw={"check": "duplicate_passage"}),
    ]
    snapshot = list(findings)
    aggregate_findings(findings)
    assert findings == snapshot
    assert len(findings) == 2


def test_every_finding_lands_in_exactly_one_issue():
    findings = [
        _mk("f01", "image_dup", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f02", "table_relationships", raw={"check": "fixed_offset"},
            location="Table #1, columns 1-2"),
        _mk("f03", "text_patterns", raw={"check": "duplicate_passage"}),
        _mk("f04", "pdf_metadata", "info"),
        _mk("f05", "some_unknown_detector", "low"),
    ]
    issues = aggregate_findings(findings)
    all_ids = [fid for i in issues for fid in i.finding_ids]
    assert sorted(all_ids) == ["f01", "f02", "f03", "f04", "f05"]


def test_deterministic_across_runs_and_input_order():
    findings = [
        _mk("f01", "image_dup", "high", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f02", "image_forensics", "low", raw={"kind": "ela", "page": 0, "index": 0}),
        _mk("f03", "table_relationships", "medium", raw={"check": "fixed_offset"},
            location="Table #1, columns 1-2"),
        _mk("f04", "text_patterns", "low", raw={"check": "duplicate_passage"}),
        _mk("f05", "page_raster_dup", "medium", raw={"page_a": 0, "page_b": 2}),
    ]
    first = [i.to_dict() for i in aggregate_findings(findings)]
    second = [i.to_dict() for i in aggregate_findings(list(findings))]
    assert first == second
    # reversed input order must produce the identical serialization
    reversed_run = [i.to_dict() for i in aggregate_findings(list(reversed(findings)))]
    assert reversed_run == first


def test_issue_sort_order_is_severity_then_count():
    findings = [
        _mk("f01", "text_patterns", "low", raw={"check": "duplicate_passage"}),
        _mk("f02", "image_dup", "high", raw={"image_a": _img(0, 0), "image_b": _img(1, 0)}),
        _mk("f03", "image_forensics", "medium", raw={"kind": "ela", "page": 0, "index": 0}),
    ]
    issues = aggregate_findings(findings)
    assert issues[0].severity == "high"
    assert issues[-1].severity == "low"


# ---------------------------------------------------------------------------
# table grouping
# ---------------------------------------------------------------------------


def test_table_grouping_by_identity_and_check():
    findings = [
        _mk(
            "f01",
            "table_relationships",
            "medium",
            raw={"check": "terminal_digit_concentration", "n": 10},
            location="Table page_3 #2, column 8 ('col_7')",
        ),
        _mk(
            "f02",
            "table_relationships",
            "low",
            raw={"check": "terminal_digit_concentration", "n": 8},
            location="Table page_3 #2, column 9 ('col_8')",
        ),
        _mk(
            "f03",
            "table_relationships",
            "high",
            raw={"check": "improbable_repeated_values"},
            location="Table page_3 #2, column 9 ('col_8')",
        ),
        _mk(
            "f04",
            "table_duplicate_row",
            "medium",
            location="Table page_1 #1",
        ),
    ]
    issues = aggregate_findings(findings)
    # f01+f02 same table + same check → 1 issue; f03 same table other
    # check → own issue; f04 other table → own issue.
    assert len(issues) == 3
    assert _issue_of(issues, "f01") is _issue_of(issues, "f02")
    assert _issue_of(issues, "f03") is not _issue_of(issues, "f01")
    assert all(i.kind == "table" for i in issues)


def test_table_cross_table_pair_identity():
    """left_table/right_table pairs share one issue regardless of column
    variants and side order."""
    findings = [
        _mk(
            "f01",
            "table_relationships",
            "high",
            raw={"check": "cross_table_fixed_offset", "left_table": "Fig.1", "right_table": "Fig.2"},
        ),
        _mk(
            "f02",
            "table_relationships",
            "medium",
            raw={"check": "cross_table_fixed_offset", "left_table": "Fig.2", "right_table": "Fig.1"},
        ),
        _mk(
            "f03",
            "table_relationships",
            "medium",
            # plain fixed_offset folds into the same check cluster
            raw={"check": "fixed_offset", "left_table": "Fig.1", "right_table": "Fig.2"},
        ),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 1
    assert issues[0].member_count == 3


# ---------------------------------------------------------------------------
# text / metadata grouping
# ---------------------------------------------------------------------------


def test_text_grouping_by_detector_family():
    findings = [
        _mk("f01", "text_patterns", "low", raw={"check": "duplicate_passage"}, location="Page 1"),
        _mk("f02", "text_patterns", "medium", raw={"check": "boilerplate"}, location="Page 3"),
        _mk("f03", "text_tortured_phrases", "medium", location="Page 2"),
        _mk("f04", "ref_duplicate", "low"),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2
    text_issue = _issue_of(issues, "f01")
    assert text_issue.kind == "text"
    assert set(text_issue.finding_ids) == {"f01", "f02", "f03"}
    assert _issue_of(issues, "f04").kind == "text"


def test_metadata_grouping():
    findings = [
        _mk("f01", "pdf_metadata", "info"),
        _mk("f02", "metadata", "low"),
        _mk("f03", "compliance", "medium"),
    ]
    issues = aggregate_findings(findings)
    assert len(issues) == 2
    meta_issue = _issue_of(issues, "f01")
    assert meta_issue.kind == "metadata"
    assert set(meta_issue.finding_ids) == {"f01", "f02"}
    assert _issue_of(issues, "f03").kind == "metadata"


# ---------------------------------------------------------------------------
# empty input
# ---------------------------------------------------------------------------


def test_empty_input():
    assert aggregate_findings([]) == []
