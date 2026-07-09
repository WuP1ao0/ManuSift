"""HTTP chat endpoint smoke tests."""
from __future__ import annotations

from starlette.testclient import TestClient

from manusift.config import Settings
from manusift.llm import MockLLM
from manusift.llm.chat import ChatResponse
from manusift.llm.client import _reset_for_tests
from manusift.web.app import create_app


class RecordingLLM:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.tool_calls: list[list[dict]] = []

    def is_available(self) -> bool:
        return True

    def analyze_finding(self, finding):
        return None

    def chat_stream(self, messages, tools=None, *, max_tokens=4096, session_id=None):
        self.calls.append([dict(m) for m in messages])
        self.tool_calls.append([dict(t) for t in (tools or [])])
        yield ChatResponse(
            content_blocks=[
                {
                    "type": "text",
                    "text": f"reply-{len(self.calls)}",
                }
            ],
            stop_reason="end_turn",
        )

    def chat(self, messages, tools=None, *, max_tokens=4096, session_id=None):
        self.calls.append([dict(m) for m in messages])
        self.tool_calls.append([dict(t) for t in (tools or [])])
        return ChatResponse(
            content_blocks=[
                {
                    "type": "text",
                    "text": f"reply-{len(self.calls)}",
                }
            ],
            stop_reason="end_turn",
        )


def test_chat_endpoint_is_in_openapi_and_preserves_session_project(tmp_path) -> None:
    _reset_for_tests(MockLLM())
    app = create_app(settings=Settings(workspace_dir=tmp_path / "jobs", rate_limit_per_minute=0))

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/chat" in paths

        response = client.post(
            "/api/chat",
            json={
                "session_id": "019ef342-3bed-75e2-817b-9563742c5d6e",
                "project_id": "manusift-local",
                "message": "please review this paper",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "019ef342-3bed-75e2-817b-9563742c5d6e"
    assert body["project_id"] == "manusift-local"
    assert body["ok"] is True
    assert "[mock echo]" in body["text"]
    assert body["turns"] >= 1


def test_chat_endpoint_accepts_camel_case_session_project(tmp_path) -> None:
    _reset_for_tests(MockLLM())
    app = create_app(settings=Settings(workspace_dir=tmp_path / "jobs", rate_limit_per_minute=0))

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "sessionId": "019ef342-3bed-75e2-817b-9563742c5d6e",
                "projectId": "manusift-local-b",
                "message": "ping",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "019ef342-3bed-75e2-817b-9563742c5d6e"
    assert body["project_id"] == "manusift-local-b"


def test_chat_endpoint_replays_prior_session_turns(tmp_path) -> None:
    llm = RecordingLLM()
    _reset_for_tests(llm)
    app = create_app(settings=Settings(workspace_dir=tmp_path / "jobs", rate_limit_per_minute=0))

    with TestClient(app) as client:
        first = client.post(
            "/api/chat",
            json={
                "sessionId": "019ef342-3bed-75e2-817b-9563742c5d6e",
                "projectId": "manusift-local-c",
                "message": "first turn",
            },
        )
        second = client.post(
            "/api/chat",
            json={
                "sessionId": "019ef342-3bed-75e2-817b-9563742c5d6e",
                "projectId": "manusift-local-d",
                "message": "second turn",
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    second_messages = llm.calls[-1]
    contents = [m.get("content") for m in second_messages]
    assert "first turn" in contents
    assert "reply-1" in contents
    assert "second turn" in contents


def test_chat_endpoint_sends_deep_review_prompt_and_tools(tmp_path) -> None:
    llm = RecordingLLM()
    _reset_for_tests(llm)
    app = create_app(settings=Settings(workspace_dir=tmp_path / "jobs", rate_limit_per_minute=0))

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "sessionId": "019ef342-3bed-75e2-817b-9563742c5d6e",
                "projectId": "manusift-local-review-boundary",
                "message": "请对这篇论文直接进行深度审查并生成完整报告",
            },
        )

    assert response.status_code == 200
    assert llm.calls
    assert llm.tool_calls
    messages = llm.calls[-1]
    system_prompt = messages[0]["content"]
    assert messages[0]["role"] == "system"
    assert "Review intent" in system_prompt
    assert "quick triage" not in system_prompt.lower()
    assert "render_report" in system_prompt
    assert "exactly one" in system_prompt.lower()

    tool_names = {tool["name"] for tool in llm.tool_calls[-1]}
    for name in (
        "ingest_from_path",
        "list_data_sources",
        "read_data_source",
        "table_relationships",
        "image_forensics",
        "render_report",
    ):
        assert name in tool_names
