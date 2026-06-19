"""Tests for the R-2026-06-15
(Phase 1 + P1-1.1) typed
``ToolReport`` contract.

Covers:

  * ``ToolReport.empty()``
    returns a default
    dataclass.
  * ``ToolReport.from_metadata({})``
    returns the same
    defaults.
  * ``from_metadata``
    reads each of the 7
    well-known keys
    correctly.
  * ``from_metadata``
    tolerates missing
    keys, corrupt values
    (non-list for list
    fields, non-dict for
    dict fields, etc.).
  * ``from_metadata``
    never raises.
  * ``to_metadata``
    round-trips a
    non-empty report.
  * ``with_report`` (the
    module-level helper)
    preserves unknown keys
    when
    ``preserve_unknown=True``
    (the default); drops
    them when
    ``preserve_unknown=False``.
  * ``with_merge`` merges
    two reports with the
    documented semantics
    (scalars: ``other`` wins;
    lists: concatenated).
  * The ``ToolContext.report``
    property returns a
    ``ToolReport`` (the
    derived view does
    not mutate the
    underlying metadata).
  * Each of the 3
    sub-dataclasses
    (``DataSourceInfo``,
    ``ToolCallRecord``,
    ``EvidenceAsset``)
    has a
    ``from_dict``
    classmethod that
    coerces unknown shapes
    to safe defaults.

Pattern follows the
agent-infra-iteration-
engineer skill rule I.4:
pure helpers + thin
wiring, both tested.
"""
from __future__ import annotations

from typing import Any

import pytest

from manusift.tools.report import (
    DataSourceInfo,
    EvidenceAsset,
    KEY_CONVERSATION_STATE,
    KEY_DATA_SOURCES,
    KEY_EVIDENCE_ASSETS,
    KEY_PARSED_DOC,
    KEY_PDF_PATH,
    KEY_SESSION_ID,
    KEY_TOOL_CALLS,
    ToolCallRecord,
    ToolReport,
    with_report,
)
from manusift.tools.tool import ToolContext


# --------------------------------------------------------------------
# ToolReport.empty() / from_metadata({})
# --------------------------------------------------------------------


def test_empty_report_has_all_defaults():
    r = ToolReport.empty()
    assert r.session_id is None
    assert r.pdf_path is None
    assert r.data_sources == ()
    assert r.tool_calls == ()
    assert r.evidence_assets == ()
    assert r.parsed_doc is None
    assert r.conversation_state == {}


def test_from_metadata_empty_dict_yields_empty_report():
    r = ToolReport.from_metadata({})
    assert r == ToolReport.empty()


def test_from_metadata_none_yields_empty_report():
    """``None`` (e.g. a
    ``ToolContext`` whose
    ``metadata`` was
    never set) is
    tolerated: the
    conversion returns the
    default ``ToolReport``.
    """
    r = ToolReport.from_metadata(None)
    assert r == ToolReport.empty()


def test_from_metadata_non_dict_yields_empty_report():
    """A non-dict metadata
    (e.g. the
    dataclass default
    was accidentally
    passed as a string) is
    coerced to ``{}``
    rather than raising.
    """
    r = ToolReport.from_metadata("not a dict")
    assert r == ToolReport.empty()


# --------------------------------------------------------------------
# from_metadata: each well-known key
# --------------------------------------------------------------------


def test_from_metadata_reads_session_id():
    r = ToolReport.from_metadata(
        {KEY_SESSION_ID: "abc123"}
    )
    assert r.session_id == "abc123"


def test_from_metadata_reads_pdf_path():
    r = ToolReport.from_metadata(
        {KEY_PDF_PATH: "/data/paper.pdf"}
    )
    assert r.pdf_path == "/data/paper.pdf"


def test_from_metadata_reads_parsed_doc():
    sentinel = object()
    r = ToolReport.from_metadata(
        {KEY_PARSED_DOC: sentinel}
    )
    # The parsed doc is
    # opaque (could be
    # any object); we
    # just pass it
    # through.
    assert r.parsed_doc is sentinel


