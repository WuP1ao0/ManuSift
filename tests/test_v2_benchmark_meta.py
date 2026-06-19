"""Smoke tests for the v2 benchmark scripts.

These tests verify the build / scoring logic of
the v2 benchmark without invoking the network or
the full ManuSift pipeline (those are
integration-only).  They use the 30-case spec
embedded in ``cases_meta.py`` as the source of
truth.

We deliberately keep these tests offline so they
can run as part of the standard ``pytest`` suite
without polluting the workspace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Path to the v2 benchmark root (one level up
# from the tests/ dir)
V2_ROOT = (
    Path(__file__).resolve().parent.parent
    / "manusift_benchmarks"
    / "officially_flagged_cases_v2"
)
sys.path.insert(0, str(V2_ROOT))

from cases_meta import (  # noqa: E402
    CASES,
    CATEGORY_MAP,
    TEST_TO_DETECTORS,
    case_by_id,
    primary_tests_to_detectors,
)


def test_cases_count_is_30() -> None:
    assert len(CASES) == 30


def test_each_case_has_required_fields() -> None:
    required = {
        "case_id",
        "domain",
        "title",
        "doi",
        "primary_tests",
    }
    for c in CASES:
        missing = required - set(c.keys())
        assert not missing, f"{c['case_id']} missing {missing}"


def test_each_case_id_is_unique() -> None:
    ids = [c["case_id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case_id"


def test_each_domain_has_exactly_5_cases() -> None:
    by_domain: dict[str, int] = {}
    for c in CASES:
        by_domain[c["domain"]] = by_domain.get(c["domain"], 0) + 1
    for d, n in by_domain.items():
        assert n == 5, f"{d} has {n} cases, expected 5"


def test_doi_format() -> None:
    """All DOIs look like '10.NNNN/...'."""
    import re
    pat = re.compile(r"^10\.\d{3,9}/\S+$")
    for c in CASES:
        assert pat.match(c["doi"]), (
            f"{c['case_id']}: bad DOI '{c['doi']}'"
        )


def test_category_map_case_ids_exist() -> None:
    ids = {c["case_id"] for c in CASES}
    for cat, cases in CATEGORY_MAP.items():
        for cid in cases:
            assert cid in ids, (
                f"category_map.{cat} references unknown case {cid}"
            )


def test_category_map_covers_spec() -> None:
    """The 6 user-spec categories are all present."""
    expected = {
        "image_duplication",
        "data_validity",
        "source_data_missing",
        "peer_review_manipulation",
        "citation_manipulation",
        "content_overlap",
    }
    assert expected <= set(CATEGORY_MAP.keys())


def test_test_to_detectors_keys_match_spec_categories() -> None:
    """Every ``primary_test`` used in CASES has a
    mapping in ``TEST_TO_DETECTORS``.  Otherwise the
    benchmark cannot translate the spec into
    detectors.
    """
    used: set[str] = set()
    for c in CASES:
        used.update(c["primary_tests"])
    missing = used - set(TEST_TO_DETECTORS.keys())
    assert not missing, f"TEST_TO_DETECTORS missing keys: {missing}"


def test_primary_tests_to_detectors_dedups() -> None:
    out = primary_tests_to_detectors(
        ["image_duplication", "image_manipulation"]
    )
    # ``image_dup`` and ``image_forensics`` appear
    # in both input maps; the output should
    # de-duplicate.
    assert out.count("image_dup") == 1
    assert out.count("image_forensics") == 1


def test_primary_tests_to_detectors_unknown_test_is_silent() -> None:
    """An unknown ``primary_test`` should NOT raise;
    it should contribute no detectors.
    """
    out = primary_tests_to_detectors(["unknown_test_xyz"])
    assert out == []


def test_lookup_known_case() -> None:
    c = case_by_id("case_bio_001")
    assert c is not None
    assert c["doi"] == "10.3389/fnmol.2021.728128"


def test_lookup_unknown_returns_none() -> None:
    assert case_by_id("case_does_not_exist") is None


def test_each_case_has_at_least_one_primary_test() -> None:
    for c in CASES:
        assert c["primary_tests"], (
            f"{c['case_id']} has no primary_tests"
        )


def test_v2_root_has_scripts() -> None:
    """The 4 build / run scripts exist at the v2 root."""
    expected = [
        "downloader.py",
        "build_official_gold.py",
        "run_manusift.py",
        "build_alignment.py",
        "build_summary.py",
        "cases_meta.py",
    ]
    for s in expected:
        p = V2_ROOT / s
        assert p.exists(), f"missing script {p}"


def test_v2_root_has_cases_subdirs() -> None:
    """The 6 domain subdirs exist under cases/."""
    expected_domains = {
        "biomedical",
        "clinical_public_health",
        "psychology_social_science",
        "chemistry_materials_nanotech",
        "engineering_energy_applied",
        "environmental_agriculture_ecology",
    }
    actual = {
        p.name
        for p in (V2_ROOT / "cases").iterdir()
        if p.is_dir()
    }
    assert expected_domains <= actual, (
        f"missing domain subdirs: "
        f"{expected_domains - actual}"
    )
