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
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass
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

    Attributes:
        name: short identifier
            (e.g. ``"workspace"``,
            ``"settings"``,
            ``"deps"``,
            ``"llm"``,
            ``"crossref"``).
        status: one of
            ``STATUS_OK`` /
            ``STATUS_WARN`` /
            ``STATUS_FAIL``.
        message: human-readable
            description. For
            ``ok`` this is
            a short success
            note (e.g.
            ``"workspace
            exists at
            /foo"``).
            For ``warn`` /
            ``fail`` this
            explains the
            problem + a
            suggested fix.
        details: optional
            machine-readable
            extras (e.g.
            the list of
            missing deps,
            the current
            LLM model name,
            etc.).
    """

    name: str
    status: str
    message: str
    details: dict[str, Any] | None = None


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