def test_from_metadata_reads_data_sources():
    md = {
        KEY_DATA_SOURCES: [
            {
                "id": "ds-1",
                "format": "csv",
                "path": "/data/ds1.csv",
            },
            {
                "id": "ds-2",
                "format": "xlsx",
                "path": "/data/ds2.xlsx",
            },
        ]
    }
    r = ToolReport.from_metadata(md)
    assert len(r.data_sources) == 2
    assert r.data_sources[0].id == "ds-1"
    assert r.data_sources[0].format == "csv"
    assert r.data_sources[0].path == "/data/ds1.csv"
    assert r.data_sources[1].id == "ds-2"
    assert r.data_sources[1].format == "xlsx"


def test_from_metadata_reads_tool_calls():
    md = {
        KEY_TOOL_CALLS: [
            {
                "name": "bash",
                "input": {"command": "ls"},
                "ok": True,
                "latency_ms": 12,
                "trace_id": "t-1",
            },
            {
                "name": "ingest_from_path",
                "input": {"path": "/data/x.pdf"},
                "ok": False,
                "error_kind": "data_source_missing",
                "error": "no such file",
            },
        ]
    }
    r = ToolReport.from_metadata(md)
    assert len(r.tool_calls) == 2
    assert r.tool_calls[0].name == "bash"
    assert r.tool_calls[0].ok is True
    assert r.tool_calls[0].latency_ms == 12
    assert r.tool_calls[1].ok is False
    assert r.tool_calls[1].error_kind == (
        "data_source_missing"
    )


def test_from_metadata_reads_evidence_assets():
    md = {
        KEY_EVIDENCE_ASSETS: [
            {
                "path": "/out/fig5b_crop.png",
                "kind": "image",
                "caption": "Figure 5B crop",
                "trace_id": "t-1",
            }
        ]
    }
    r = ToolReport.from_metadata(md)
    assert len(r.evidence_assets) == 1
    assert (
        r.evidence_assets[0].path
        == "/out/fig5b_crop.png"
    )
    assert r.evidence_assets[0].kind == "image"


def test_from_metadata_reads_conversation_state():
    md = {
        KEY_CONVERSATION_STATE: {
            "turn": 5,
            "topic": "Figure 5B",
        }
    }
    r = ToolReport.from_metadata(md)
    assert r.conversation_state == {
        "turn": 5,
        "topic": "Figure 5B",
    }


# --------------------------------------------------------------------
# from_metadata: tolerance
# --------------------------------------------------------------------


def test_from_metadata_data_sources_not_list_yields_empty():
    """If the data_sources
    field is not a list
    (e.g. ``None`` or a
    string), the parser
    returns an empty
    tuple rather than
    raising.
    """
    r = ToolReport.from_metadata(
        {KEY_DATA_SOURCES: None}
    )
    assert r.data_sources == ()
    r = ToolReport.from_metadata(
        {KEY_DATA_SOURCES: "not a list"}
    )
    assert r.data_sources == ()


def test_from_metadata_data_sources_row_not_dict_is_coerced():
    """A list element that
    is not a dict (e.g.
    ``None``) becomes an
    empty
    ``DataSourceInfo``.
    """
    r = ToolReport.from_metadata(
        {KEY_DATA_SOURCES: [None, "bad", {}]}
    )
    assert len(r.data_sources) == 3
    assert r.data_sources[0].id == ""
    assert r.data_sources[1].id == ""
    # An empty dict
    # is also a valid
    # row (all-empty
    # fields).
    assert r.data_sources[2].id == ""


def test_from_metadata_conversation_state_not_dict_yields_empty():
    r = ToolReport.from_metadata(
        {KEY_CONVERSATION_STATE: "not a dict"}
    )
    assert r.conversation_state == {}


def test_from_metadata_never_raises():
    """The contract: the
    parser NEVER raises.
    A corrupt metadata
    is the tool loop's
    problem, not the
    reporter's.
    """
    # None
    ToolReport.from_metadata(None)
    # A
    # list
    ToolReport.from_metadata([1, 2, 3])
    # A
    # string
    ToolReport.from_metadata("x")
    # A
    # dict
    # with
    # garbage
    # values
    ToolReport.from_metadata(
        {
            KEY_DATA_SOURCES: "bad",
            KEY_TOOL_CALLS: 123,
            KEY_EVIDENCE_ASSETS: [None, "x"],
            KEY_CONVERSATION_STATE: [("k", "v")],
        }
    )
    # All
    # good
    # --
    # the
    # parser
    # returned
    # defaults
    # rather
    # than
    # raising.


