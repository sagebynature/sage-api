"""Tests for health check endpoints (liveness and readiness probes)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sage_api.api.health import router
from sage_api.models.schemas import AgentInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_redis(*, ping_raises: Exception | None = None) -> AsyncMock:
    """Build a mock Redis client.

    Args:
        ping_raises: If set, ``ping()`` will raise this exception.
    """
    mock_redis = AsyncMock()
    if ping_raises is not None:
        mock_redis.ping = AsyncMock(side_effect=ping_raises)
    else:
        mock_redis.ping = AsyncMock(return_value=True)
    return mock_redis


def _make_mock_registry(agents: list[AgentInfo]) -> MagicMock:
    """Build a mock AgentRegistry with a fixed ``list_agents`` return value."""
    mock_registry = MagicMock()
    mock_registry.list_agents.return_value = agents
    return mock_registry


@pytest.fixture()
def app_healthy() -> FastAPI:
    """App with healthy Redis and one registered agent."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.redis = _make_mock_redis()
    test_app.state.registry = _make_mock_registry([AgentInfo(name="helper", description="A helper", capabilities=[])])
    return test_app


@pytest.fixture()
def app_no_agents() -> FastAPI:
    """App with healthy Redis but empty registry."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.redis = _make_mock_redis()
    test_app.state.registry = _make_mock_registry([])
    return test_app


@pytest.fixture()
def app_redis_down() -> FastAPI:
    """App where Redis ping raises a connection error."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.redis = _make_mock_redis(ping_raises=ConnectionError("Redis connection refused"))
    test_app.state.registry = _make_mock_registry([AgentInfo(name="helper", description="A helper", capabilities=[])])
    return test_app


@pytest.fixture()
def app_both_fail() -> FastAPI:
    """App where Redis is down AND registry is empty."""
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.redis = _make_mock_redis(ping_raises=ConnectionError("Redis unavailable"))
    test_app.state.registry = _make_mock_registry([])
    return test_app


# ---------------------------------------------------------------------------
# Tests: GET /health/live
# ---------------------------------------------------------------------------


class TestLiveness:
    """Tests for GET /health/live."""

    def test_liveness_returns_200(self, app_healthy):
        """Liveness probe always returns HTTP 200."""
        client = TestClient(app_healthy)
        response = client.get("/health/live")
        assert response.status_code == 200

    def test_liveness_returns_ok_status(self, app_healthy):
        """Liveness probe body is ``{"status": "ok"}``."""
        client = TestClient(app_healthy)
        response = client.get("/health/live")
        assert response.json() == {"status": "alive"}

    def test_liveness_does_not_require_auth(self, app_no_agents):
        """Liveness probe is reachable without any authentication header."""
        client = TestClient(app_no_agents)
        response = client.get("/health/live")
        # Must be 200, not 401 or 403
        assert response.status_code == 200

    def test_liveness_returns_200_even_when_redis_down(self, app_redis_down):
        """Liveness probe stays 200 regardless of Redis or registry state."""
        client = TestClient(app_redis_down)
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


# ---------------------------------------------------------------------------
# Tests: GET /health/ready
# ---------------------------------------------------------------------------


class TestReadiness:
    """Tests for GET /health/ready."""

    def test_readiness_returns_200_when_healthy(self, app_healthy):
        """Readiness probe returns 200 when Redis is up and agents are registered."""
        client = TestClient(app_healthy)
        response = client.get("/health/ready")
        assert response.status_code == 200

    def test_readiness_body_contains_agent_count(self, app_healthy):
        """Readiness response includes ``agents`` count when healthy."""
        client = TestClient(app_healthy)
        response = client.get("/health/ready")
        data = response.json()
        assert data["status"] == "ready"
        assert data["redis"] == "connected" and data["agents_loaded"] == 1

    def test_readiness_returns_503_when_redis_down(self, app_redis_down):
        """Readiness probe returns 503 when Redis ping fails."""
        client = TestClient(app_redis_down)
        response = client.get("/health/ready")
        assert response.status_code == 503

    def test_readiness_returns_503_when_no_agents(self, app_no_agents):
        """Readiness probe returns 503 when registry is empty."""
        client = TestClient(app_no_agents)
        response = client.get("/health/ready")
        assert response.status_code == 503

    def test_readiness_503_body_when_redis_down(self, app_redis_down):
        """503 response body indicates unavailable status."""
        client = TestClient(app_redis_down)
        response = client.get("/health/ready")
        data = response.json()
        assert data["status"] == "not_ready"
        assert "redis" in data and len(data["redis"]) > 0


    def test_readiness_503_body_when_no_agents(self, app_no_agents):
        """503 response body mentions missing agents."""
        client = TestClient(app_no_agents)
        response = client.get("/health/ready")
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["agents_loaded"] == 0

    def test_readiness_returns_503_when_both_fail(self, app_both_fail):
        """503 when both Redis is down and no agents registered."""
        client = TestClient(app_both_fail)
        response = client.get("/health/ready")
        assert response.status_code == 503

    def test_readiness_does_not_require_auth(self, app_healthy):
        """Readiness probe is reachable without any authentication header."""
        client = TestClient(app_healthy)
        response = client.get("/health/ready")
        # Must be 200, not 401 or 403
        assert response.status_code == 200

    def test_readiness_agent_count_reflects_registry(self):
        """Agent count in response matches the number of registered agents."""
        agents = [
            AgentInfo(name="a1", description=None, capabilities=[]),
            AgentInfo(name="a2", description=None, capabilities=[]),
            AgentInfo(name="a3", description=None, capabilities=[]),
        ]
        test_app = FastAPI()
        test_app.include_router(router)
        test_app.state.redis = _make_mock_redis()
        test_app.state.registry = _make_mock_registry(agents)

        client = TestClient(test_app)
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["agents_loaded"] == 3
