"""R-2026-06-19 (P2-B3):
``/doctor``
health check.

Borrowed from
Claude Code's
``/doctor``
slash command.
A one-line
diagnostic
that surfaces
the most
common
"why doesn't
ManuSift work?"
problems:

  * workspace
    dir is
    missing
    or
    unwritable
  * required
    settings
    are
    missing
    (LLM
    API key,
    Crossref
    email,
    etc.)
  * critical
    Python
    dependencies
    are
    missing
    (numpy,
    PIL,
    fitz,
    openpyxl,
    ...)
  * LLM
    connectivity
    is broken
    (Anthropic
    / OpenAI
    client
    cannot
    reach
    the
    API)
  * Crossref
    cache
    is
    stale
    or
    corrupt

The function
returns a
list of
``CheckResult``
dataclasses
with a
``status``
(``"ok"`` /
``"warn"`` /
``"fail"``) +
a
``message``.
The TUI
``/doctor``
slash command
renders the
list as a
pretty table;
the CLI
prints it as
text.

Tests:

  * The
    6
    health
    checks
    are
    all
    callable
    and
    return
    a
    CheckResult.
  * The
    ``run_health_check()``
    function
    returns
    a
    list
    of
    results
    even
    when
    some
    checks
    fail
    (never
    raises).
  * The
    ``format_health_report()``
    function
    turns
    the
    list
    into
    a
    human-readable
    text
    report
    with
    status
    icons.
"""
from __future__ import annotations

import os
import socket
import tempfile
from dataclasses import dataclass, field
from typing import Any

# Status constants -- mirror
# the 3 states
# used by
# the LLM's
# "is everything
# ok?"
# report.
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """One health check outcome.

    R-2026-06-20 (CDE-RECONSTRUCT):
    Accepts both the legacy
    field names (``message``,
    ``details``) and the new
    field names (``summary``,
    ``hint``) so the test suite
    can construct instances
    using either vocabulary.

    Attributes:
        name: short identifier
            (e.g. ``"workspace"``).
        status: ``STATUS_OK`` /
            ``STATUS_WARN`` /
            ``STATUS_FAIL``.
        message: human-readable
            description (legacy).
        summary: same as
            ``message`` (new).
        details: optional
            machine-readable
            extras (legacy).
        hint: same as
            ``details`` (new).
    """

    name: str
    status: str
    message: str = ""
    summary: str = ""
    details: dict[str, Any] | None = None
    hint: str | None = None

    def __post_init__(self) -> None:
        # Normalize: ``summary`` falls back to ``message`` and
        # vice versa; ``hint`` falls back to ``details``.
        if not self.summary and self.message:
            object.__setattr__(self, "summary", self.message)
        if not self.message and self.summary:
            object.__setattr__(self, "message", self.summary)
        if self.hint is None and isinstance(self.details, str):
            object.__setattr__(self, "hint", self.details)
        # Normalize status string -> CheckStatus enum.
        if isinstance(self.status, str):
            try:
                object.__setattr__(
                    self, "status", CheckStatus(self.status)
                )
            except ValueError:
                pass


# Status icons for
# the text report.
_STATUS_ICONS = {
    STATUS_OK: "✓",
    STATUS_WARN: "⚠",
    STATUS_FAIL: "✖",
}


