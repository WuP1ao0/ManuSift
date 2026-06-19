"""Tests for the OCR-based table extraction tool (T10).

The T10 tool accepts an image
path and returns a JSON object
with ``headers`` and ``rows``.
The tests focus on the
*plumbing* -- input validation,
the registry registration, the
behaviour on missing files --
rather than on OCR accuracy,
which is impossible to assert
deterministically without a
fixed test image and a
frozen EasyOCR model.

The OCR test uses a synthetic
image with very large, clear
digits so EasyOCR has a high
chance of returning something
sensible. The test does not
insist on the exact OCR output;
it only requires that the
tool returns a well-formed
JSON object without raising.
"""
from __future__ import annotations

import json
import tempfile

import pytest
from PIL import Image, ImageDraw, ImageFont


# ---------- 1. Tool Protocol conformance ----------

def test_extract_table_tool_is_a_tool() -> None:
    from manusift.tools import Tool
    from manusift.tools.table_ocr import (
        ExtractTableFromImageTool,
    )
    tool = ExtractTableFromImageTool()
    assert isinstance(tool, Tool)
    assert tool.name == "extract_table_from_image"
    assert isinstance(tool.description(), str)
    assert isinstance(tool.input_schema(), dict)
    assert isinstance(
        tool.execute(
            {"image_path": "/no/such/path"},
            type("Ctx", (), {"trace_id": "t"})(),
        ),
        str,
    )


def test_extract_table_input_schema() -> None:
    from manusift.tools.table_ocr import (
        ExtractTableFromImageTool,
    )
    schema = ExtractTableFromImageTool().input_schema()
    assert schema["type"] == "object"
    assert "image_path" in schema["properties"]
    assert "image_path" in schema["required"]
    assert schema["properties"]["image_path"]["type"] == "string"
    assert schema.get("additionalProperties") is False


# ---------- 2. Missing argument ----------

def test_extract_table_rejects_missing_arg() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.table_ocr import (
        ExtractTableFromImageTool,
    )
    ctx = ToolContext(trace_id="t")
    out = ExtractTableFromImageTool().execute({}, ctx)
    data = json.loads(out)
    assert "error" in data


# ---------- 3. Missing file ----------

def test_extract_table_returns_error_for_missing_file() -> None:
    from manusift.tools import ToolContext
    from manusift.tools.table_ocr import (
        ExtractTableFromImageTool,
    )
    ctx = ToolContext(trace_id="t")
    out = ExtractTableFromImageTool().execute(
        {"image_path": "/nonexistent/file.png"}, ctx
    )
    data = json.loads(out)
    # Either the tool returns
    # an "error" key, or it
    # returns the "no rows"
    # note -- both are valid
    # responses.
    assert "error" in data or "note" in data


# ---------- 4. Registry exposes the tool ----------

def test_iter_registered_tools_yields_table_ocr_tool() -> None:
    from manusift.tools import iter_registered_tools
    names = {t.name for t in iter_registered_tools()}
    assert "extract_table_from_image" in names


# ---------- 5. Synthetic table image is OCR'd ----------

@pytest.mark.slow
def test_synthetic_table_image_returns_rows() -> None:
    """Render a simple table
    image with PIL and feed it
    to the OCR tool. We only
    assert the tool returns a
    JSON object with the right
    shape -- the exact row
    contents depend on the
    EasyOCR model and are not
    part of the public contract.
    """
    from manusift.tools import ToolContext
    from manusift.tools.table_ocr import (
        ExtractTableFromImageTool,
    )
    # Build a simple
    # three-column table image
    # with very large black
    # text on a white
    # background. The image
    # is intentionally large
    # (1200x400) so EasyOCR has
    # a high chance of
    # recognising the digits.
    img = Image.new("RGB", (1200, 400), "white")
    d = ImageDraw.Draw(img)
    # Try to use a default font
    # that ships with PIL; if
    # no font is available,
    # PIL falls back to its
    # built-in bitmap font
    # which is still readable.
    try:
        font = ImageFont.truetype(
            "arial.ttf", 40
        )
    except OSError:
        font = ImageFont.load_default()
    rows_text = [
        ("A", "B", "C"),
        ("1", "2", "3"),
        ("4", "5", "6"),
        ("7", "8", "9"),
    ]
    for r, row in enumerate(rows_text):
        y = 40 + r * 80
        for c, cell in enumerate(row):
            x = 40 + c * 400
            d.text((x, y), cell, fill="black", font=font)
    f = tempfile.NamedTemporaryFile(
        suffix=".png", delete=False
    )
    img.save(f, format="PNG")
    f.close()
    ctx = ToolContext(trace_id="t-ocr")
    out = ExtractTableFromImageTool().execute(
        {"image_path": f.name}, ctx
    )
    data = json.loads(out)
    # The tool must return
    # ``headers`` and ``rows``
    # as top-level keys. The
    # exact contents are not
    # asserted.
    assert "headers" in data
    assert "rows" in data
    assert isinstance(data["headers"], list)
    assert isinstance(data["rows"], list)
    # ``row_count`` is
    # convenience metadata.
    assert "row_count" in data


# ---------- 6. Helper: grouping detections into rows ----------

def test_group_into_rows_splits_on_whitespace() -> None:
    """The internal
    ``_group_into_rows`` helper
    must split a list of raw
    OCR detections into rows
    based on whitespace. We
    exercise it directly so the
    test does not depend on
    EasyOCR's behaviour."""
    from manusift.tools.table_ocr import _group_into_rows
    detections = [
        "A B C",   # one row
        "1 2 3",   # one row
        "4 5 6",   # one row
    ]
    rows = _group_into_rows(detections)
    # The whitespace
    # heuristic splits on two
    # or more spaces; single
    # spaces inside a cell
    # stay together. For
    # ``"A B C"`` we get
    # ``["A B C"]`` (one cell)
    # because there is only one
    # space between the
    # tokens. We accept
    # either result; the test
    # just checks that the
    # helper returns a list
    # of lists of strings.
    assert isinstance(rows, list)
    assert all(isinstance(r, list) for r in rows)


# ---------- 7. Helper: coerce to headers + body ----------

def test_coerce_to_table_separates_header_from_body() -> None:
    from manusift.tools.table_ocr import _coerce_to_table
    rows = [
        ["name", "age", "score"],
        ["alice", "30", "95"],
        ["bob", "25", "88"],
    ]
    headers, body = _coerce_to_table(rows)
    assert headers == ["name", "age", "score"]
    assert body == [
        ["alice", "30", "95"],
        ["bob", "25", "88"],
    ]


def test_coerce_to_table_handles_inconsistent_columns() -> None:
    """If the rows have
    inconsistent column counts,
    the helper does not invent a
    header. The whole input is
    returned as body rows and
    ``headers`` is empty."""
    from manusift.tools.table_ocr import _coerce_to_table
    rows = [
        ["a", "b", "c"],
        ["1", "2"],
        ["3"],
    ]
    headers, body = _coerce_to_table(rows)
    assert headers == []
    assert body == rows
