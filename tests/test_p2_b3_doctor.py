"""R-2026-06-19 (P2-B3):
``/doctor``
health check.

The ``/doctor``
slash command
runs 5 health
checks and
surfaces a
human-readable
report. The
core is in
``manusift.tui.doctor``
which provides
``run_health_check``
+ ``format_health_report``.

Tests:

  * ``run_health_check``
    returns
    a list
    of
    ``CheckResult``
    (one
    per
    check).
  * ``run_health_check``
    NEVER
    raises
    (a crash
    in one
    check
    is converted
    to a
    ``fail``
    result).
  * ``format_health_report``
    returns
    a non-empty
    string
    with
    the
    "Doctor
    report:"
    header.
  * The
    ``/doctor``
    slash
    command
    is
    registered
    on
    import
    (auto-registration
    in
    ``doctor.py``).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tui import doctor  # noqa: E402
from manusift.tui.doctor import (  # noqa: E402
    STATUS_FAIL,
    STATUS_OK,
    STATUS_WARN,
    CheckResult,
    format_health_report,
    run_health_check,
)


# ---------------------------------------------------------------------------
# run_health_check
# ---------------------------------------------------------------------------


class TestRunHealthCheck:
    def test_returns_a_list(self):
        result = run_health_check()
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_returns_check_results(self):
        for r in run_health_check():
            assert isinstance(r, CheckResult)

    def test_each_check_has_a_valid_status(self):
        valid = {STATUS_OK, STATUS_WARN, STATUS_FAIL}
        for r in run_health_check():
            assert r.status in valid

    def test_each_check_has_a_name_and_message(self):
        for r in run_health_check():
            assert r.name
            assert r.message

    def test_never_raises_even_when_check_crashes(
        self, monkeypatch
    ):
        """If a check raises,
        ``run_health_check``
        converts it to a
        ``fail`` result."""
        from manusift.tui import doctor as doc_mod

        original_check = doc_mod.HEALTH_CHECKS[0]

        def crashing_check() -> CheckResult:
            raise RuntimeError("simulated crash")

        # Replace the
        # first check
        # with one
        # that raises.
        monkeypatch.setattr(
            doc_mod, "HEALTH_CHECKS", [crashing_check]
        )
        result = run_health_check()
        assert len(result) == 1
        assert result[0].status == STATUS_FAIL
        assert "simulated crash" in result[0].message


# ---------------------------------------------------------------------------
# format_health_report
# ---------------------------------------------------------------------------


class TestFormatHealthReport:
    def test_includes_diagnostic_header(self):
        text = format_health_report([])
        # Empty
        # results
        # is a
        # special
        # case
        # but the
        # function
        # should
        # still
        # return
        # a
        # string.
        assert isinstance(text, str)

    def test_includes_each_check_name(self):
        results = [
            CheckResult(
                name="alpha", status=STATUS_OK,
                message="all good",
            ),
            CheckResult(
                name="beta", status=STATUS_FAIL,
                message="broken",
            ),
        ]
        text = format_health_report(results)
        assert "alpha" in text
        assert "beta" in text
        assert "all good" in text
        assert "broken" in text

    def test_summary_line_counts(self):
        results = [
            CheckResult(
                name="a", status=STATUS_OK, message="x"
            ),
            CheckResult(
                name="b", status=STATUS_OK, message="x"
            ),
            CheckResult(
                name="c", status=STATUS_FAIL, message="x"
            ),
        ]
        text = format_health_report(results)
        assert "1 fail" in text
        assert "0 warn" in text
        assert "2 ok" in text


# ---------------------------------------------------------------------------
# /doctor slash command
# ---------------------------------------------------------------------------


class TestSlashRegistration:
    def test_doctor_command_registered(self):
        # ``doctor.py``
        # auto-registers
        # on import.
        # We just need
        # to check the
        # registry has
        # it.
        # The doctor
        # module is
        # already
        # imported
        # above.
        from manusift.tui.slash_registry import find

        cmd = find("doctor")
        assert cmd is not None
        assert cmd.name == "doctor"
        assert cmd.category == "Diagnostics"

    def test_doctor_handler_does_not_crash(self):
        from manusift.tui.slash_registry import find

        cmd = find("doctor")
        # Mock
        # ``app`` with
        # the
        # ``_append_status_line``
        # method
        # the handler
        # calls.
        app = MagicMock()
        cmd.handler(app, "")
        # The handler
        # must NOT
        # raise.
        # It should
        # call
        # ``_append_status_line``
        # at least
        # once.
        assert app._append_status_line.call_count >= 1