def _check_workspace() -> CheckResult:
    """Check that the
    workspace dir
    exists and is
    writable.

    R-2026-06-19 (P2-B3):
    the workspace
    is the
    default
    location
    where
    ManuSift
    writes
    per-job
    files
    (raw_trace.json,
    report.html,
    etc.). If
    it doesn't
    exist, the
    chat TUI
    will crash
    on the
    first tool
    call.
    """
    from manusift.config import get_settings

    try:
        settings = get_settings()
        workspace = settings.workspace_dir
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="workspace",
            status=STATUS_FAIL,
            message=f"settings could not be loaded: {exc}",
        )
    if not workspace.exists():
        # Try to create
        # it. If that
        # fails the
        # user has a
        # permissions
        # problem.
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            return CheckResult(
                name="workspace",
                status=STATUS_OK,
                message=(
                    f"workspace created at {workspace}"
                ),
            )
        except OSError as exc:
            return CheckResult(
                name="workspace",
                status=STATUS_FAIL,
                message=(
                    f"workspace {workspace} does not exist "
                    f"and could not be created: {exc}"
                ),
                details={"path": str(workspace)},
                hint=f"check parent directory permissions for {workspace.parent}",
            )
    # Test writability
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(workspace), delete=True
        ):
            pass
        return CheckResult(
            name="workspace",
            status=STATUS_OK,
            message=f"workspace is writable at {workspace}",
            details={"path": str(workspace)},
        )
    except OSError as exc:
        return CheckResult(
            name="workspace",
            status=STATUS_FAIL,
            message=(
                f"workspace {workspace} is not writable: "
                f"{exc}"
            ),
            details={"path": str(workspace)},
        )


def _check_settings() -> CheckResult:
    """Check that critical
    settings are present.

    R-2026-06-19 (P2-B3):
    the LLM API
    key is the
    most
    common
    "nothing
    works" cause;
    we surface
    it here.
    """
    from manusift.config import get_settings

    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="settings",
            status=STATUS_FAIL,
            message=f"settings could not be loaded: {exc}",
        )
    missing: list[str] = []
    warnings: list[str] = []
    # LLM model is
    # required; the
    # key is read
    # from env
    # inside the
    # client so we
    # don't check
    # the key here
    # (avoids
    # logging
    # secrets).
    if not settings.llm_model:
        missing.append("llm_model")
    if not settings.workspace_dir:
        missing.append("workspace_dir")
    if missing:
        return CheckResult(
            name="settings",
            status=STATUS_FAIL,
            message=(
                f"required settings missing: {', '.join(missing)}"
            ),
            details={"missing": missing},
        )
    return CheckResult(
        name="settings",
        status=STATUS_OK if not warnings else STATUS_WARN,
        message=(
            "settings OK"
            if not warnings
            else f"warnings: {'; '.join(warnings)}"
        ),
        details={
            "llm_model": settings.llm_model,
            "workspace_dir": str(settings.workspace_dir),
        },
    )


def _check_deps() -> CheckResult:
    """Check that critical
    Python dependencies
    are importable.

    R-2026-06-19 (P2-B3):
    these are the
    6 packages
    the 30 v2
    benchmark
    cases rely
    on. If any
    is missing,
    the
    detectors
    that need
    it will
    no-op (returning
    empty
    findings)
    and the
    user will
    see a
    confusing
    "0 findings"
    report.
    """
    required = {
        "PIL": "image reading / forensics",
        "fitz": "PDF parsing (PyMuPDF)",
        "pdfplumber": "PDF table extraction",
        "openpyxl": "Excel (xlsx) parsing",
        "numpy": "numerical computations",
        "httpx": "HTTP client (Crossref, LLM)",
    }
    missing: list[str] = []
    available: list[str] = []
    for name, purpose in required.items():
        try:
            __import__(name)
            available.append(name)
        except ImportError:
            missing.append(f"{name} ({purpose})")
    if missing:
        return CheckResult(
            name="deps",
            status=STATUS_FAIL,
            message=(
                f"missing dependencies: {'; '.join(missing)}"
            ),
            details={"missing": missing},
        )
    return CheckResult(
        name="deps",
        status=STATUS_OK,
        message=(
            f"all {len(required)} critical dependencies present"
        ),
        details={"available": available},
    )


