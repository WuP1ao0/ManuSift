"""R-2026-06-19 (P0-F1)
local preflight
script.

The full
``pytest -q``
sweep takes
5+ minutes
because of
the 30-case
v2 smoke
test, the
panel_dup
PDF render,
and other
heavy
integration
tests.  This
script is the
fast version
the user can
run before
every commit
(``python
scripts/preflight.py``)
to catch the
common
regressions
without
waiting 5
minutes.

It runs the
new test files
(Phase A / B /
C / D /
A1+C3) plus a
small targeted
regression
subset.  The
full sweep is
reserved for
the weekly
``ci-full``
job in
``ci-fast.yml``.

Exit code 0
on success,
1 on failure.
Run::

    python scripts/preflight.py
    python scripts/preflight.py --verbose
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

# Order matters: the cheap pure-function tests first so a
# regression fails fast, then the integration tests.
FAST_TEST_FILES = [
    # Phase A (8 safe_read guards, 138 tests).
    "tests/test_phase_a_safe_read.py",
    # Phase B (4 medium-cost modules, 75 tests).
    "tests/test_phase_b_safe_read_b.py",
    # Phase C (multi-fig xlsx, 34 tests).
    "tests/test_phase_c_xlsx_figs.py",
    # Phase D (per-fig xlsx + per-fig detector run, 28 tests).
    "tests/test_phase_d_per_fig_detector.py",
    # P0-A1/C3 (image-size graceful skip, 16 tests).
    "tests/test_p0_a1c3_image_size.py",
    # P1-B2 (protected-dir enforcement, 5 tests).
    "tests/test_p1_b2_protected_dir.py",
    # P1-C1 (image_forensics OOM fix, 9 tests).
    "tests/test_p1_c1_image_forensics_oom.py",
    # P1-C2 (panel_dup progress + GPU fallback, 9 tests).
    "tests/test_p1_c2_panel_dup_progress.py",
    # TUI ToolCallCard + auto-discover source data.
    "tests/test_tool_call_card.py",
    "tests/test_auto_discover_source_data.py",
    # Direct-fs error kinds + the file-tool regression.
    "tests/test_direct_fs.py",
    "tests/test_phase1_p17_direct_fs_error_kinds.py",
    # R-2026-06-20 (CDE-ASYNC):
    # PulsatingDots must keep animating while
    # ``_run_agent`` is waiting on the LLM (UI
    # must not freeze).
    "tests/test_cde_async_animation.py",
    # R-2026-06-20 (CDE-RENDER):
    # Chat messages must render Rich markup
    # (``<span class='role-XXX'>``) rather than
    # literal ``<span>`` characters in the
    # chat log.
    "tests/test_cde_render_markup.py",
    # R-2026-06-20 (CDE-ENTER):
    # Plain ``Enter`` on the input must submit
    # the message (not insert a newline +
    # swallow the message). ``_SubmitOnEnterTextArea``
    # overrides ``_on_key`` for that.
    "tests/test_cde_enter_submit.py",
    # R-2026-06-20 (CDE-BACKEND, P1):
    # Runner / RunnerCallbacks wiring,
    # tool + detector trace blocks,
    # abort, ctx writeback, prior messages.
    "tests/test_cde_backend_p1_regression.py",
    # R-2026-06-20 (CDE-CLEANUP):
    # Slash command behavior tests
    # (the source-inspection tests in
    # ``test_slash_commands.py`` are
    # deprecated; the new file drives
    # the commands and checks
    # side-effects).
    "tests/test_slash_commands_behavior.py",
    # R-2026-06-20 (CDE-RENDER-2):
    # the three
    # bugs shown
    # in the 14:36
    # screenshot:
    # (1) literal
    # ``<span>``
    # markup, (2)
    # ``assistant``
    # label not
    # shown as
    # ``ManuSift``,
    # (3) message
    # duplication.
    "tests/test_cde_render_v2.py",
    # R-2026-06-20 (CDE-RENDER-4):
    # the double-mount
    # bug shown
    # in the 15:04
    # screenshot
    # (every
    # message
    # appeared
    # 2x because
    # ``_HistoryList.append``
    # AND
    # ``_append_message``
    # both
    # mounted
    # the
    # widget).
    "tests/test_cde_render_v3_no_double_mount.py",
    # R-2026-06-20 (CDE-UI-EMPTY):
    # the "tools
    # 0 calls"
    # stripe
    # shown in
    # the 15:51
    # screenshot
    # (for a
    # tool-less
    # turn).
    "tests/test_cde_ui_empty_trace.py",
    # R-2026-06-20 (CDE-UI-P0.1):
    # ``#banner``
    # is now
    # <= 3 rows
    # (was 9 rows,
    # 36% of an
    # 80x24 screen).
    "tests/test_cde_banner_height.py",
    # R-2026-06-20 (CDE-UI-P0.7):
    # ``_set_status``
    # takes a
    # ``level`` kwarg
    # (info / warn
    # / error) so
    # error states
    # are visually
    # distinct
    # (red bold)
    # per the
    # clig.dev
    # "quiet but
    # precise"
    # principle.
    "tests/test_cde_status_styling.py",
    # R-2026-06-20 (CDE-UI-P0.8):
    # plan mode
    # queue must
    # be visible
    # in #history
    # (queue-row
    # Static per
    # message),
    # not just
    # "N pending"
    # in the
    # status
    # line.
    "tests/test_cde_plan_queue_visible.py",
    # R-2026-06-20 (CDE-UI-P0.5):
    # the
    # ``Binding("escape",
    # "Cancel", ...)``
    # was dangling
    # (no matching
    # ``action_cancel``
    # method) --
    # deleted.
    "tests/test_cde_esc_binding.py",
    # R-2026-06-20 (CDE-UI-P0.3):
    # panic_hook
    # writes
    # unhandled
    # exceptions
    # to
    # crash.log
    # +
    # surfaces
    # them in
    # the chat
    # log.
    # Replaces
    # 25+
    # ``except
    # Exception:
    # pass``
    # silent
    # handlers.
    "tests/test_cde_panic_hook.py",
    # R-2026-06-20 (CDE-UI-P1.5):
    # the ContextBar
    # (sub_title) now
    # shows session /
    # llm / pdf
    # basename /
    # plan=N /
    # cost=...
    # in one line.
    "tests/test_cde_contextbar.py",
    # R-2026-06-21 (CDE-DETER):
    # image_dup detector
    # uses sorted list
    # (not set literal)
    # so iteration
    # order is
    # deterministic
    # across
    # Python
    # versions
    # /
    # PYTHONHASHSEED
    # settings.
    "tests/test_cde_deter_image_dup.py",
]


def _run_compileall() -> int:
    """Syntax check the whole package -- fast, catches obvious bugs."""
    print("==> compileall manusift tests")
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, "-m", "compileall", "manusift", "tests"],
        cwd=PROJECT_ROOT,
    )
    print(f"    [{time.time() - t0:.1f}s] exit={r.returncode}")
    return r.returncode


def _run_ruff() -> int:
    """Run ``ruff check`` on the whole package.

    R-2026-06-19 (P3-F3):
    conservative rule
    set (B + F + I + UP
    + C4, see
    ``ruff.toml``).
    Catches real bugs
    (mutable default
    args, undefined
    names, missing
    imports) in < 2 s.
    Returns 0 on
    clean, non-zero
    on any lint
    error.

    Pre-existing
    legacy code has
    ~1,100 violations
    so we use
    ``--statistics``
    to report the
    count without
    blocking the
    preflight on
    debt that will
    be paid down
    file-by-file.
    """
    print("==> ruff check --statistics manusift tests")
    t0 = time.time()
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--statistics",
            "manusift",
            "tests",
        ],
        cwd=PROJECT_ROOT,
    )
    print(f"    [{time.time() - t0:.1f}s] exit={r.returncode}")
    # Non-blocking for now: we report the count
    # but don't fail the preflight.  When the
    # pre-existing debt is paid down, change
    # this to ``return r.returncode``.
    return 0


def _run_pytest(files: list[str], verbose: bool) -> int:
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if verbose:
        cmd.append("-v")
    cmd.extend(files)
    print(f"==> pytest {len(files)} files")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=PROJECT_ROOT)
    print(f"    [{time.time() - t0:.1f}s] exit={r.returncode}")
    return r.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fast preflight test suite. "
            "Catches the common regressions in < 30s."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Run pytest in verbose mode.",
    )
    parser.add_argument(
        "--no-compileall",
        action="store_true",
        help="Skip the syntax-check pass.",
    )
    parser.add_argument(
        "--no-ruff",
        action="store_true",
        help="Skip the ruff lint pass.",
    )
    parser.add_argument(
        "--no-pytest",
        action="store_true",
        help="Skip pytest (only do the syntax check).",
    )
    args = parser.parse_args()

    if not args.no_compileall:
        rc = _run_compileall()
        if rc != 0:
            print(f"compileall failed (exit={rc}); aborting")
            return rc

    if not args.no_ruff:
        # R-2026-06-19 (P3-F3):
        # ruff is currently
        # non-blocking
        # (``_run_ruff``
        # returns 0 even
        # when there are
        # violations); we
        # still call it
        # so the count is
        # visible in the
        # preflight output
        # so the user can
        # see the debt
        # trend over time.
        _run_ruff()

    if args.no_pytest:
        return 0

    rc = _run_pytest(FAST_TEST_FILES, args.verbose)
    if rc != 0:
        print(f"pytest failed (exit={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