# --------------------------------------------------------------------
# to_metadata: round-trip
# --------------------------------------------------------------------


def test_to_metadata_round_trip():
    original = ToolReport(
        session_id="abc",
        pdf_path="/data/x.pdf",
        data_sources=(
            DataSourceInfo(
                id="d1", format="csv", path="x"
            ),
        ),
        tool_calls=(
            ToolCallRecord(
                name="bash",
                input={"command": "ls"},
                ok=True,
                latency_ms=12,
                trace_id="t-1",
            ),
        ),
        evidence_assets=(
            EvidenceAsset(
                path="/out/fig.png",
                kind="image",
                caption="caption",
                trace_id="t-1",
            ),
        ),
        parsed_doc="pdf-content",
        conversation_state={
            "turn": 3,
        },
    )
    md = original.to_metadata()
    # Round-trip:
    # the
    # rebuilt
    # report
    # must
    # equal
    # the
    # original.
    rebuilt = ToolReport.from_metadata(md)
    assert rebuilt == original


def test_to_metadata_omits_unset_scalars():
    """A scalar field that
    is ``None`` is NOT
    written to the
    metadata dict. The
    parser fills in the
    default (``None``)
    when the key is
    missing.
    """
    r = ToolReport.empty()
    md = r.to_metadata()
    assert KEY_SESSION_ID not in md
    assert KEY_PDF_PATH not in md
    assert KEY_PARSED_DOC not in md


def test_to_metadata_omits_empty_lists():
    r = ToolReport.empty()
    md = r.to_metadata()
    assert KEY_DATA_SOURCES not in md
    assert KEY_TOOL_CALLS not in md
    assert KEY_EVIDENCE_ASSETS not in md
    assert KEY_CONVERSATION_STATE not in md


# --------------------------------------------------------------------
# with_report: preserve unknown keys
# --------------------------------------------------------------------


def test_with_report_preserves_unknown_keys_by_default():
    md = {
        "vector_store": "future-field",
        "session_id": "abc",
    }
    report = ToolReport(session_id="abc")
    out = with_report(md, report)
    assert out["vector_store"] == "future-field"
    assert out["session_id"] == "abc"


def test_with_report_drops_unknown_keys_when_preserve_unknown_false():
    md = {
        "vector_store": "future-field",
        "session_id": "abc",
    }
    report = ToolReport(session_id="abc")
    out = with_report(
        md, report, preserve_unknown=False
    )
    assert "vector_store" not in out
    assert out["session_id"] == "abc"


def test_with_report_does_not_mutate_input():
    md = {"session_id": "abc", "k": "v"}
    report = ToolReport(session_id="xyz")
    with_report(md, report)
    # Caller's
    # dict
    # is
    # unchanged.
    assert md == {"session_id": "abc", "k": "v"}


# --------------------------------------------------------------------
# with_merge
# --------------------------------------------------------------------


def test_with_merge_scalars_other_wins():
    a = ToolReport(session_id="a", pdf_path="p1")
    b = ToolReport(session_id="b", pdf_path="p2")
    merged = a.with_merge(b)
    # ``other`` (b) wins
    # on every scalar.
    assert merged.session_id == "b"
    assert merged.pdf_path == "p2"


def test_with_merge_scalars_other_none_falls_back_to_self():
    a = ToolReport(session_id="a", pdf_path="p1")
    b = ToolReport.empty()
    merged = a.with_merge(b)
    # ``b``'s
    # None
    # falls
    # back
    # to
    # ``a``'s
    # value.
    assert merged.session_id == "a"
    assert merged.pdf_path == "p1"


def test_with_merge_lists_concatenate():
    a = ToolReport(
        data_sources=(
            DataSourceInfo(id="d1"),
        ),
    )
    b = ToolReport(
        data_sources=(
            DataSourceInfo(id="d2"),
        ),
    )
    merged = a.with_merge(b)
    assert len(merged.data_sources) == 2
    assert merged.data_sources[0].id == "d1"
    assert merged.data_sources[1].id == "d2"


def test_with_merge_conversation_state_dicts_merged():
    a = ToolReport(
        conversation_state={"turn": 1, "topic": "x"},
    )
    b = ToolReport(
        conversation_state={"turn": 2, "next": "y"},
    )
    merged = a.with_merge(b)
    # ``b``'s
    # keys
    # win
    # on
    # conflict
    # (``turn``
    # is
    # 2,
    # not
    # 1).
    assert merged.conversation_state == {
        "turn": 2,
        "topic": "x",
        "next": "y",
    }


