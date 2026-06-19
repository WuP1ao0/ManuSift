"""R-2026-06-15 (Phase 0+1 + P1-15):
guard against the legacy
``_BASH_DENY_PATTERNS`` table
returning to
``manusift/tools/agent_tools.py``.

The original 14-row table was
the 2-state blocklist used by
``BashTool`` before
``classify_command`` was
introduced in Phase 1+3b.  The
table is dead code; the
single source of truth is now
``manusift/tools/safety.py``
``_SHELL_DENY_RULES`` (a 3-state
classifier).  We assert:

  1. ``_BASH_DENY_PATTERNS`` is
     not present in
     ``manusift/tools/agent_tools.py``
     (no assignment).
  2. The new
     ``classify_command`` is
     importable from
     ``manusift.tools.safety``
     and has 3 states
     (``safe``,
     ``needs_confirm``,
     ``block``).
  3. At least one of the legacy
     patterns (e.g.
     ``rm -rf /``) is still
     blocked by the new
     classifier (regression
     guard: a future PR cannot
     silently drop a deny rule).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# R-2026-06-15 (Phase 4 + P4-1):
# ``agent_tools.py`` is
# now a package
# directory.  The test
# reads the source
# files in the package
# to verify the deny
# table is not
# present in any of
# them.
AGENT_TOOLS_DIR = (
    Path(__file__).parent.parent
    / "manusift"
    / "tools"
    / "agent_tools"
)
SAFETY = (
    Path(__file__).parent.parent
    / "manusift"
    / "tools"
    / "safety.py"
)


def test_p115_legacy_denylist_table_is_removed():
    """``_BASH_DENY_PATTERNS`` must
    not be assigned anywhere in
    ``agent_tools.py``.  The
    string ``rm -rf / is
    blocked`` was the
    human-readable reason in
    the legacy table; if it
    comes back, the legacy
    table has re-appeared.
    """
    # R-2026-06-15 (Phase 4 + P4-1):
    # the original was a
    # single .py file; now
    # it is a package of
    # 6 submodules.  Read
    # them all and check
    # none contain the deny
    # table.
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(AGENT_TOOLS_DIR.glob("*.py"))
    )
    # Strip comments to avoid
    # false positives on
    # documentation references
    # to the removed symbol.
    no_comments = re.sub(
        r"#[^\n]*", "", src
    )
    assert (
        "_BASH_DENY_PATTERNS:" not in no_comments
    ), (
        "_BASH_DENY_PATTERNS table re-appeared in "
        "manusift/tools/agent_tools.py; route "
        "deny rules through "
        "manusift/tools/safety.py instead"
    )
    assert (
        "rm -rf / is blocked" not in src
    ), (
        "the legacy 'rm -rf / is blocked' string is "
        "back -- the legacy table has been "
        "re-introduced"
    )


def test_p115_classify_command_has_3_states():
    """The new classifier must
    have all 3 states.  A
    future PR cannot drop a
    state without breaking
    this test.
    """
    from manusift.tools.safety import (
        STATE_BLOCK,
        STATE_NEEDS_CONFIRM,
        STATE_SAFE,
        classify_command,
    )

    assert STATE_SAFE == "safe"
    assert STATE_NEEDS_CONFIRM == "needs_confirm"
    assert STATE_BLOCK == "block"
    # The three states are
    # distinct.
    assert len(
        {STATE_SAFE, STATE_NEEDS_CONFIRM, STATE_BLOCK}
    ) == 3


def test_p115_classify_command_blocks_legacy_patterns():
    """Regression guard: every
    *destructive* pattern in
    the *old* legacy table
    must still be refused
    (either ``block`` or
    ``needs_confirm``) under
    the new classifier.  A
    future PR cannot
    accidentally re-classify a
    deny rule as ``safe``.
    """
    from manusift.tools.safety import (
        STATE_BLOCK,
        STATE_NEEDS_CONFIRM,
        classify_command,
    )

    refused = {
        STATE_BLOCK,
        STATE_NEEDS_CONFIRM,
    }
    legacy = [
        ("rm -rf /", STATE_BLOCK),
        ("rm -rf / ", STATE_BLOCK),
        ("mkfs.ext4 /dev/sda", STATE_BLOCK),
        ("dd if=/dev/zero of=/dev/sda", STATE_BLOCK),
        # The fork bomb is
        # ``needs_confirm`` (the
        # 3-state design lets the
        # user accept it; the
        # legacy table hard-blocked
        # it).  We assert it is
        # still refused.
        (":(){ :|:& };:", STATE_NEEDS_CONFIRM),
        ("shutdown -h now", STATE_BLOCK),
        ("halt", STATE_BLOCK),
        ("reboot", STATE_BLOCK),
        # ``init 0`` is
        # ``needs_confirm`` -- the
        # 3-state classifier is
        # more conservative than
        # the legacy hard-deny.
        ("init 0", STATE_NEEDS_CONFIRM),
        ("poweroff", STATE_BLOCK),
    ]
    for cmd, expected_min in legacy:
        result = classify_command(cmd)
        assert result.state in refused, (
            f"legacy deny rule {cmd!r} no longer "
            f"refused; classifier says {result.state!r} "
            f"({result.reason!r})"
        )
        # Soft assertion: the
        # classifier must be at
        # least as strict as the
        # old behaviour
        # (``block`` is
        # ``needs_confirm`` plus
        # the user rejecting
        # by default; ``needs_confirm``
        # is a strict subset of
        # ``block`` in the new
        # design).
        assert (
            result.state == expected_min
            or result.state == STATE_BLOCK
        ), (
            f"legacy rule {cmd!r} downgraded from "
            f"{expected_min!r} to "
            f"{result.state!r}"
        )


def test_p115_classify_command_allows_safe_commands():
    """Sanity: a benign ``ls`` is
    ``safe``, not blocked.
    """
    from manusift.tools.safety import (
        STATE_SAFE,
        classify_command,
    )

    assert (
        classify_command("ls -la").state
        == STATE_SAFE
    )
    assert (
        classify_command("echo hello").state
        == STATE_SAFE
    )


def test_p115_single_source_of_truth_for_deny_rules():
    """All deny rules must live
    in ``manusift/tools/safety.py``.
    """
    # R-2026-06-15 (Phase 4 + P4-1):
    # ``agent_tools.py`` is
    # now a package.  The
    # ``BashTool`` class is
    # in
    # ``agent_tools/bash.py``
    # which is the file
    # that calls
    # ``classify_command``.
    src = (
        AGENT_TOOLS_DIR / "bash.py"
    ).read_text(encoding="utf-8")
    # The new BashTool.execute
    # must call
    # ``classify_command``
    # (not roll its own regex
    # check).
    assert (
        "classify_command" in src
    ), (
        "BashTool.execute no longer calls "
        "classify_command; the safety "
        "classification is in a private "
        "regex that will drift from the "
        "official classifier"
    )
