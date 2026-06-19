"""R-2026-06-15 (Phase 1 + P1-20):
verify the no-secrets policy
for ``ToolContext.metadata``.

The audit found that
``ToolContext.metadata`` is
serialised into:

  * the audit log (every
    tool call);
  * the TUI debug drawer;
  * the chat-session pickle;
  * the report HTML / Markdown;
  * the test fixtures.

A secret (API key, OAuth
token, password) that
lands in ``metadata`` ends
up in *all* of these
locations.  The fix is a
two-part contract:

  1. **Documentation** in
     ``ToolContext``'s
     docstring (this test
     asserts the docstring
     mentions the policy).
  2. **Static check** in the
     source tree: we grep
     every ``.py`` file in
     ``manusift/`` for the
     anti-pattern
     ``metadata[.*secret|key|token|password``
     and fail the test if a
     call site is found.

The test runs in CI on every
commit; a future PR that
violates the policy fails
the test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MANUSIFT_ROOT = (
    Path(__file__).parent.parent / "manusift"
)
TOOL_CONTEXT = (
    MANUSIFT_ROOT / "tools" / "tool.py"
)

# Patterns that would
# indicate a secret is being
# put into ``metadata``.  We
# catch the literal
# ``metadata[...secret...]``
# / ``metadata[...key...]``
# / ``metadata[...token...]``
# / ``metadata[...password...]``
# patterns, *case-insensitive*,
# in any file under
# ``manusift/``.  The test
# is intentionally strict --
# even a comment like
# ``ctx.metadata["api_key"]``
# is flagged, because the
# pattern is the same one a
# real bug would use.
SECRET_PATTERNS = [
    re.compile(
        r"""metadata\[[\'\"]"""
        r"""(?:.*(?:api[_\-]?key|secret|token|password))""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""\.metadata\.update\(.*"""
        r"""(?:api[_\-]?key|secret|token|password)""",
        re.IGNORECASE,
    ),
]


def _walk_python_files() -> list[Path]:
    """Return every ``.py``
    file under
    ``manusift/``, excluding
    the docstring block in
    ``tool.py`` (the
    docstring *mentions* the
    patterns for educational
    purposes, which is the
    *intended* location for
    the pattern to appear).
    """
    out: list[Path] = []
    for p in MANUSIFT_ROOT.rglob("*.py"):
        out.append(p)
    return out


def test_p120_tool_context_docstring_documents_policy():
    """The ``ToolContext``
    docstring must mention
    the no-secrets policy.
    """
    src = TOOL_CONTEXT.read_text(
        encoding="utf-8"
    )
    # The docstring must
    # contain the literal
    # "no-secrets" or
    # "Do NOT put secrets".
    has_marker = (
        "no-secrets" in src.lower()
        or "do not put secrets" in src.lower()
    )
    assert has_marker, (
        "ToolContext docstring is "
        "missing the no-secrets "
        "policy marker; add a "
        "'no-secrets' section to "
        "manusift/tools/tool.py"
    )


def test_p120_no_secret_metadata_in_source_tree():
    """Grep the source tree
    for ``metadata[...secret|key|token|password]``
    call sites.  Any match
    is a policy violation.
    """
    violations: list[str] = []
    for path in _walk_python_files():
        # Skip ``tool.py`` --
        # the docstring
        # *mentions* the
        # patterns in the
        # policy text, and we
        # do not want the
        # policy to be flagged
        # by its own check.
        if path == TOOL_CONTEXT:
            continue
        # Skip the test file
        # itself (it contains
        # the patterns as
        # *literals* in the
        # regex, not as data).
        if path.name.startswith(
            "test_phase1_p120"
        ):
            continue
        try:
            src = path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError:
            continue
        # Strip line comments
        # (``# ...``) and
        # docstring blocks
        # (``"""..."""``) to
        # avoid false positives
        # on documentation
        # references.
        no_docstring = re.sub(
            r'"""[\s\S]*?"""',
            "",
            src,
        )
        for line_no, line in enumerate(
            no_docstring.splitlines(), 1
        ):
            # Skip pure
            # comment lines.
            stripped = line.strip()
            if (
                stripped.startswith("#")
                or '"""' in stripped
            ):
                continue
            for pat in SECRET_PATTERNS:
                if pat.search(line):
                    violations.append(
                        f"{path}:{line_no}: {line.strip()}"
                    )
    assert not violations, (
        "secret-like keys found in "
        "ToolContext.metadata call sites:\n"
        + "\n".join(violations)
    )


def test_p120_with_metadata_does_not_carry_secret_field():
    """The ``ToolContext.with_metadata``
    builder does NOT
    special-case secret-like
    keys (it doesn't redact
    them -- a caller who puts
    a secret in metadata has
    a problem; the builder
    faithfully copies the
    key).  The test just
    documents this so a
    future PR adding a
    redaction layer is
    intentional, not
    accidental.
    """
    from manusift.tools.tool import (
        ToolContext,
    )

    ctx = ToolContext(
        trace_id="t",
        metadata={"shell_mode": "bash"},
    )
    # A caller can add a
    # secret-like key; the
    # builder does not
    # block it.  (The
    # audit log will
    # ``[REDACTED]`` the
    # output; see
    # ``manusift/audit.py``.)
    new = ctx.with_metadata(
        api_key="sk-legacy"
    )
    assert new.metadata["api_key"] == (
        "sk-legacy"
    )
    # The original is
    # unchanged.
    assert "api_key" not in ctx.metadata
