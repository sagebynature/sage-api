"""Tests for message sending REST endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from sage_api.api.messages import router
from sage_api.models.schemas import MessageResponse, SessionInfo, UsageInfo
from sage_api.services.session_manager import SessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-api-key-12345"
AUTH_HEADERS = {"X-Api-Key": TEST_API_KEY}


def make_message_response(
    session_id: str = "session-abc",
    message: str = "Hello from agent",
) -> MessageResponse:
    return MessageResponse(session_id=session_id, message=message)


async def async_chunks(*chunks: str):
    """Async generator that yields string chunks."""
    for chunk in chunks:
        yield chunk


def build_app(mock_manager: SessionManager) -> FastAPI:
    """Build minimal FastAPI app with the messages router and mock manager."""
    app = FastAPI()
    app.state.session_manager = mock_manager
    app.include_router(router)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setenv("SAGE_API_API_KEY", TEST_API_KEY)
    from sage_api.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_manager() -> MagicMock:
    session = SessionInfo(
        session_id="session-abc",
        agent_name="my-agent",
        created_at=datetime.now(timezone.utc),
        last_active_at=datetime.now(timezone.utc),
        message_count=0,
        duration_seconds=0.0,
        usage=UsageInfo(),
        model=None,
        context_window_utilization=None,
    )
    manager = MagicMock(spec=SessionManager)
    manager.send_message = AsyncMock(return_value=make_message_response())
    manager.stream_message = MagicMock(return_value=async_chunks("Hello", " world"))
    manager.get_session = AsyncMock(return_value=session)
    return manager


@pytest.fixture
def app(mock_manager) -> FastAPI:
    return build_app(mock_manager)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests — POST /v1/agents/{name}/messages
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_send_message_success_returns_200(self, client):
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

    def test_send_message_success_returns_message_response(self, client):
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        data = response.json()
        assert data["session_id"] == "session-abc"
        assert data["message"] == "Hello from agent"

    def test_send_message_calls_manager_with_correct_args(self, client, mock_manager):
        client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Test message"},
            headers=AUTH_HEADERS,
        )
        mock_manager.send_message.assert_awaited_once_with(
            session_id="session-abc",
            message="Test message",
        )

    def test_send_message_missing_session_returns_404(self, client, mock_manager):
        mock_manager.send_message = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Session 'missing' not found")
        )
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "missing", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_send_message_conflict_returns_409(self, client, mock_manager):
        mock_manager.send_message = AsyncMock(
            side_effect=HTTPException(status_code=409, detail="Concurrent request to same session")
        )
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 409

    def test_send_message_timeout_returns_504(self, client, mock_manager):
        mock_manager.send_message = AsyncMock(side_effect=HTTPException(status_code=504, detail="Request timed out"))
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 504

    def test_send_message_without_auth_returns_401(self, client):
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
        )
        assert response.status_code == 401

    def test_send_message_wrong_agent_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(
            return_value=SessionInfo(
                session_id="session-abc",
                agent_name="other-agent",
                created_at=datetime.now(timezone.utc),
                last_active_at=datetime.now(timezone.utc),
                message_count=0,
                duration_seconds=0.0,
                usage=UsageInfo(),
                model=None,
                context_window_utilization=None,
            )
        )
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_send_message_missing_session_id_returns_422(self, client):
        response = client.post(
            "/v1/agents/my-agent/messages",
            json={"message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests — POST /v1/agents/{name}/messages/stream
# ---------------------------------------------------------------------------


class TestStreamMessages:
    @pytest.mark.asyncio
    async def test_stream_returns_sse_content_type(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/v1/agents/my-agent/messages/stream",
                json={"session_id": "session-abc", "message": "Hello"},
                headers=AUTH_HEADERS,
            ) as response:
                assert response.status_code == 200
                content_type = response.headers.get("content-type", "")
                assert "text/event-stream" in content_type

    @pytest.mark.asyncio
    async def test_stream_body_contains_message_events(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/v1/agents/my-agent/messages/stream",
                json={"session_id": "session-abc", "message": "Hello"},
                headers=AUTH_HEADERS,
            ) as response:
                body = await response.aread()
                assert b"event: message" in body

    @pytest.mark.asyncio
    async def test_stream_body_contains_done_event(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/v1/agents/my-agent/messages/stream",
                json={"session_id": "session-abc", "message": "Hello"},
                headers=AUTH_HEADERS,
            ) as response:
                body = await response.aread()
                assert b"event: done" in body

    @pytest.mark.asyncio
    async def test_stream_body_contains_chunk_data(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            async with ac.stream(
                "POST",
                "/v1/agents/my-agent/messages/stream",
                json={"session_id": "session-abc", "message": "Hello"},
                headers=AUTH_HEADERS,
            ) as response:
                body = await response.aread()
                assert b"Hello" in body

    def test_stream_without_auth_returns_401(self, client):
        response = client.post(
            "/v1/agents/my-agent/messages/stream",
            json={"session_id": "session-abc", "message": "Hello"},
        )
        assert response.status_code == 401

    def test_stream_message_wrong_agent_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(
            return_value=SessionInfo(
                session_id="session-abc",
                agent_name="other-agent",
                created_at=datetime.now(timezone.utc),
                last_active_at=datetime.now(timezone.utc),
                message_count=0,
                duration_seconds=0.0,
                usage=UsageInfo(),
                model=None,
                context_window_utilization=None,
            )
        )
        response = client.post(
            "/v1/agents/my-agent/messages/stream",
            json={"session_id": "session-abc", "message": "Hello"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404
