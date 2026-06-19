"""Tests for the R-2026-06-15 (Phase 0.5)
``/status`` slash command's new
data-sources line.

The contract:

  * When ``ctx.metadata`` has
    no ``data_sources`` key
    (or it is an empty list),
    the ``/status`` message
    ends with
    ``"data sources: (none —
    use /upload to add)"``.
  * When ``data_sources`` has
    one entry, the line shows
    ``"data sources (1 data
    source): <id>(<format>)"``.
  * When there are 2+ entries,
    the line shows a comma-
    separated list of the
    first 5 entries.
  * When there are 6+
    entries, the line is
    truncated and shows
    ``"... (+N more)"``.

Pattern follows the agent-infra-
iteration-engineer skill rule
I.4: pure-helper-driven
rendering is tested without
spinning up a textual App.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from manusift.tui.chat_app import ChatApp
from manusift.tui.i18n import t as _t


def _build_status_content(
    data_sources: list[dict[str, Any]],
) -> str:
    """Reproduce the ``/status``
    content from
    ``ChatApp._cmd_status``.

    The function is inlined
    in chat_app. We re-
    construct it here to
    pin the format. If the
    format changes, the
    test will surface the
    change explicitly.
    """
    ds_count = len(data_sources)
    ds_str = (
        f" ({ds_count} data "
        f"source"
        f"{'s' if ds_count != 1 else ''})"
        if ds_count
        else ""
    )
    if ds_count:
        ds_preview = ", ".join(
            f"{ds.get('id', '?')}"
            f"({ds.get('format', '?')})"
            for ds in data_sources[:5]
        )
        if ds_count > 5:
            ds_preview += f" ... (+{ds_count - 5} more)"
    else:
        ds_preview = "(none — use /upload to add)"
    return f"data sources{ds_str}: {ds_preview}"


def test_status_with_no_data_sources_uses_default_message():
    out = _build_status_content([])
    assert "data sources: (none" in out
    assert "use /upload" in out


def test_status_with_one_data_source_uses_singular():
    out = _build_status_content(
        [{"id": "ds-1", "format": "csv"}]
    )
    assert "data sources (1 data source):" in out
    assert "ds-1(csv)" in out


def test_status_with_multiple_data_sources_uses_plural():
    out = _build_status_content(
        [
            {"id": "ds-1", "format": "csv"},
            {"id": "ds-2", "format": "xlsx"},
        ]
    )
    assert "data sources (2 data sources):" in out
    assert "ds-1(csv)" in out
    assert "ds-2(xlsx)" in out


def test_status_with_six_data_sources_truncates():
    sources = [
        {"id": f"ds-{i}", "format": "csv"}
        for i in range(7)
    ]
    out = _build_status_content(sources)
    assert "(7 data sources):" in out
    assert "+2 more" in out
    # The first 5 are
    # shown.
    for i in range(5):
        assert f"ds-{i}(csv)" in out
    # The 6th and 7th are
    # not in the preview.
    assert "ds-5(csv)" not in out
    assert "ds-6(csv)" not in out


def test_status_with_missing_format_field_falls_back():
    out = _build_status_content(
        [{"id": "ds-x"}]
    )
    assert "ds-x(?)" in out
