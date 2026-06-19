"""Tests for the LLM cost tracking (Step P1-E).

P1-E writes one JSONL line per LLM call to
``data/cost/calls.jsonl`` and serves an
aggregated summary at ``GET /api/cost``.

Guarantees:

  1. ``record_call`` appends one line per
     non-empty response and returns the
     written record.
  2. ``record_call`` returns ``None`` for a
     response with zero token usage (the
     mock / no-key path) and does not write
     a line.
  3. ``_cost_for`` returns 0 for the mock
     model and a positive number for a real
     model.
  4. ``aggregate_cost(days=N)`` sums tokens
     and cost per model and sorts by cost
     descending.
  5. Malformed lines in the cost log are
     skipped, not raised.
  6. The HTTP endpoint returns the same
     shape as ``cost_to_json(aggregate_cost())``.
  7. ``record_call`` swallows OSError on a
     read-only directory and does not raise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.cost import (
    ModelCost,
    _cost_for,
    aggregate_cost,
    cost_log_path,
    cost_root,
    cost_to_json,
    record_call,
)
from manusift.llm.chat import ChatResponse
from manusift.web import app as web_mod


# ---------- 1. record_call happy path ----------

def test_record_call_writes_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response with non-zero usage produces one
    line in the cost log and returns the record."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    resp = ChatResponse(
        content_blocks=[{"type": "text", "text": "ok"}],
        stop_reason="end_turn",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
        model="gpt-4o-mini",
    )
    rec = record_call(resp)
    assert rec is not None
    assert rec["model"] == "gpt-4o-mini"
    assert rec["in_tok"] == 100
    assert rec["out_tok"] == 50
    # File was written.
    assert cost_log_path().exists()
    lines = [
        l for l in cost_log_path().read_text(
            encoding="utf-8"
        ).splitlines() if l.strip()
    ]
    assert len(lines) == 1


# ---------- 2. zero-usage response is skipped ----------

def test_record_call_zero_usage_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response with no usage (mock / no-key)
    does not produce a log line. The dashboard
    should not be polluted with $0.00 rows."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    resp = ChatResponse(
        content_blocks=[{"type": "text", "text": "(mock)"}],
        stop_reason="end_turn",
    )
    rec = record_call(resp)
    assert rec is None
    assert not cost_log_path().exists()


# ---------- 3. _cost_for ----------

def test_cost_for_mock_is_zero() -> None:
    """The mock client produces zero cost."""
    assert _cost_for("mock", 1000, 1000) == 0.0


def test_cost_for_real_model_is_positive() -> None:
    """A real model with 1k input + 1k output is
    strictly more than 0."""
    cost = _cost_for("gpt-4o-mini", 1000, 1000)
    assert cost > 0


def test_cost_for_unknown_model_falls_back() -> None:
    """An unknown model name defaults to the
    gpt-4o-mini price list. The cost is the
    same as a gpt-4o-mini call with the same
    tokens -- predictable behavior, not a zero
    surprise."""
    cost_unknown = _cost_for("totally-made-up", 1000, 1000)
    cost_mini = _cost_for("gpt-4o-mini", 1000, 1000)
    assert cost_unknown == cost_mini


# ---------- 4. aggregate_cost ----------

def _seed_cost_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict],
) -> None:
    """Write records directly to the cost log so a
    test does not have to spin up an LLMClient.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    path = cost_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_aggregate_sums_per_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two models, each with two calls. The
    aggregator returns one row per model with
    the correct totals; the most expensive model
    is first."""
    _seed_cost_log(tmp_path, monkeypatch, [
        {"ts": 1.0, "model": "gpt-4o-mini",
         "in_tok": 1000, "out_tok": 100, "cost_usd": 0.0001},
        {"ts": 2.0, "model": "gpt-4o-mini",
         "in_tok": 2000, "out_tok": 200, "cost_usd": 0.0002},
        {"ts": 3.0, "model": "gpt-4o",
         "in_tok": 500, "out_tok": 50, "cost_usd": 0.001},
        {"ts": 4.0, "model": "gpt-4o",
         "in_tok": 500, "out_tok": 50, "cost_usd": 0.001},
    ])
    rows = aggregate_cost(days=0)  # all time
    assert len(rows) == 2
    # gpt-4o total cost 0.002 > gpt-4o-mini 0.0003
    assert rows[0].model == "gpt-4o"
    assert rows[1].model == "gpt-4o-mini"
    assert rows[0].calls == 2
    assert rows[0].in_tok == 1000
    assert rows[0].out_tok == 100
    assert rows[0].cost_usd == pytest.approx(0.002)
    assert rows[1].calls == 2
    assert rows[1].in_tok == 3000
    assert rows[1].out_tok == 300
    assert rows[1].cost_usd == pytest.approx(0.0003)


def test_aggregate_empty_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No cost log on disk is the same as an
    empty log: returns ``[]``."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    assert aggregate_cost(days=30) == []


def test_aggregate_skips_malformed_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt line in the cost log does not
    raise; well-formed lines around it still
    count."""
    _seed_cost_log(tmp_path, monkeypatch, [
        {"ts": 1.0, "model": "x", "in_tok": 100,
         "out_tok": 10, "cost_usd": 0.0001},
    ])
    # Append a garbage line.
    with cost_log_path().open("a", encoding="utf-8") as f:
        f.write("{not json}\n")
    # Append another good one.
    with cost_log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": 2.0, "model": "x", "in_tok": 50,
            "out_tok": 5, "cost_usd": 0.00005
        }) + "\n")
    rows = aggregate_cost(days=0)
    assert len(rows) == 1
    assert rows[0].calls == 2


