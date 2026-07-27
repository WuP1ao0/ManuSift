"""Toolserver (pi bridge) contract tests.

Replaces the former MCP stdio contract: list -> call -> error paths,
driven directly through ``serve()`` with in-memory streams.
"""
from __future__ import annotations

import io
import json

from manusift.toolserver import serve, tool_schemas


def _run(lines: list[str]) -> list[dict]:
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    serve(trace_id="t-test", stdin=stdin, stdout=stdout)
    return [
        json.loads(line)
        for line in stdout.getvalue().splitlines()
        if line.strip()
    ]


def test_ready_and_list() -> None:
    out = _run([json.dumps({"op": "list", "id": 1}), json.dumps({"op": "shutdown"})])
    assert out[0]["op"] == "ready"
    assert out[0]["tools"] > 0
    resp = out[1]
    assert resp["id"] == 1 and resp["ok"] is True
    names = [t["name"] for t in resp["tools"]]
    assert "list_dir" in names
    for t in resp["tools"]:
        assert t["input_schema"]["type"] == "object"
        assert isinstance(t["description"], str)


def test_call_list_dir(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    out = _run(
        [
            json.dumps(
                {
                    "op": "call",
                    "id": 2,
                    "tool": "list_dir",
                    "input": {"path": str(tmp_path)},
                }
            ),
            json.dumps({"op": "shutdown"}),
        ]
    )
    resp = out[1]
    assert resp["id"] == 2 and resp["ok"] is True
    payload = json.loads(resp["result"])
    text = json.dumps(payload)
    assert "a.txt" in text


def test_unknown_tool_and_op_and_bad_json() -> None:
    out = _run(
        [
            json.dumps({"op": "call", "id": 3, "tool": "no_such_tool"}),
            json.dumps({"op": "frobnicate", "id": 4}),
            "{not json",
            json.dumps({"op": "shutdown"}),
        ]
    )
    assert out[1]["ok"] is False and "unknown_tool" in out[1]["error"]
    assert out[2]["ok"] is False and "unknown_op" in out[2]["error"]
    assert out[3]["ok"] is False and out[3]["error"] == "bad_json"


def test_tool_schemas_cover_registry() -> None:
    schemas = tool_schemas()
    assert len(schemas) >= 50
    assert len({s["name"] for s in schemas}) == len(schemas)