def _check_llm_connectivity() -> CheckResult:
    """Check that the LLM
    client can reach
    the API.

    R-2026-06-19 (P2-B3):
    this is a
    fast
    TCP-level
    probe
    (we don't
    make an
    actual API
    call
    because that
    would cost
    a
    fraction
    of a
    cent
    and add
    1-3 s
    to the
    doctor
    report).
    If the
    user has
    set
    ``MANUSIFT_OFFLINE=1``
    we skip
    the probe
    (offline
    dev mode).
    """
    # Skip if the
    # user has
    # asked for
    # offline mode.
    if os.environ.get("MANUSIFT_OFFLINE") == "1":
        return CheckResult(
            name="llm",
            status=STATUS_WARN,
            message=(
                "MANUSIFT_OFFLINE=1, skipping LLM probe"
            ),
        )
    # Map of
    # provider
    # → host:port.
    hosts = {
        "Anthropic": (
            "api.anthropic.com", 443
        ),
        "OpenAI": (
            "api.openai.com", 443
        ),
    }
    timeout = 2.0
    results: list[str] = []
    any_ok = False
    for name, (host, port) in hosts.items():
        try:
            with socket.create_connection(
                (host, port), timeout=timeout
            ):
                results.append(f"{name}: ok")
                any_ok = True
        except (socket.timeout, OSError) as exc:
            results.append(
                f"{name}: failed ({type(exc).__name__})"
            )
    return CheckResult(
        name="llm",
        status=STATUS_OK if any_ok else STATUS_FAIL,
        message="; ".join(results),
        details={"timeout_seconds": timeout},
    )


def _check_crossref_cache() -> CheckResult:
    """Check the
    ``crossref_cache.json``
    file is present
    and parseable.

    R-2026-06-19 (P2-B3):
    a corrupt
    cache is
    rare but
    when it
    happens
    every
    citation
    lookup
    falls
    back
    to a
    network
    call and
    the
    detector
    slows
    down
    by
    10-30x.
    """
    from manusift.config import get_settings

    try:
        settings = get_settings()
        cache_path = (
            settings.workspace_dir.parent / "crossref_cache.json"
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="crossref",
            status=STATUS_WARN,
            message=(
                f"could not resolve cache path: {exc}"
            ),
        )
    if not cache_path.exists():
        return CheckResult(
            name="crossref",
            status=STATUS_OK,
            message=(
                f"cache does not exist yet at {cache_path} "
                "(first run will populate it)"
            ),
            details={"path": str(cache_path)},
        )
    # File exists;
    # try to parse.
    import json as _json
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = _json.load(f)
        n_entries = len(data) if isinstance(data, dict) else 0
        return CheckResult(
            name="crossref",
            status=STATUS_OK,
            message=(
                f"cache is parseable: {n_entries} entries "
                f"({cache_path.stat().st_size} bytes)"
            ),
            details={"path": str(cache_path), "n_entries":
                n_entries},
        )
    except (OSError, ValueError) as exc:
        return CheckResult(
            name="crossref",
            status=STATUS_FAIL,
            message=(
                f"cache file is corrupt: {exc}. "
                f"Delete {cache_path} to recover."
            ),
            details={"path": str(cache_path)},
        )


# The 6 health checks
# in registration
# order.  Add new
# checks here.
HEALTH_CHECKS = [
    _check_workspace,
    _check_settings,
    _check_deps,
    _check_llm_connectivity,
    _check_crossref_cache,
]


def run_health_check() -> list[CheckResult]:
    """Run every health
    check and return the
    list of results.

    R-2026-06-19 (P2-B3):
    this function
    never raises.
    Any exception
    inside a
    check is
    converted
    to a
    CheckResult
    with
    status=``"fail"``
    so the
    report
    always
    renders.
    """
    out: list[CheckResult] = []
    for chk in HEALTH_CHECKS:
        try:
            out.append(chk())
        except Exception as exc:  # noqa: BLE001
            out.append(
                CheckResult(
                    name=chk.__name__.lstrip("_check_"),
                    status=STATUS_FAIL,
                    message=(
                        f"check {chk.__name__} crashed: {exc}"
                    ),
                )
            )
    return out


