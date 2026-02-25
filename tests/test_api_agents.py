"""Tests for agent discovery REST endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sage_api.api.agents import router
from sage_api.config import get_settings
from sage_api.models.schemas import AgentInfo
from sage_api.services.agent_registry import AgentRegistry


@pytest.fixture()
def mock_registry() -> MagicMock:
    """Create a mock AgentRegistry."""
    return MagicMock(spec=AgentRegistry)


@pytest.fixture()
def app(monkeypatch, mock_registry) -> FastAPI:
    """Create a minimal FastAPI app with the agents router and a mock registry."""
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.registry = mock_registry
    return test_app


@pytest.fixture()
def client(app) -> TestClient:
    """Create a TestClient for the test app."""
    return TestClient(app)


AUTH_HEADERS = {"X-API-Key": "test-key"}


class TestListAgents:
    """Tests for GET /v1/agents."""

    def test_list_returns_empty_when_no_agents(self, client, mock_registry):
        """Empty registry returns an empty JSON array."""
        mock_registry.list_agents.return_value = []

        response = client.get("/v1/agents", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json() == []
        mock_registry.list_agents.assert_called_once()

    def test_list_returns_multiple_agents(self, client, mock_registry):
        """Registry with multiple agents returns all of them."""
        agents = [
            AgentInfo(name="alpha", description="Alpha agent", capabilities=["chat"]),
            AgentInfo(name="beta", description=None, capabilities=[]),
        ]
        mock_registry.list_agents.return_value = agents

        response = client.get("/v1/agents", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "alpha"
        assert data[0]["description"] == "Alpha agent"
        assert data[0]["capabilities"] == ["chat"]
        assert data[1]["name"] == "beta"
        assert data[1]["description"] is None

    def test_list_missing_auth_returns_401(self, client, mock_registry):
        """Request without API key returns 401."""
        response = client.get("/v1/agents")

        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()

    def test_list_wrong_auth_returns_401(self, client, mock_registry):
        """Request with wrong API key returns 401."""
        response = client.get("/v1/agents", headers={"X-API-Key": "wrong-key"})

        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()


class TestGetAgent:
    """Tests for GET /v1/agents/{name}."""

    def test_get_existing_agent_returns_agent_info(self, client, mock_registry):
        """Known agent name returns AgentInfo with 200."""
        config = MagicMock()
        config.name = "my-agent"
        config.description = "A helpful agent"
        mock_registry.get_template.return_value = config

        response = client.get("/v1/agents/my-agent", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my-agent"
        assert data["description"] == "A helpful agent"
        assert data["capabilities"] == []
        mock_registry.get_template.assert_called_once_with("my-agent")

    def test_get_missing_agent_returns_404(self, client, mock_registry):
        """Unknown agent name returns 404 with ErrorResponse body."""
        mock_registry.get_template.return_value = None

        response = client.get("/v1/agents/unknown", headers=AUTH_HEADERS)

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "Not Found"
        assert "unknown" in detail["detail"]
        assert detail["status_code"] == 404

    def test_get_agent_missing_auth_returns_401(self, client, mock_registry):
        """Request without API key returns 401 even for valid agent names."""
        response = client.get("/v1/agents/some-agent")

        assert response.status_code == 401
        mock_registry.get_template.assert_not_called()

    def test_get_agent_with_no_description(self, client, mock_registry):
        """Agent with no description returns description as null."""
        config = MagicMock()
        config.name = "minimal-agent"
        config.description = None
        mock_registry.get_template.return_value = config

        response = client.get("/v1/agents/minimal-agent", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "minimal-agent"
        assert data["description"] is None
        assert data["capabilities"] == []

    def test_get_agent_capabilities_always_empty_list(self, client, mock_registry):
        """Capabilities field is always an empty list (not yet implemented)."""
        config = MagicMock()
        config.name = "cap-agent"
        config.description = "Has capabilities"
        mock_registry.get_template.return_value = config

        response = client.get("/v1/agents/cap-agent", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json()["capabilities"] == []
