"""R-2026-06-19 (P3-A5):
TUI
``[sub:...]``
rows.

The
sub-agent
forwarder
(
``manusift.tools.subagent_forwarder``
)
already
tags
events
with
``subagent_id``
in
their
payload
so
the
TUI
can
show
nested
sub-agent
activity.
P2-B1
added
the
``level``
field
to
``ToolEntry``
so
the
``ToolCallCard``
renders
a
``›``
prefix
per
level.

P3-A5
wires
the
two
together
by
adding
a
small
helper
``format_subagent_event_row(payload)``
that
returns
the
TUI
row
text
for
a
given
event
payload.
The
TUI
calls
this
when
it
sees
an
event
with
``subagent_id``
and
appends
the
row
to
the
``#history``
scrollback
above
the
nested
``ToolCallCard``.

Tests:

  * ``format_subagent_event_row``
    returns
    a
    non-empty
    string
    for
    a
    payload
    with
    ``subagent_id``.
  * The
    row
    includes
    the
    short
    sub-agent
    prefix
    (``sub:ab12``).
  * The
    row
    includes
    the
    event
    type
    and
    a
    human-readable
    description
    of
    the
    payload
    fields
    (e.g.
    ``tool_name`` /
    ``detector_name``).
  * ``format_subagent_event_row``
    returns
    ``None``
    when
    the
    payload
    has
    no
    ``subagent_id``
    (so
    the
    TUI
    can
    decide
    to
    skip
    the
    row).
"""
from __future__ import annotations

from typing import Any

import pytest

# We import
# the helper
# inline so
# the test
# file is
# self-contained
# and does
# not require
# the full
# TUI to
# be running.
import sys
sys.path.insert(0, r"C:\Users\22509\Desktop\ManuSift1")

from manusift.tools.subagent_forwarder import (  # noqa: E402
    format_subagent_event_row,
    short_subagent_prefix,
)


# ---------------------------------------------------------------------------
# format_subagent_event_row
# ---------------------------------------------------------------------------


class TestFormatSubagentEventRow:
    def test_returns_none_for_no_subagent_id(self):
        payload = {"event": "tool.started", "tool_name": "x"}
        assert format_subagent_event_row(payload) is None

    def test_returns_string_for_subagent_event(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "tool.started",
            "tool_name": "read_file",
        }
        row = format_subagent_event_row(payload)
        assert isinstance(row, str)
        assert len(row) > 0

    def test_row_contains_short_subagent_prefix(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "tool.started",
            "tool_name": "read_file",
        }
        row = format_subagent_event_row(payload)
        # ``sub:abc``
        # is the
        # 3-char
        # prefix
        # (the
        # current
        # implementation
        # uses
        # ``subagent_id[:7]``
        # = ``sub:`` + 3).
        assert "sub:abc" in row

    def test_row_contains_tool_name(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "tool.started",
            "tool_name": "read_file",
        }
        row = format_subagent_event_row(payload)
        assert "read_file" in row

    def test_row_contains_detector_name(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "detector.done",
            "detector_name": "image_dup",
        }
        row = format_subagent_event_row(payload)
        assert "image_dup" in row

    def test_row_contains_subagent_progress(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "subagent.progress",
            "tool_name": "grep",
            "detector_name": "image_dup",
        }
        row = format_subagent_event_row(payload)
        assert "sub:abc" in row

    def test_row_for_subagent_finished(self):
        payload = {
            "subagent_id": "sub:abcdef",
            "event": "subagent.finished",
            "ok": True,
        }
        row = format_subagent_event_row(payload)
        assert "sub:abc" in row
        # The
        # finished
        # row
        # shows
        # the
        # ok/fail
        # status.
        assert "ok" in row or "✓" in row or "finished" in row


# ---------------------------------------------------------------------------
# short_subagent_prefix
# ---------------------------------------------------------------------------


class TestShortSubagentPrefix:
    def test_with_sub_prefix(self):
        # Current
        # implementation
        # uses
        # ``subagent_id[:7]``
        # which
        # gives
        # ``sub:abc``
        # (sub:
        # + 3
        # hex).
        assert short_subagent_prefix("sub:abcdef") == "sub:abc"

    def test_without_sub_prefix(self):
        # Falls
        # back
        # to
        # first
        # 7
        # chars.
        assert short_subagent_prefix("abcdef") == "abcdef"
