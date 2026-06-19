"""R-2026-06-19 (P2-B4):
``/diff``
slash command.

Borrowed from
Claude Code's
``/diff``
command.
The user
types::

    /diff path_a/foo.py path_b/bar.py
    /diff path/some.py
    /diff path/some.py new_content=line1\\nline2

and the TUI
shows a
unified
diff in a
modal
overlay.

The actual
diff
computation
is in
``manusift.tools.agent_tools.diff.DiffTool``
(P2-B5); this
module is
just the
slash-command
adapter that
parses the
arg string
and calls
the tool.

Tests:

  * The
    ``/diff``
    command
    is
    registered
    on
    import.
  * The
    handler
    correctly
    parses
    two
    paths
    (``/diff
    a b``).
  * The
    handler
    correctly
    parses
    one
    path
    + content
    (``/diff
    a
    new_content=...``).
  * The
    handler
    never
    raises
    on
    bad
    input.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Avoid a hard
# import cycle
# at module
# import time:
# ``slash_registry``
# is imported
# inside
# ``register_diff_command``.


# R-2026-06-19 (P2-B4):
# the
# ``new_content=...``
# argument can
# be multi-line;
# the user
# writes the
# value after
# ``=`` and the
# rest of the
# arg is the
# content.  We
# support both
# inline
# (``new_content=line1\nline2``)
# and
# quoted
# (``new_content="line1\nline2"``)
# forms.

# Pattern: capture
# ``new_content=...``
# at the end
# of the
# arg string.
_NEW_CONTENT_RE = re.compile(
    r"^(?P<path>\S+)\s+new_content=(?P<content>.*)$",
    re.DOTALL,
)


def _parse_diff_arg(arg: str) -> dict[str, str]:
    """Parse a ``/diff``
    command arg into
    a ``DiffTool``
    input dict.

    R-2026-06-19 (P2-B4):
    three forms
    are supported:

      1. ``/diff
         <path_a>
         <path_b>``
         -- two
         files
         on
         disk.
      2. ``/diff
         <path>
         new_content=<content>``
         -- file
         vs
         string.
      3. ``/diff
         <path_a>
         <path_b>
         new_content=<content>``
         -- file
         vs
         string
         with
         a
         custom
         fromfile/tofile
         label
         (the
         content
         is
         ignored
         for
         the
         diff
         but
         we
         accept
         it
         for
         forward
         compat).
    """
    arg = arg.strip()
    if not arg:
        return {}
    # First check
    # for the
    # ``new_content=...``
    # form.
    m = _NEW_CONTENT_RE.match(arg)
    if m:
        content = m.group("content")
        # Strip
        # quotes
        # if
        # present.
        if (
            len(content) >= 2
            and content[0] == content[-1]
            and content[0] in ('"', "'")
        ):
            content = content[1:-1]
        return {
            "path": m.group("path"),
            "new_content": content,
        }
    # Otherwise,
    # treat as
    # space-separated
    # paths.
    parts = arg.split()
    if len(parts) == 1:
        return {"path": parts[0]}
    if len(parts) >= 2:
        return {
            "path_a": parts[0],
            "path_b": parts[1],
        }
    return {}


def _diff_handler(app: Any, arg: str) -> None:
    """The ``/diff``
    slash-command handler.

    R-2026-06-19 (P2-B4):
    parses the
    arg, calls
    ``DiffTool``
    with the
    parsed
    input,
    and
    appends
    the
    diff
    (or
    an
    error
    message)
    to the
    chat
    log.
    """
    parsed = _parse_diff_arg(arg)
    if not parsed:
        if app is not None and hasattr(app, "_append_status_line"):
            app._append_status_line(
                "usage: /diff <path_a> <path_b>  OR  "
                "/diff <path> new_content=<content>"
            )
        return
    # Import
    # inside
    # the
    # handler
    # to
    # avoid
    # a
    # hard
    # dependency
    # on
    # the
    # tool
    # layer
    # (some
    # test
    # harnesses
    # may
    # import
    # the
    # slash
    # command
    # without
    # the
    # tool
    # layer).
    try:
        from manusift.tools.agent_tools.diff import DiffTool
        from manusift.tools.tool import ToolContext
    except ImportError as exc:  # noqa: BLE001
        if app is not None and hasattr(
            app, "_append_status_line"
        ):
            app._append_status_line(
                f"/diff: tool layer unavailable: {exc}"
            )
        return
    # Build
    # a
    # ToolContext.
    # We don't have
    # a real
    # one in
    # a
    # slash-command
    # context;
    # create
    # a
    # minimal
    # one.
    trace_id = ""
    if app is not None and hasattr(app, "_current_trace_id"):
        trace_id = str(app._current_trace_id())
    try:
        ctx = ToolContext(
            trace_id=trace_id or "diff-cli",
            current_pdf="",
            metadata={},
        )
    except Exception:  # noqa: BLE001
        ctx = None
    if ctx is None:
        # ToolContext
        # is required;
        # if it can't
        # be built,
        # surface
        # a
        # status-line
        # error.
        if app is not None and hasattr(
            app, "_append_status_line"
        ):
            app._append_status_line(
                "/diff: ToolContext unavailable"
            )
        return
    # Run
    # the
    # tool.
    try:
        raw = DiffTool().execute(parsed, ctx)
    except Exception as exc:  # noqa: BLE001
        if app is not None and hasattr(
            app, "_append_status_line"
        ):
            app._append_status_line(
                f"/diff: tool crashed: {exc}"
            )
        return
    # Parse
    # the
    # JSON
    # response.
    try:
        envelope = json.loads(raw)
    except ValueError:
        envelope = {"ok": False, "error": raw}
    if not envelope.get("ok"):
        err = envelope.get("error", "unknown error")
        if app is not None and hasattr(
            app, "_append_status_line"
        ):
            app._append_status_line(f"/diff: {err}")
        return
    diff_text = envelope.get("diff", "")
    if not diff_text:
        # No
        # diff
        # (files
        # are
        # identical
        # or
        # one
        # is
        # empty).
        if app is not None and hasattr(
            app, "_append_status_line"
        ):
            app._append_status_line(
                f"/diff: no changes between "
                f"{envelope.get('fromfile')} and "
                f"{envelope.get('tofile')}"
            )
        return
    # Render
    # the
    # diff
    # line
    # by
    # line
    # so
    # each
    # ``+``/``-``
    # line
    # shows
    # up
    # as
    # its
    # own
    # status-line
    # entry.
    n_added = envelope.get("n_added", 0)
    n_removed = envelope.get("n_removed", 0)
    if app is not None and hasattr(
        app, "_append_status_line"
    ):
        app._append_status_line(
            f"/diff: +{n_added} -{n_removed} "
            f"({envelope.get('fromfile')} -> "
            f"{envelope.get('tofile')})"
        )
        for line in diff_text.splitlines():
            app._append_status_line(line)


def register_diff_command() -> None:
    """Register the
    ``/diff`` slash
    command.

    R-2026-06-19 (P2-B4):
    called at
    import
    time
    so the
    command
    is in
    the
    registry
    before
    the
    TUI
    starts
    building
    its
    command
    palette.
    """
    try:
        from manusift.tui.slash_registry import (
            SlashCommand,
            register,
        )
    except ImportError:
        return
    register(
        SlashCommand(
            name="diff",
            description=(
                "show a unified diff between two files "
                "or a file and a proposed new content"
            ),
            category="Help",
            handler=_diff_handler,
            aliases=("d",),
        )
    )


# Auto-register
# on import.
try:
    register_diff_command()
except Exception:  # noqa: BLE001
    pass
