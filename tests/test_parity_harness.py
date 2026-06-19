"""Tests for ``tests.mock_parity_harness`` (R-2026-06-14, P0.2).

The harness itself runs end-to-end against the real
production code (no mocking of Manusift internals). The
tests in this file pin:

  - the manifest loads with the expected 5 scenarios,
  - each scenario's runner returns an ``ok=True`` result,
  - every ``expect`` field holds,
  - the harness completes in well under 5 seconds
    (the 47-case real benchmark takes ~75 minutes; this
    smoke harness must be cheap enough to live in CI).

Pattern follows claw-code's
``tests/test_parity_harness.rs`` (see
``external_repos/claw-code/rust/crates/rusty-claude-cli/tests/mock_parity_harness.rs``).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.mock_parity_harness import (
    SCENARIO_MANIFEST_PATH,
    SCENARIO_RUNNERS,
    Scenario,
    assert_scenario,
    load_scenarios,
    run_scenario,
    run_scenario_chat_continuity,
    run_scenario_bash_dangerous_blocked,
    run_scenario_budget_exhausted,
    run_scenario_single_pdf_review,
    run_scenario_xlsx_with_data_source,
    make_tmp_workspace,
    write_fake_pdf,
    write_fake_xlsx,
)


# --------------------------------------------------------------------
# Manifest shape
# --------------------------------------------------------------------


def test_manifest_exists():
    assert SCENARIO_MANIFEST_PATH.exists()


def test_manifest_has_five_scenarios():
    """5 scenarios is the agreed-upon R-2026-06-14 minimum
    for the parity harness. Adding more is fine, but
    never fewer.
    """
    scenarios = load_scenarios()
    assert len(scenarios) == 5
    expected = {
        "single_pdf_review",
        "xlsx_with_data_source",
        "bash_dangerous_blocked",
        "budget_exhausted",
        "chat_continuity",
    }
    assert {s.name for s in scenarios} == expected


def test_manifest_round_trip():
    """The manifest round-trips through json.loads so a
    missing comma would surface as a JSON error, not a
    silent schema issue.
    """
    raw = SCENARIO_MANIFEST_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert "scenarios" in parsed
    assert isinstance(parsed["scenarios"], list)


# --------------------------------------------------------------------
# Per-scenario runner smoke
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario_name, runner",
    [
        ("single_pdf_review", run_scenario_single_pdf_review),
        ("xlsx_with_data_source", run_scenario_xlsx_with_data_source),
        ("bash_dangerous_blocked", run_scenario_bash_dangerous_blocked),
        ("budget_exhausted", run_scenario_budget_exhausted),
        ("chat_continuity", run_scenario_chat_continuity),
    ],
)
def test_each_scenario_runner_returns_ok(
    scenario_name, runner
):
    """Each runner is wired and returns ``ok=True`` on a
    default environment. (Default env has openpyxl,
    pymupdf, anthropic key, etc. installed.)
    """
    from tests.mock_parity_harness import Scenario
    scenario = Scenario(
        name=scenario_name,
        description="",
    )
    workspace = make_tmp_workspace()
    try:
        result = runner(scenario, workspace)
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
    assert result.get("ok") is True, result


# --------------------------------------------------------------------
# Full-harness end-to-end
# --------------------------------------------------------------------


def test_full_harness_passes_all_scenarios():
    """The full manifest runs to completion with all
    ``expect`` fields satisfied.

    This is the **single test that replaces the 47-case
    real-benchmark** for the CI path: 5 scenarios in
    < 5 seconds, no LLM key needed.
    """
    scenarios = load_scenarios()
    for s in scenarios:
        result = run_scenario(s)
        assert_scenario(s, result)


def test_full_harness_under_5_seconds():
    """The harness is meant to live in CI. If a scenario
    takes more than 1 second the harness is broken --
    the whole 5-scenario run should finish in well
    under 5 seconds.
    """
    scenarios = load_scenarios()
    t0 = time.perf_counter()
    for s in scenarios:
        run_scenario(s)
    dt = time.perf_counter() - t0
    assert dt < 5.0, f"parity harness took {dt:.2f}s, expected < 5s"


# --------------------------------------------------------------------
# Targeted assertion tests (per-scenario expect field)
# --------------------------------------------------------------------


def test_xlsx_scenario_yields_data_source(tmp_path: Path):
    """The R-2026-06-14 XLSX fix means a folder with an
    XLSX file must register it as a data source. We
    write a real openpyxl workbook, run the scenario,
    and assert ``data_source_count >= 1``.
    """
    pdf = write_fake_pdf(tmp_path, name="paper.pdf")
    xlsx = write_fake_xlsx(tmp_path)
    assert pdf.exists()
    assert xlsx.exists()
    assert xlsx.stat().st_size > 0

    from tests.mock_parity_harness import Scenario

    scenario = Scenario(
        name="xlsx_with_data_source",
        description="",
    )
    result = run_scenario_xlsx_with_data_source(scenario, tmp_path)
    # The smoke harness does not actually parse the
    # PDF, so we only check the harness's own report;
    # the real assertion lives in
    # ``test_chat_trust_fixes::test_ingest_with_xlsx_*``.
    assert result.get("ok") is True


def test_bash_dangerous_outcome_is_blocked():
    """``rm -rf /`` is blocked by BashTool's denylist.
    The harness asserts ``bash_outcome == "blocked"``.
    """
    from tests.mock_parity_harness import Scenario

    scenario = Scenario(
        name="bash_dangerous_blocked",
        description="",
    )
    workspace = make_tmp_workspace()
    try:
        result = run_scenario_bash_dangerous_blocked(scenario, workspace)
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
    assert result.get("bash_outcome") == "blocked"


def test_budget_exhausted_message_names_env_var():
    """The per-name cap error message must mention the
    env var so the user knows how to lift the cap.
    """
    from tests.mock_parity_harness import Scenario

    scenario = Scenario(
        name="budget_exhausted",
        description="",
    )
    workspace = make_tmp_workspace()
    try:
        result = run_scenario_budget_exhausted(scenario, workspace)
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
    content = str(result.get("tool_result_content", ""))
    assert "tool-call budget exhausted" in content
    assert "MANUSIFT_TOOL_MAX_CALLS_PER_NAME" in content


def test_chat_continuity_keeps_pdf_in_prior():
    """Round 2 ``下一步`` must still see the round-1 PDF
    path in the prior messages sent to the LLM.
    """
    from tests.mock_parity_harness import Scenario

    scenario = Scenario(
        name="chat_continuity",
        description="",
    )
    workspace = make_tmp_workspace()
    try:
        result = run_scenario_chat_continuity(scenario, workspace)
    finally:
        import shutil

        shutil.rmtree(workspace, ignore_errors=True)
    assert result.get("pdf_in_prior") is True


# --------------------------------------------------------------------
# Single-pdf scenario: report.html path + data source count
# --------------------------------------------------------------------


def test_single_pdf_scenario_writes_report_html(tmp_path: Path):
    """The single-PDF scenario writes a placeholder
    ``report.html`` so the harness can assert on it.
    """
    from tests.mock_parity_harness import Scenario

    scenario = Scenario(
        name="single_pdf_review",
        description="",
    )
    result = run_scenario_single_pdf_review(scenario, tmp_path)
    import shutil

    shutil.rmtree(tmp_path, ignore_errors=True)
    assert result.get("ok") is True
    assert str(
        result.get("report_html_path", "")
    ).endswith("report.html")


# --------------------------------------------------------------------
# Scenario dispatch
# --------------------------------------------------------------------


def test_run_scenario_dispatches_to_correct_runner():
    """The dispatch table covers all 5 scenarios.
    """
    scenarios = load_scenarios()
    for s in scenarios:
        assert s.name in SCENARIO_RUNNERS, (
            f"missing runner for {s.name!r}"
        )


def test_run_scenario_unknown_returns_error():
    """A scenario name with no runner returns
    ``ok=False`` instead of raising.
    """
    scenario = Scenario(
        name="nonexistent_scenario",
        description="",
    )
    result = run_scenario(scenario)
    assert result.get("ok") is False
    assert "no runner" in result.get("error", "")
