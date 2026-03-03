from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from sage_api.a2a.routes import router
from sage_api.exceptions import NotFoundError
from sage_api.models.schemas import MessageResponse, SessionInfo
from sage_api.services.session_manager import SessionManager

AUTH_HEADERS = {"X-Api-Key": "test-key"}


def make_jsonrpc_request(method: str, params: dict, request_id: str | int = "req-1") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }


def make_message_params(parts: list[dict], session_id: str | None = "session-abc") -> dict:
    payload: dict[str, object] = {
        "message": {
            "messageId": "message-1",
            "role": "user",
            "parts": parts,
        }
    }
    if session_id is not None:
        payload["sessionId"] = session_id
    return payload


async def async_chunks(*chunks: str):
    for chunk in chunks:
        yield chunk


def build_app(mock_manager: SessionManager) -> FastAPI:
    app = FastAPI()
    app.state.session_manager = mock_manager
    app.state.default_agent_name = "assistant"

    mock_agent_info = MagicMock()
    mock_agent_info.name = "assistant"
    mock_registry = MagicMock()
    mock_registry.list_agents.return_value = [mock_agent_info]
    app.state.registry = mock_registry

    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    from sage_api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_manager() -> MagicMock:
    manager = MagicMock(spec=SessionManager)
    manager.send_message = AsyncMock(return_value=MessageResponse(session_id="session-abc", message="Hi there"))
    manager.stream_message = MagicMock(return_value=async_chunks("Hello", " world"))
    manager.create_session = AsyncMock(
        return_value=SessionInfo(
            session_id="new-session",
            agent_name="assistant",
            created_at=datetime.now(timezone.utc),
            last_active_at=datetime.now(timezone.utc),
            message_count=0,
        )
    )
    return manager


@pytest.fixture
def app(mock_manager) -> FastAPI:
    return build_app(mock_manager)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def test_message_send_with_valid_session_returns_jsonrpc_result(client, mock_manager):
    body = make_jsonrpc_request(
        "message/send",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    response = client.post("/a2a", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "req-1"
    result = payload["result"]
    assert result["id"] == "session-abc"
    assert result["status"]["state"] == "completed"
    assert result["artifacts"][0]["parts"][0]["text"] == "Hi there"
    mock_manager.send_message.assert_awaited_once_with("session-abc", "hello")


def test_message_send_without_session_creates_session(client, mock_manager):
    body = make_jsonrpc_request(
        "message/send",
        make_message_params([{"kind": "text", "text": "hello"}], session_id=None),
    )
    response = client.post("/a2a", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 200
    mock_manager.create_session.assert_awaited_once_with(agent_name="assistant")
    mock_manager.send_message.assert_awaited_once_with("new-session", "hello")


@pytest.mark.asyncio
async def test_message_stream_returns_message_and_done_events(app):
    body = make_jsonrpc_request(
        "message/stream",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with ac.stream("POST", "/a2a", json=body, headers=AUTH_HEADERS) as response:
            data = await response.aread()

    assert response.status_code == 200
    assert b"event: message" in data
    assert b"event: done" in data
    assert b'"kind": "status-update"' in data
    assert b'"kind": "artifact-update"' in data
    assert b'"state": "working"' in data
    assert b'"state": "completed"' in data


def test_unknown_method_returns_jsonrpc_32601(client):
    body = make_jsonrpc_request(
        "tasks/get",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    response = client.post("/a2a", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32601
    assert payload["error"]["message"] == "Method not found"


def test_missing_api_key_returns_401(client):
    body = make_jsonrpc_request(
        "message/send",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    response = client.post("/a2a", json=body)
    assert response.status_code == 401


def test_message_send_session_not_found_maps_to_jsonrpc_error(client, mock_manager):
    mock_manager.send_message = AsyncMock(side_effect=NotFoundError("Session missing"))
    body = make_jsonrpc_request(
        "message/send",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="missing"),
    )
    response = client.post("/a2a", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"] == {"code": 404, "message": "Session missing"}


def test_message_send_extracts_only_text_parts(client, mock_manager):
    body = make_jsonrpc_request(
        "message/send",
        make_message_params(
            [
                {"kind": "text", "text": "Hello"},
                {"kind": "image", "text": "ignore"},
                {"kind": "text", "text": " world"},
            ],
            session_id="session-abc",
        ),
    )
    response = client.post("/a2a", json=body, headers=AUTH_HEADERS)

    assert response.status_code == 200
    mock_manager.send_message.assert_awaited_once_with("session-abc", "Hello world")


@pytest.mark.asyncio
async def test_message_stream_has_event_stream_content_type(app):
    body = make_jsonrpc_request(
        "message/stream",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with ac.stream("POST", "/a2a", json=body, headers=AUTH_HEADERS) as response:
            await response.aread()
            content_type = response.headers.get("content-type", "")

    assert "text/event-stream" in content_type


@pytest.mark.asyncio
async def test_message_stream_sends_failed_state_on_error(app):
    async def chunks_then_not_found():
        yield "hello"
        raise NotFoundError("gone")

    app.state.session_manager.stream_message = MagicMock(return_value=chunks_then_not_found())

    body = make_jsonrpc_request(
        "message/stream",
        make_message_params([{"kind": "text", "text": "hello"}], session_id="session-abc"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        async with ac.stream("POST", "/a2a", json=body, headers=AUTH_HEADERS) as response:
            data = await response.aread()

    assert response.status_code == 200
    assert b"event: error" in data
    assert b'"state": "failed"' in data
