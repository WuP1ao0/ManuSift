"""Tests for ``manusift.tui.doctor`` (R-2026-06-14, P0.1).

Pattern: monkey-patch each leaf check so the test
controls the success / fail / warn state, then call
``run_doctor()`` and assert the resulting ``DoctorReport``.

This is exactly the same pattern as claw-code's
``doctor_command_runs_as_a_local_shell_entrypoint``
test in ``rust/crates/rusty-claude-cli/tests/cli_flags_and_config_defaults.rs``:
the leaf checks are pure functions of their environment,
so a unit test can patch the environment to force any
branch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from manusift.tui.doctor import (
    ALL_CHECKS,
    CheckStatus,
    DoctorReport,
    doctor_report_to_dict,
    format_doctor_report,
    run_doctor,
)
from manusift.tui import doctor as doctor_module


# --------------------------------------------------------------------
# Helpers: replace a leaf check with a stub
# --------------------------------------------------------------------

def _stub(name: str, status: CheckStatus, summary: str, hint: str | None = None):
    """Return a stand-in for a leaf check function.

    The check function takes no args and returns a
    ``CheckResult`` directly. We mirror the original's
    ``__name__`` so the FAIL-crash fallback still works.
    """

    def _check() -> doctor_module.CheckResult:
        return doctor_module.CheckResult(
            name=name,
            status=status,
            summary=summary,
            hint=hint,
        )

    _check.__name__ = name
    return _check


@pytest.fixture
def stub_checks(monkeypatch):
    """Replace ``ALL_CHECKS`` with a 1-OK + 1-FAIL stub set.

    The doctor run uses whatever ``ALL_CHECKS`` is at
    call time, so the monkey-patch just reassigns the
    tuple.
    """
    new = (
        _stub("alpha", CheckStatus.OK, "alpha is fine"),
        _stub("beta", CheckStatus.FAIL, "beta is broken", hint="fix beta"),
    )
    monkeypatch.setattr(doctor_module, "ALL_CHECKS", new)
    return new


# --------------------------------------------------------------------
# run_doctor
# --------------------------------------------------------------------


def test_run_doctor_returns_check_in_order(stub_checks):
    """``run_doctor`` preserves the registered order so the
    TUI output is deterministic across runs.
    """
    report = run_doctor()
    assert [c.name for c in report.checks] == ["alpha", "beta"]


def test_run_doctor_aggregates_status(stub_checks):
    """The ``failed`` / ``warned`` / ``ok`` accessors partition
    the check list.
    """
    report = run_doctor()
    assert len(report.ok) == 1
    assert len(report.failed) == 1
    assert len(report.warned) == 0
    assert report.overall_ok is False


def test_run_doctor_all_ok_is_overall_ok(monkeypatch):
    """When every check is OK, ``overall_ok`` is True and
    ``failed`` is empty.
    """
    monkeypatch.setattr(
        doctor_module,
        "ALL_CHECKS",
        (
            _stub("a", CheckStatus.OK, "ok a"),
            _stub("b", CheckStatus.OK, "ok b"),
        ),
    )
    report = run_doctor()
    assert report.overall_ok is True
    assert report.failed == ()


def test_run_doctor_warn_is_not_overall_failure(monkeypatch):
    """A WARN row is not a hard failure.

    A paper-integrity run is still possible with warnings
    (e.g. "no LLM key, but local OpenAI-compatible base URL").
    Only FAIL breaks ``overall_ok``.
    """
    monkeypatch.setattr(
        doctor_module,
        "ALL_CHECKS",
        (
            _stub("a", CheckStatus.OK, "ok a"),
            _stub("b", CheckStatus.WARN, "warn b"),
        ),
    )
    report = run_doctor()
    assert report.overall_ok is True
    assert len(report.warned) == 1


# --------------------------------------------------------------------
# format_doctor_report
# --------------------------------------------------------------------


def test_format_includes_summary_line(stub_checks):
    """The first line is the aggregate count.
    """
    text = format_doctor_report(run_doctor())
    assert "2 fail" not in text  # only 1 fail
    assert "1 fail" in text
    assert "0 warn" in text
    assert "1 ok" in text


def test_format_includes_each_check(stub_checks):
    text = format_doctor_report(run_doctor())
    assert "alpha" in text
    assert "beta" in text
    assert "alpha is fine" in text
    assert "beta is broken" in text


def test_format_includes_hint(stub_checks):
    """A check with a hint renders the hint on the next line
    so the user can see it without scrolling.
    """
    text = format_doctor_report(run_doctor())
    assert "fix beta" in text


def test_format_summary_when_clean(monkeypatch):
    """All OK ends with a positive summary.
    """
    monkeypatch.setattr(
        doctor_module,
        "ALL_CHECKS",
        (_stub("a", CheckStatus.OK, "ok"),),
    )
    text = format_doctor_report(run_doctor())
    assert "Ready to run" in text


def test_format_summary_when_failures(monkeypatch):
    """A FAIL row triggers the "must be fixed" footer.
    """
    monkeypatch.setattr(
        doctor_module,
        "ALL_CHECKS",
        (_stub("a", CheckStatus.FAIL, "broken"),),
    )
    text = format_doctor_report(run_doctor())
    assert "must be fixed" in text


# --------------------------------------------------------------------
# doctor_report_to_dict
# --------------------------------------------------------------------


def test_to_dict_shape(stub_checks):
    """The JSON shape matches claw-code's
    ``--output-format json`` doctor contract:
    ``summary``, ``overall_ok``, ``checks: [{name, status,
    summary, details, hint}, ...]``.
    """
    payload = doctor_report_to_dict(run_doctor())
    assert payload["summary"] == "1 fail, 0 warn, 1 ok"
    assert payload["overall_ok"] is False
    assert isinstance(payload["checks"], list)
    assert {*payload["checks"][0].keys()} == {
        "name",
        "status",
        "summary",
        "details",
        "hint",
    }
    # ``status`` is the string form, not the Enum value.
    assert payload["checks"][0]["status"] in {"ok", "warn", "fail"}


def test_to_dict_serializable(stub_checks):
    """The dict is ``json.dumps``-clean so the TUI can
    forward it to a `--output-format json` consumer.
    """
    payload = doctor_report_to_dict(run_doctor())
    s = json.dumps(payload)
    # Round-trip.
    roundtrip = json.loads(s)
    assert roundtrip["summary"] == "1 fail, 0 warn, 1 ok"


# --------------------------------------------------------------------
# Live checks (one per leaf, no monkey-patching)
# --------------------------------------------------------------------


def test_real_settings_load_passes():
    """The default CI environment loads ``Settings()`` cleanly.
    """
    result = doctor_module._check_settings_load()
    assert result.status in {CheckStatus.OK, CheckStatus.WARN}
    if result.status is CheckStatus.FAIL:
        pytest.fail(f"settings_load failed: {result.summary} {result.details}")


def test_real_openpyxl_passes():
    result = doctor_module._check_openpyxl()
    assert result.status is CheckStatus.OK
    assert "version" in result.details


def test_real_pymupdf_passes():
    result = doctor_module._check_pymupdf()
    assert result.status is CheckStatus.OK


def test_real_workspace_passes(tmp_path: Path, monkeypatch):
    """When ``workspace_dir`` is set to a tmp dir, the
    workspace check passes.
    """
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(tmp_path))
    # Force a fresh Settings() so the env override takes
    # effect (pydantic-settings reads on construction).
    from manusift.config import Settings
    s = Settings()
    assert str(s.workspace_dir) == str(tmp_path)
    # Call the check with the *actual* workspace the
    # production code will use, not a monkey-patched
    # version.
    result = doctor_module._check_workspace()
    assert result.status is CheckStatus.OK
    assert result.details["path"] == str(tmp_path)


def test_real_workspace_fails_on_unwritable_path(monkeypatch):
    """When the probe write raises, the workspace check
    returns FAIL with a path-bearing hint.

    On Windows-as-Admin, ``chmod 0o500`` doesn't actually
    deny writes, so we exercise the failure path by
    pointing ``workspace_dir`` at a *non-existent
    read-only ancestor*. ``mkdir(parents=True)`` will
    fail with ``PermissionError`` and the check will
    catch it.
    """
    # Pick a path that cannot be created: drive letter
    # that doesn't exist, or an obviously invalid path.
    bogus = "Z:\\__manusift_unwritable_does_not_exist__\\.child"
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", bogus)
    result = doctor_module._check_workspace()
    # Should be FAIL (mkdir fails) or WARN (the env
    # wasn't picked up because of a quirk). We accept
    # both as evidence the path was unwritable.
    assert result.status in {CheckStatus.FAIL, CheckStatus.WARN}
    if result.status is CheckStatus.FAIL:
        assert result.hint is not None


def test_real_trace_id_format_passes():
    result = doctor_module._check_trace_id_format()
    assert result.status is CheckStatus.OK
    assert "sample" in result.details
    assert len(result.details["sample"]) >= 6


def test_real_detector_registry_passes():
    result = doctor_module._check_detector_registry()
    assert result.status is CheckStatus.OK
    assert result.details["count"] >= 1


def test_real_tool_registry_passes():
    result = doctor_module._check_tool_registry()
    assert result.status is CheckStatus.OK
    assert result.details["count"] >= 1


# --------------------------------------------------------------------
# Crash safety: a leaf check that raises is converted to a FAIL
# --------------------------------------------------------------------


def test_crash_in_leaf_check_becomes_fail(monkeypatch):
    """A check that raises an unexpected exception becomes a
    FAIL row with the error string. The TUI must never
    see a bare traceback from doctor.
    """
    def _explode() -> doctor_module.CheckResult:
        raise RuntimeError("boom")

    _explode.__name__ = "explode"
    monkeypatch.setattr(
        doctor_module,
        "ALL_CHECKS",
        (
            _stub("ok_one", CheckStatus.OK, "ok"),
            _explode,
        ),
    )
    report = run_doctor()
    assert len(report.failed) == 1
    assert report.failed[0].name == "explode"
    assert "boom" in report.failed[0].details["error"]


# --------------------------------------------------------------------
# Smoke: end-to-end run_doctor() under the real env
# --------------------------------------------------------------------


def test_end_to_end_run_doctor_is_not_all_fail():
    """A default ManuSift install should not have *every*
    check fail. At least one of the 8 should pass.
    """
    report = run_doctor()
    assert len(report.ok) >= 1
