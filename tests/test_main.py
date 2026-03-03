"""Integration tests for sage_api/main.py — FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sage_api.config import get_settings
from sage_api.exceptions import NotFoundError
from sage_api.main import create_app
from sage_api.models.schemas import AgentSummary


AUTH_HEADERS = {"X-API-Key": "test-key"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_redis(*, ping_ok: bool = True) -> AsyncMock:
    """Return a mock async Redis client."""
    mock = AsyncMock()
    if ping_ok:
        mock.ping = AsyncMock(return_value=True)
    else:
        mock.ping = AsyncMock(side_effect=ConnectionError("Redis down"))
    mock.aclose = AsyncMock()
    return mock


def _make_mock_registry(agents: list[AgentSummary] | None = None) -> MagicMock:
    """Return a mock AgentRegistry."""
    mock = MagicMock()
    mock.list_agents.return_value = agents or []
    return mock


def _make_mock_session_manager() -> MagicMock:
    """Return a mock SessionManager."""
    return MagicMock()


def _make_mock_hot_reloader() -> AsyncMock:
    """Return a mock AgentHotReloader."""
    mock = AsyncMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Fixture: app with mocked lifespan
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_registry() -> MagicMock:
    return _make_mock_registry(
        agents=[
            AgentSummary(
                name="test-agent", description="A test agent", model="gpt-4o-mini", skills_count=0, subagents_count=0
            )
        ]
    )


@pytest.fixture()
def mock_redis() -> AsyncMock:
    return _make_mock_redis(ping_ok=True)


@pytest.fixture()
def mock_session_manager() -> MagicMock:
    return _make_mock_session_manager()


@pytest.fixture()
def mock_hot_reloader() -> AsyncMock:
    return _make_mock_hot_reloader()


@pytest.fixture()
async def test_app(
    monkeypatch,
    mock_registry,
    mock_redis,
    mock_session_manager,
    mock_hot_reloader,
) -> AsyncGenerator[FastAPI, None]:
    """Build a create_app() instance with all startup dependencies mocked.

    ASGITransport does NOT trigger ASGI lifespan, so we set app.state.*
    directly after creating the app.
    """
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()

    @asynccontextmanager
    async def mock_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.redis = mock_redis
        app.state.registry = mock_registry
        app.state.session_manager = mock_session_manager
        app.state.hot_reloader = mock_hot_reloader
        yield

    app = create_app(lifespan_override=mock_lifespan)
    # Set state directly since ASGITransport never runs lifespan
    app.state.redis = mock_redis
    app.state.registry = mock_registry
    app.state.session_manager = mock_session_manager
    app.state.hot_reloader = mock_hot_reloader
    yield app


@pytest.fixture()
async def client(test_app) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client wired to the test app via ASGI transport."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test 1: GET /health/live → 200 (no auth needed)
# ---------------------------------------------------------------------------


async def test_health_live_returns_200(client: AsyncClient) -> None:
    """Liveness probe returns 200 with no authentication required."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


# ---------------------------------------------------------------------------
# Test 2: GET /health/ready → 200 when Redis + registry are healthy
# ---------------------------------------------------------------------------


async def test_health_ready_returns_200_when_healthy(
    client: AsyncClient, mock_redis: AsyncMock, mock_registry: MagicMock
) -> None:
    """Readiness probe returns 200 when Redis responds and registry has agents."""
    response = await client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["redis"] == "connected" and data["agents_loaded"] == 1


# ---------------------------------------------------------------------------
# Test 3: GET /health/ready → 503 when Redis is down
# ---------------------------------------------------------------------------


async def test_health_ready_returns_503_when_redis_down(
    monkeypatch, mock_hot_reloader: AsyncMock, mock_registry: MagicMock, mock_session_manager: MagicMock
) -> None:
    """Readiness probe returns 503 when Redis is unreachable."""
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()

    broken_redis = _make_mock_redis(ping_ok=False)

    @asynccontextmanager
    async def mock_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.redis = broken_redis
        app.state.registry = mock_registry
        app.state.session_manager = mock_session_manager
        app.state.hot_reloader = mock_hot_reloader
        yield

    down_app = create_app(lifespan_override=mock_lifespan)
    # Set state directly since ASGITransport never runs lifespan
    down_app.state.redis = broken_redis
    down_app.state.registry = mock_registry
    down_app.state.session_manager = mock_session_manager
    down_app.state.hot_reloader = mock_hot_reloader

    async with AsyncClient(transport=ASGITransport(app=down_app), base_url="http://test") as ac:
        response = await ac.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# Test 4: GET /v1/agents → 401 (no API key)
# ---------------------------------------------------------------------------


async def test_list_agents_requires_auth(client: AsyncClient) -> None:
    """GET /v1/agents returns 401 when no API key is provided."""
    response = await client.get("/v1/agents")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 5: GET /v1/agents → 200 with API key and mocked registry
# ---------------------------------------------------------------------------


async def test_list_agents_returns_200_with_auth(client: AsyncClient, mock_registry: MagicMock) -> None:
    """GET /v1/agents returns 200 with valid API key and registry data."""
    response = await client.get("/v1/agents", headers=AUTH_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "test-agent"


# ---------------------------------------------------------------------------
# Test 6: GET /.well-known/agent-card.json → 200 (no auth)
# ---------------------------------------------------------------------------


async def test_agent_card_returns_200_no_auth(client: AsyncClient) -> None:
    """Agent card endpoint is publicly accessible without authentication."""
    response = await client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "sage-api"
    assert "url" in data
    assert "skills" in data


# ---------------------------------------------------------------------------
# Test 7: POST /a2a → 401 (no API key)
# ---------------------------------------------------------------------------


async def test_a2a_requires_auth(client: AsyncClient) -> None:
    """POST /a2a returns 401 when no API key is provided."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "Hello"}],
            }
        },
    }
    response = await client.post("/a2a", json=payload)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test 8: create_app() produces consistent app metadata
# ---------------------------------------------------------------------------


async def test_create_app_metadata(monkeypatch) -> None:
    """create_app() returns a FastAPI instance with the correct title and version."""
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()

    test_app = create_app()
    assert test_app.title == "sage-api"
    assert test_app.version == "1.0.0"
    assert test_app.docs_url == "/docs"
    assert test_app.redoc_url == "/redoc"


# ---------------------------------------------------------------------------
# Test 9: GET /docs → 200 (OpenAPI docs publicly accessible)
# ---------------------------------------------------------------------------


async def test_docs_endpoint_accessible(client: AsyncClient) -> None:
    """OpenAPI docs are served without authentication."""
    response = await client.get("/docs")
    assert response.status_code == 200


async def test_error_handler_returns_error_response_shape(
    client: AsyncClient,
    mock_session_manager: MagicMock,
) -> None:
    mock_session_manager.create_session = AsyncMock(side_effect=NotFoundError("Agent 'nonexistent' not found"))

    response = await client.post(
        "/v1/agents/nonexistent/sessions",
        headers=AUTH_HEADERS,
        json={},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "Not Found"
    assert body["detail"] == "Agent 'nonexistent' not found"
    assert body["status_code"] == 404


async def test_cors_middleware_not_added_when_origins_empty(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"Origin": "http://evil.com"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
