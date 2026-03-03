"""Tests for session lifecycle REST endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sage_api.api.sessions import router
from sage_api.models.schemas import SessionInfo, UsageInfo
from sage_api.services.session_manager import SessionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-api-key-12345"
AUTH_HEADERS = {"X-Api-Key": TEST_API_KEY}


def make_session_info(
    session_id: str = "abc123",
    agent_name: str = "my-agent",
) -> SessionInfo:
    now = datetime.now(timezone.utc)
    return SessionInfo(
        session_id=session_id,
        agent_name=agent_name,
        created_at=now,
        last_active_at=now,
        message_count=0,
        duration_seconds=0.0,
        usage=UsageInfo(),
        model=None,
        context_window_utilization=None,
    )


def build_app(mock_manager: SessionManager) -> FastAPI:
    """Build a minimal FastAPI app with the sessions router and mock manager."""
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
    manager = MagicMock(spec=SessionManager)
    manager.create_session = AsyncMock(return_value=make_session_info())
    manager.get_session = AsyncMock(return_value=make_session_info())
    manager.delete_session = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def client(mock_manager) -> TestClient:
    app = build_app(mock_manager)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests — POST /v1/agents/{name}/sessions
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_create_session_returns_201(self, client, mock_manager):
        response = client.post(
            "/v1/agents/my-agent/sessions",
            json={},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201

    def test_create_session_returns_session_info(self, client, mock_manager):
        response = client.post(
            "/v1/agents/my-agent/sessions",
            json={},
            headers=AUTH_HEADERS,
        )
        data = response.json()
        assert data["session_id"] == "abc123"
        assert data["agent_name"] == "my-agent"
        assert data["message_count"] == 0
        assert "created_at" in data
        assert "last_active_at" in data

    def test_create_session_calls_manager_with_agent_name(self, client, mock_manager):
        client.post(
            "/v1/agents/my-agent/sessions",
            json={},
            headers=AUTH_HEADERS,
        )
        mock_manager.create_session.assert_awaited_once()
        call_kwargs = mock_manager.create_session.call_args
        assert call_kwargs.kwargs["agent_name"] == "my-agent"

    def test_create_session_passes_metadata(self, client, mock_manager):
        client.post(
            "/v1/agents/my-agent/sessions",
            json={"metadata": {"user": "alice"}},
            headers=AUTH_HEADERS,
        )
        call_kwargs = mock_manager.create_session.call_args
        assert call_kwargs.kwargs["metadata"] == {"user": "alice"}

    def test_create_session_without_auth_returns_401(self, client):
        response = client.post("/v1/agents/my-agent/sessions", json={})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests — GET /v1/agents/{name}/sessions?session_id=
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_get_existing_session_returns_200(self, client, mock_manager):
        response = client.get(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200

    def test_get_existing_session_returns_session_info(self, client, mock_manager):
        response = client.get(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        data = response.json()
        assert data["session_id"] == "abc123"
        assert data["agent_name"] == "my-agent"

    def test_get_missing_session_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(return_value=None)
        response = client.get(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "nonexistent"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_get_session_without_auth_returns_401(self, client):
        response = client.get(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
        )
        assert response.status_code == 401

    def test_get_session_wrong_agent_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(return_value=make_session_info(agent_name="other-agent"))
        response = client.get(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_get_session_without_session_id_returns_422(self, client):
        response = client.get(
            "/v1/agents/my-agent/sessions",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests — DELETE /v1/agents/{name}/sessions?session_id=
# ---------------------------------------------------------------------------


class TestDeleteSession:
    def test_delete_existing_session_returns_204(self, client, mock_manager):
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 204

    def test_delete_existing_session_has_empty_body(self, client, mock_manager):
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        assert response.content == b""

    def test_delete_missing_session_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(return_value=None)
        mock_manager.delete_session = AsyncMock(return_value=False)
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "nonexistent"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_delete_session_without_auth_returns_401(self, client):
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
        )
        assert response.status_code == 401

    def test_delete_calls_manager_with_session_id(self, client, mock_manager):
        client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        mock_manager.delete_session.assert_awaited_once_with("abc123")

    def test_delete_session_wrong_agent_returns_404(self, client, mock_manager):
        mock_manager.get_session = AsyncMock(return_value=make_session_info(agent_name="other-agent"))
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            params={"session_id": "abc123"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404

    def test_delete_session_without_session_id_returns_422(self, client):
        response = client.delete(
            "/v1/agents/my-agent/sessions",
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422