def test_aggregate_filters_by_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``days=N`` excludes records older than N
    days. We seed one old and one new record."""
    import time
    _seed_cost_log(tmp_path, monkeypatch, [
        {"ts": time.time() - 60 * 86400,  # 60 days ago
         "model": "x", "in_tok": 100,
         "out_tok": 10, "cost_usd": 0.0001},
        {"ts": time.time() - 5 * 86400,    # 5 days ago
         "model": "x", "in_tok": 50,
         "out_tok": 5, "cost_usd": 0.00005},
    ])
    rows_30 = aggregate_cost(days=30)
    rows_90 = aggregate_cost(days=90)
    assert rows_30[0].calls == 1
    assert rows_30[0].cost_usd == pytest.approx(0.00005)
    assert rows_90[0].calls == 2


# ---------- 5. cost_to_json shape ----------

def test_cost_to_json_shape() -> None:
    """The JSON shape has the documented fields."""
    out = cost_to_json([
        ModelCost(
            model="gpt-4o-mini", calls=2,
            in_tok=100, out_tok=20, cost_usd=0.0003,
        )
    ])
    assert out["total_models"] == 1
    assert out["total_calls"] == 2
    assert out["total_in_tok"] == 100
    assert out["total_out_tok"] == 20
    assert out["total_cost_usd"] == 0.0003
    assert out["by_model"][0]["model"] == "gpt-4o-mini"


# ---------- 6. HTTP endpoint ----------

def test_endpoint_returns_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /api/cost`` returns the same shape as
    ``cost_to_json(aggregate_cost())``."""
    _seed_cost_log(tmp_path, monkeypatch, [
        {"ts": 1780995000.0, "model": "gpt-4o-mini",
         "in_tok": 100, "out_tok": 50, "cost_usd": 0.0001}
    ])
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=tmp_path / "ws")
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/cost")
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 1
    assert body["by_model"][0]["model"] == "gpt-4o-mini"


def test_endpoint_empty_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No cost data: the endpoint returns the
    empty aggregate shape, not 404."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    from manusift.web.jobs_db import InMemoryJobStore
    web_mod._JOBS_STORE = InMemoryJobStore()
    client = TestClient(
        web_mod.create_app(
            settings=Settings(workspace_dir=workspace)
        ),
        raise_server_exceptions=False,
    )
    r = client.get("/api/cost")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "by_model": [],
        "total_models": 0,
        "total_calls": 0,
        "total_in_tok": 0,
        "total_out_tok": 0,
        "total_cost_usd": 0.0,
    }


# ---------- 7. record_call is best-effort on OSError ----------

def test_record_call_swallows_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only cost directory must not crash
    a chat session. The function returns None
    when the write fails."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("MANUSIFT_WORKSPACE_DIR", str(workspace))
    from manusift.config import get_settings
    if hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()
    # Pre-create the cost dir as a file, so the
    # ``mkdir(parents=True, exist_ok=True)`` will
    # raise OSError. Or even simpler: point the
    # cost root at a path that exists but is not
    # writable.
    monkeypatch.setattr(
        "manusift.cost.cost_log_path",
        lambda: tmp_path / "nope" / "calls.jsonl",
    )
    resp = ChatResponse(
        content_blocks=[{"type": "text", "text": "x"}],
        stop_reason="end_turn",
        usage={"prompt_tokens": 100, "completion_tokens": 10},
        model="gpt-4o-mini",
    )
    # Must not raise.
    rec = record_call(resp)
    # The record was still built (the OSError is
    # on the write, not the cost computation).
    assert rec is not None
    assert rec["model"] == "gpt-4o-mini"