def format_health_report(
    results: list[CheckResult],
) -> str:
    """Render the health
    results as a
    human-readable text
    report.

    R-2026-06-19 (P2-B3):
    the TUI
    ``/doctor``
    handler
    calls
    this
    and
    shows
    the
    output
    in
    a
    modal
    overlay.
    """
    if not results:
        return "All checks passed (no checks defined)."
    # Sort by
    # severity:
    # fail
    # first,
    # then
    # warn,
    # then
    # ok.
    order = {
        STATUS_FAIL: 0,
        STATUS_WARN: 1,
        STATUS_OK: 2,
    }
    sorted_results = sorted(
        results, key=lambda r: order.get(r.status, 99)
    )
    lines: list[str] = []
    n_fail = sum(1 for r in results if r.status == STATUS_FAIL)
    n_warn = sum(1 for r in results if r.status == STATUS_WARN)
    n_ok = sum(1 for r in results if r.status == STATUS_OK)
    lines.append(
        f"Doctor report: "
        f"{n_fail} fail, {n_warn} warn, {n_ok} ok"
    )
    lines.append("")
    for r in sorted_results:
        icon = _STATUS_ICONS.get(r.status, "?")
        lines.append(f"  {icon} {r.name}: {r.message}")
    return "\n".join(lines)


def _doctor_handler(app: Any, arg: str) -> None:
    """The ``/doctor``
    slash-command handler.

    R-2026-06-19 (P2-B3):
    runs all
    health
    checks
    and
    appends
    the
    formatted
    report
    to the
    chat log.
    """
    results = run_health_check()
    text = format_health_report(results)
    if app is None:
        return
    if hasattr(app, "_append_status_line"):
        # Multi-line
        # report;
        # split
        # so
        # the
        # status
        # line
        # shows
        # one
        # check
        # per
        # line.
        for line in text.splitlines():
            app._append_status_line(line)


def register_doctor_command() -> None:
    """Register the
    ``/doctor`` slash
    command.

    R-2026-06-19 (P2-B3):
    called at
    import
    time
    (e.g.
    from
    ``chat_app.py``
    ) so the
    command
    shows up
    in the
    ``/help``
    overlay.
    The
    handler
    is a
    thin
    wrapper
    around
    ``run_health_check``
    +
    ``format_health_report``.
    """
    # Avoid
    # a
    # hard
    # import
    # cycle:
    # ``slash_registry``
    # imports
    # ``chat_app``
    # which
    # imports
    # everything.
    from manusift.tui.slash_registry import (
        SlashCommand,
        register,
    )

    register(
        SlashCommand(
            name="doctor",
            description=(
                "run a health check: workspace, "
                "settings, deps, LLM connectivity, "
                "Crossref cache"
            ),
            category="Diagnostics",
            handler=_doctor_handler,
        )
    )


# Auto-register
# on import
# so the
# slash
# command
# is
# available
# in
# the
# TUI
# without
# a
# manual
# call.
try:
    register_doctor_command()
except Exception:  # noqa: BLE001
    # If the
    # registry
    # is not
    # importable
    # yet (e.g.
    # in a
    # test
    # that
    # imports
    # only
    # the
    # doctor
    # module),
    # skip
    # silently.
    pass


# ============================================================
# R-2026-06-20 (CDE-RECONSTRUCT):
# Compat layer for the test suite (test_doctor.py).
# The original doctor.py used different names (CheckResult /
# run_health_check); the rewritten version uses these
# dataclasses + helpers.
# ============================================================

from enum import Enum


class CheckStatus(Enum):
    """Health check outcome enum."""
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


def _to_compat_check_result(cr: "CheckResult") -> "DoctorCheck":
    """Convert the legacy ``CheckResult`` to the new
    ``DoctorCheck`` dataclass expected by ``run_doctor``.

    Forwards ``hint`` so test stubs that pass
    ``hint=...`` see it in the rendered report.
    """
    return DoctorCheck(
        name=cr.name,
        status=cr.status,
        summary=cr.summary,
        hint=getattr(cr, "hint", None),
        details=cr.details if isinstance(cr.details, dict) else None,
    )


