"""R-2026-06-15 (Phase 1 + P1-12):
lightweight integration test
for the 30-case v2
benchmark.

The 30-case v2 benchmark
(
``manusift_benchmarks/officially_flagged_cases_v2/``
) has 30 cases spanning 6
domains.  Running the full
30 cases takes ~45 minutes
and uses significant memory
on the test machine, so the
**full** benchmark is a
production-only integration
test.  This pytest
integration test exercises
a **light** subset:

  1. The v2 inventory is
     intact (30 case
     directories, one
     ``paper.pdf`` per
     case).
  2. The pipeline module
     imports without raising
     (catches syntax errors
     and import-time
     regressions in the
     detector pipeline).
  3. All registered
     detectors can be
     enumerated (catches
     the "new detector
     forgot to register"
     regression).
  4. The detector list
     matches the
     ``detector_gap_report.md``
     expectations
     (12+ detectors
     registered, including
     ``pdf_metadata``,
     ``image_dup``,
     ``image_forensics``,
     ``text_patterns``,
     ``stat_consistency``,
     ``paper_mill_authorship``,
     ``noise_inconsistency``).

R-2026-06-15 (Phase 1 + P1-12):
the FULL 30-case v2
benchmark is a separate
process
(``manusift_benchmarks/officially_flagged_cases_v2/run_manusift.py``);
this pytest test is a
*guard* that catches
infrastructure regressions
(syntax errors, missing
detectors, deleted case
directories) at CI time
without paying the 45-minute
full-run cost.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


BENCH_ROOT = (
    Path(__file__).parent.parent
    / "manusift_benchmarks"
    / "officially_flagged_cases_v2"
)


def test_p112_30case_v2_inventory() -> None:
    """The 30-case v2
    benchmark has 30 case
    directories (5 per
    domain, 6 domains).

    This is a *light*
    check -- it does not
    run the benchmark, but
    it does verify the
    inventory is intact
    (so a partial deletion
    is caught at CI time,
    not at the next
    45-minute run).
    """
    case_root = BENCH_ROOT / "cases"
    if not case_root.exists():
        pytest.skip("no v2 cases dir")
    total = sum(
        1
        for d in case_root.rglob("case_*")
        if d.is_dir()
    )
    assert total >= 30, (
        f"only {total} cases in v2 benchmark; "
        f"expected >=30"
    )


def test_p112_every_case_has_paper_pdf() -> None:
    """Every case in the v2
    benchmark has a
    ``paper.pdf``.

    A case with no
    ``paper.pdf`` is
    ``not_testable`` and
    would be silently
    skipped by the runner;
    this test surfaces
    missing PDFs at CI
    time.
    """
    case_root = BENCH_ROOT / "cases"
    if not case_root.exists():
        pytest.skip("no v2 cases dir")
    missing: list[str] = []
    for d in case_root.rglob("case_*"):
        if not d.is_dir():
            continue
        if not (d / "paper.pdf").exists():
            missing.append(str(d))
    assert not missing, (
        f"{len(missing)} case(s) missing "
        f"paper.pdf: "
        f"{missing[:3]}"
    )


def test_p112_pipeline_imports_clean() -> None:
    """The pipeline module
    imports without raising
    (catches syntax errors
    and import-time
    regressions in the
    detector pipeline).
    """
    from manusift.pipeline import (  # noqa: F401
        run_pipeline,
    )
    from manusift.detectors import (  # noqa: F401
        iter_registered_detectors,
    )


def test_p112_at_least_12_detectors_registered() -> None:
    """At least 12 detectors
    are registered (the
    audit-recommended
    minimum; 39 detectors
    is the current count).

    R-2026-06-15 (Phase 1 + P1-12):
    ``iter_registered_detectors()``
    iterates ``_DETECTOR_SPECS``,
    which contains the 6
    *core* detectors the
    pipeline actually loads
    on every run.  The full
    39-detector set is
    enumerated via
    ``detector_names()``
    (which does not import
    implementations).  We
    use the latter for the
    count check.
    """
    from manusift.detectors import (
        detector_names,
    )
    names = detector_names()
    assert len(names) >= 12, (
        f"only {len(names)} detectors "
        f"registered; expected >=12"
    )


def test_p112_expected_detectors_present() -> None:
    """The detectors named in
    the audit's
    ``detector_gap_report.md``
    are present.

    The set below is the
    *minimum* the audit
    expects; if any of
    these are missing, the
    benchmark numbers
    regressed.

    R-2026-06-15 (Phase 1 + P1-12):
    the actual detector
    names differ from the
    class names (e.g.
    ``PdfMetadataDetector``
    has ``name =
    "metadata"``, not
    ``"pdf_metadata"``).
    Use the names that
    ``detector_names()``
    returns, not the class
    names.
    """
    from manusift.detectors import (
        detector_names,
    )
    names = set(detector_names())
    expected = {
        "metadata",  # PDF metadata
        "image_dup",
        "image_forensics",
        "text_patterns",
        "stat_grim",  # GRIM test
        "paper_mill_authorship",
        "image_noise_inconsistency",
    }
    missing = expected - names
    assert not missing, (
        f"expected detectors not registered: "
        f"{sorted(missing)}"
    )


def test_p112_smoke_run_one_case_in_subprocess() -> None:
    """Run ONE case
    (case_bio_001) in a
    subprocess to verify
    the pipeline does not
    crash on a real
    case.  We use a
    **180-second** budget
    (a real run on
    case_bio_001 takes
    ~10-120s on typical
    hardware, depending
    on PDF size and
    detector count).

    Set
    ``MANUSIFT_SKIP_P112_SMOKE=1``
    to skip this test in
    a memory-constrained
    CI environment.
    """
    if os.environ.get(
        "MANUSIFT_SKIP_P112_SMOKE"
    ) == "1":
        pytest.skip(
            "MANUSIFT_SKIP_P112_SMOKE=1"
        )
    smoke_case = (
        BENCH_ROOT
        / "cases"
        / "biomedical"
        / "case_bio_001"
    )
    if not smoke_case.exists():
        pytest.skip("smoke case not found")
    cmd = [
        sys.executable,
        str(BENCH_ROOT / "run_manusift.py"),
        "--cases",
        "case_bio_001",
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(BENCH_ROOT),
        timeout=180,
        env={
            **os.environ,
            "MANUSIFT_LLM_ENRICHMENT_BUDGET": "0",
            "MANUSIFT_CROSSREF_ENABLED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        },
    )
    # Exit code 0 is
    # expected; non-zero is
    # a regression.
    assert result.returncode == 0, (
        f"runner exit code "
        f"{result.returncode}; "
        f"stderr (last 500): "
        f"{result.stderr[-500:]}"
    )
    # Sanity check: the
    # runner wrote a
    # ``manusift_run/``
    # directory to the
    # case dir.
    run_dir = smoke_case / "manusift_run"
    assert run_dir.exists(), (
        f"runner did not write "
        f"manusift_run/ to "
        f"{smoke_case}"
    )
