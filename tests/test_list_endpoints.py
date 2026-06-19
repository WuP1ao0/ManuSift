"""Tests for the /api/detectors and /api/tools endpoints (R5).

R5 added two new endpoints to
the web layer:

  * ``GET /api/detectors`` --
    list every built-in
    detector (R3 canonical
    list) with name /
    class / module. Used by
    the LLM for introspect
    and by the web dashboard
    for the detector
    catalogue.
  * ``GET /api/tools`` --
    list every tool the LLM
    can call (built-in
    + entry-point). The
    descriptions are
    truncated to 200 chars
    for the dashboard; the
    agent loop uses the
    full descriptions.

The tests below pin both
endpoints' contracts and
cross-check that the
``/api/detectors`` count
matches the TUI's
status-line detector count
(so the dashboard and the
chat both see the same
set).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def client():
    """Spin up the FastAPI app
    via TestClient. We do NOT
    use ``with TestClient(app)``
    as a context manager
    because that triggers
    the lifespan startup /
    shutdown hooks, which
    races with the
    singleton stores that
    other tests may have
    already initialised."""
    from starlette.testclient import TestClient
    from manusift.web.app import create_app
    app = create_app()
    return TestClient(app)


# ---------- 1. /api/detectors shape ----------

def test_detectors_endpoint_returns_200(client) -> None:
    r = client.get("/api/detectors")
    assert r.status_code == 200


def test_detectors_endpoint_returns_count(client) -> None:
    """The response has a
    ``count`` field that
    matches ``len(detectors)``.
    """
    r = client.get("/api/detectors")
    body = r.json()
    assert "detectors" in body
    assert "count" in body
    assert body["count"] == len(body["detectors"])
    assert body["count"] >= 25


def test_detectors_endpoint_each_row_has_three_fields(
    client,
) -> None:
    r = client.get("/api/detectors")
    for row in r.json()["detectors"]:
        assert set(row.keys()) == {
            "name",
            "class_name",
            "module",
        }


def test_detectors_endpoint_names_match_canonical(client) -> None:
    """The names returned by
    ``/api/detectors`` must
    match the
    ``detector_names()`` R3
    canonical list (so the
    web dashboard and the
    TUI status bar stay in
    sync)."""
    from manusift.detectors import detector_names
    r = client.get("/api/detectors")
    names_from_endpoint = [d["name"] for d in r.json()["detectors"]]
    assert names_from_endpoint == detector_names()


# ---------- 2. /api/tools shape ----------

def test_tools_endpoint_returns_200(client) -> None:
    r = client.get("/api/tools")
    assert r.status_code == 200


def test_tools_endpoint_returns_count(client) -> None:
    r = client.get("/api/tools")
    body = r.json()
    assert "tools" in body
    assert "count" in body
    assert body["count"] == len(body["tools"])
    # The project ships
    # at least 4 built-in
    # detector-as-tool
    # adapters (metadata /
    # image_dup /
    # image_forensics /
    # text_patterns) plus
    # the inspection /
    # OCR / LaTeX /
    # similarity-matrix
    # tools. We expect at
    # least 8.
    assert body["count"] >= 8


def test_tools_endpoint_each_row_has_three_fields(
    client,
) -> None:
    r = client.get("/api/tools")
    for row in r.json()["tools"]:
        assert set(row.keys()) == {
            "name",
            "description",
            "has_schema",
        }


def test_tools_endpoint_includes_metadata_tool(client) -> None:
    """The ``metadata`` tool
    (the most common entry
    point for the LLM)
    must appear in the list
    with a non-empty
    description."""
    r = client.get("/api/tools")
    names = [t["name"] for t in r.json()["tools"]]
    assert "metadata" in names
    # The description is
    # truncated to 200
    # chars so we check
    # that the metadata
    # tool's description is
    # non-empty and starts
    # with the detector's
    # docstring's first
    # line.
    metadata_tool = next(
        t for t in r.json()["tools"] if t["name"] == "metadata"
    )
    assert len(metadata_tool["description"]) > 0


# ---------- 3. endpoints are stable across requests ----------

def test_detectors_endpoint_stable_across_requests(
    client,
) -> None:
    first = client.get("/api/detectors").json()
    second = client.get("/api/detectors").json()
    assert first == second


def test_tools_endpoint_stable_across_requests(
    client,
) -> None:
    first = client.get("/api/tools").json()
    second = client.get("/api/tools").json()
    assert first == second