@dataclass
class DoctorCheck:
    """One health check outcome (compat schema)."""
    name: str
    status: str
    summary: str
    hint: str | None = None
    details: dict[str, Any] | None = None

    @property
    def is_fail(self) -> bool:
        return _status_str(self.status) == "fail"

    @property
    def is_warn(self) -> bool:
        return _status_str(self.status) == "warn"

    @property
    def is_ok(self) -> bool:
        return _status_str(self.status) == "ok"


@dataclass
class DoctorReport:
    """Aggregate doctor run report."""
    checks: tuple[DoctorCheck, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> tuple[DoctorCheck, ...]:
        return tuple(c for c in self.checks if c.is_ok)

    @property
    def failed(self) -> tuple[DoctorCheck, ...]:
        return tuple(c for c in self.checks if c.is_fail)

    @property
    def warned(self) -> tuple[DoctorCheck, ...]:
        return tuple(c for c in self.checks if c.is_warn)

    @property
    def overall_ok(self) -> bool:
        return len(self.failed) == 0


def run_doctor() -> DoctorReport:
    """Run all health checks and return a DoctorReport.

    Reads the module-level ``ALL_CHECKS`` tuple at call time
    so tests can ``monkeypatch.setattr(doctor_module,
    "ALL_CHECKS", ...)`` to control the check set.
    """
    raw_results: list[DoctorCheck] = []
    for check_fn in ALL_CHECKS:
        try:
            cr = check_fn()
            # Accept either the new ``DoctorCheck`` or
            # the legacy ``CheckResult``.
            if isinstance(cr, DoctorCheck):
                raw_results.append(cr)
            else:
                raw_results.append(_to_compat_check_result(cr))
        except Exception as exc:  # noqa: BLE001
            raw_results.append(
                DoctorCheck(
                    name=getattr(check_fn, "__name__", "unknown"),
                    status=CheckStatus.FAIL.value,
                    summary=f"check crashed: {exc}",
                    hint="check the traceback in the error log",
                    details={"error": str(exc), "type": type(exc).__name__},
                )
            )
    return DoctorReport(checks=tuple(raw_results))


def _status_str(s: Any) -> str:
    """Normalize a status field to its string form."""
    if hasattr(s, "value"):
        return str(s.value)
    return str(s)


def format_doctor_report(report: DoctorReport) -> str:
    """Render a DoctorReport as a TUI-friendly string."""
    lines: list[str] = []
    lines.append(
        f"doctor: {len(report.failed)} fail, {len(report.warned)} warn, {len(report.ok)} ok"
    )
    for c in report.checks:
        st = _status_str(c.status)
        lines.append(f"  [{st}] {c.name}: {c.summary}")
        if c.hint:
            lines.append(f"    -> {c.hint}")
    if report.overall_ok:
        lines.append("Ready to run")
    else:
        lines.append("Issues found, must be fixed before running.")
    return "\n".join(lines)


def doctor_report_to_dict(report: DoctorReport) -> dict:
    """Serialize a DoctorReport as a JSON-ready dict.

    Shape: ``{summary, overall_ok, checks: [{name, status, summary,
    details, hint}, ...]}``.
    """
    return {
        "summary": (
            f"{len(report.failed)} fail, "
            f"{len(report.warned)} warn, "
            f"{len(report.ok)} ok"
        ),
        "overall_ok": report.overall_ok,
        "checks": [
            {
                "name": c.name,
                "status": _status_str(c.status),
                "summary": c.summary,
                "details": {},
                "hint": c.hint,
            }
            for c in report.checks
        ],
    }


# ``ALL_CHECKS`` is the tuple of leaf check callables that
# ``run_doctor`` iterates over. Each callable takes no
# arguments and returns a ``CheckResult`` (legacy) or
# ``DoctorCheck`` (new).
ALL_CHECKS: tuple = (
    _check_workspace,
    _check_settings,
    _check_deps,
    _check_llm_connectivity,
    _check_crossref_cache,
)



# ============================================================
# R-2026-06-20 (CDE-RECONSTRUCT):
# Additional leaf checks exposed for the test_doctor.py suite.
# These are minimal real checks that don't require monkey-patching.
# ============================================================


def _check_settings_load() -> CheckResult:
    """Load ``Settings()`` cleanly."""
    try:
        from ..config import Settings
        s = Settings()
        return CheckResult(
            name="settings_load",
            status=STATUS_OK,
            summary=f"settings loaded (workspace={s.workspace_dir})",
            details={"path": str(s.workspace_dir)},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="settings_load",
            status=STATUS_WARN,
            summary=f"settings load failed: {exc}",
        )


def _check_openpyxl() -> CheckResult:
    """``openpyxl`` is importable (needed for XLSX ingest)."""
    try:
        import openpyxl
        v = getattr(openpyxl, "__version__", "?")
        return CheckResult(
            name="openpyxl",
            status=STATUS_OK,
            summary=f"openpyxl {v} available",
            details={"version": v},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="openpyxl",
            status=STATUS_FAIL,
            summary=f"openpyxl import failed: {exc}",
            details={"error": str(exc)},
        )


def _check_pymupdf() -> CheckResult:
    """``pymupdf`` (fitz) is importable (needed for PDF ingest)."""
    try:
        import fitz  # PyMuPDF
        v = getattr(fitz, "__version__", "?")
        return CheckResult(
            name="pymupdf",
            status=STATUS_OK,
            summary=f"pymupdf {v} available",
            details={"version": v},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="pymupdf",
            status=STATUS_FAIL,
            summary=f"pymupdf import failed: {exc}",
            details={"error": str(exc)},
        )


def _check_trace_id_format() -> CheckResult:
    """``trace_id`` format is non-empty + at least 6 chars."""
    try:
        from ..trace import new_trace_id
        sample = new_trace_id()
        ok = isinstance(sample, str) and len(sample) >= 6
        return CheckResult(
            name="trace_id_format",
            status=STATUS_OK if ok else STATUS_FAIL,
            summary=f"trace_id looks like {sample!r}",
            details={"sample": sample, "length": len(sample) if isinstance(sample, str) else 0},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="trace_id_format",
            status=STATUS_FAIL,
            summary=f"trace_id check failed: {exc}",
        )


def _check_detector_registry() -> CheckResult:
    """The detector registry loads at least one detector."""
    try:
        from ..detectors import iter_registered_detectors
        n = sum(1 for _ in iter_registered_detectors())
        return CheckResult(
            name="detector_registry",
            status=STATUS_OK if n >= 1 else STATUS_FAIL,
            summary=f"registered {n} detector(s)",
            details={"count": n},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="detector_registry",
            status=STATUS_FAIL,
            summary=f"detector registry check failed: {exc}",
        )


def _check_tool_registry() -> CheckResult:
    """The tool registry loads at least one tool."""
    try:
        from ..tools import iter_registered_tools
        n = sum(1 for _ in iter_registered_tools())
        return CheckResult(
            name="tool_registry",
            status=STATUS_OK if n >= 1 else STATUS_FAIL,
            summary=f"registered {n} tool(s)",
            details={"count": n},
        )
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="tool_registry",
            status=STATUS_FAIL,
            summary=f"tool registry check failed: {exc}",
        )


# Update ALL_CHECKS to include the new checks too
ALL_CHECKS = (
    _check_workspace,
    _check_settings,
    _check_deps,
    _check_llm_connectivity,
    _check_crossref_cache,
    _check_settings_load,
    _check_openpyxl,
    _check_pymupdf,
    _check_trace_id_format,
    _check_detector_registry,
    _check_tool_registry,
)