# --------------------------------------------------------------------
# ToolContext.report: derived view
# --------------------------------------------------------------------


def test_tool_context_report_derived_view():
    ctx = ToolContext(
        trace_id="t-1",
        metadata={
            KEY_SESSION_ID: "abc",
            KEY_PDF_PATH: "/x.pdf",
            KEY_DATA_SOURCES: [
                {"id": "d1", "format": "csv"}
            ],
        },
    )
    report = ctx.report
    assert report.session_id == "abc"
    assert report.pdf_path == "/x.pdf"
    assert len(report.data_sources) == 1
    assert report.data_sources[0].id == "d1"


def test_tool_context_report_does_not_mutate_metadata():
    """The
    ``ctx.report``
    property is a
    derived view: the
    underlying
    ``metadata``
    dict is
    unchanged.
    """
    md = {
        KEY_SESSION_ID: "abc",
    }
    ctx = ToolContext(trace_id="t-1", metadata=md)
    _ = ctx.report
    assert md == {KEY_SESSION_ID: "abc"}


def test_tool_context_report_idempotent():
    ctx = ToolContext(
        trace_id="t-1",
        metadata={KEY_SESSION_ID: "abc"},
    )
    r1 = ctx.report
    r2 = ctx.report
    # The
    # two
    # reads
    # produce
    # equal
    # (not
    # identical)
    # reports.
    assert r1 == r2


def test_tool_context_report_with_empty_metadata_returns_empty():
    ctx = ToolContext(trace_id="t-1")
    assert ctx.report == ToolReport.empty()


# --------------------------------------------------------------------
# Sub-dataclass tests
# --------------------------------------------------------------------


def test_data_source_info_from_dict_minimal():
    """A dict with no
    keys at all becomes
    an empty
    ``DataSourceInfo``.
    """
    d = DataSourceInfo.from_dict({})
    assert d == DataSourceInfo()


def test_data_source_info_to_dict_round_trip():
    d = DataSourceInfo(id="d1", format="csv", path="x")
    out = d.to_dict()
    assert out == {
        "id": "d1",
        "format": "csv",
        "path": "x",
    }
    # The
    # rebuilt
    # row
    # equals
    # the
    # original.
    assert DataSourceInfo.from_dict(out) == d


def test_data_source_info_from_dict_non_dict_yields_empty():
    assert DataSourceInfo.from_dict(None) == (
        DataSourceInfo()
    )
    assert DataSourceInfo.from_dict("x") == (
        DataSourceInfo()
    )


def test_tool_call_record_from_dict_with_optional_fields():
    """A tool call record
    can omit ``output``,
    ``error_kind``, etc.
    The default is empty
    / ``None``.
    """
    rec = ToolCallRecord.from_dict(
        {"name": "bash", "ok": True}
    )
    assert rec.name == "bash"
    assert rec.ok is True
    assert rec.error_kind == ""
    assert rec.error == ""
    assert rec.latency_ms == 0
    assert rec.output is None


def test_evidence_asset_from_dict_minimal():
    a = EvidenceAsset.from_dict(
        {"path": "/x.png"}
    )
    assert a.path == "/x.png"
    assert a.kind == ""
    assert a.caption == ""
    assert a.trace_id == ""


# --------------------------------------------------------------------
# Integration: ToolContext + with_report
# --------------------------------------------------------------------


def test_tool_context_with_new_report_updates_metadata():
    """The
    ``with_report`` helper
    is the canonical way
    to set a typed field
    on the
    ``ToolContext``.
    The original
    ``metadata`` dict is
    replaced via
    ``dataclasses.replace``.
    """
    ctx = ToolContext(
        trace_id="t-1",
        metadata={KEY_SESSION_ID: "old"},
    )
    new_report = ToolReport(session_id="new")
    new_ctx = ToolContext(
        trace_id=ctx.trace_id,
        current_pdf=ctx.current_pdf,
        metadata=with_report(
            ctx.metadata, new_report
        ),
    )
    assert new_ctx.metadata[KEY_SESSION_ID] == "new"
    # The
    # report
    # round-trips.
    assert new_ctx.report.session_id == "new"
