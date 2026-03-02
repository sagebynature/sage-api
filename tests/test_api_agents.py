"""Tests for agent discovery REST endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sage.config import ModelParams, Permission

from sage_api.api.agents import router
from sage_api.config import get_settings
from sage_api.models.schemas import AgentDetail, AgentSummary, SkillInfo, SubagentDetail
from sage_api.services.agent_registry import AgentRegistry


@pytest.fixture()
def mock_registry() -> MagicMock:
    return MagicMock(spec=AgentRegistry)


@pytest.fixture()
def app(monkeypatch, mock_registry) -> FastAPI:
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.registry = mock_registry
    return test_app


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


AUTH_HEADERS = {"X-API-Key": "test-key"}


class TestListAgents:

    def test_list_returns_empty_when_no_agents(self, client, mock_registry):
        mock_registry.list_agents.return_value = []
        response = client.get("/v1/agents", headers=AUTH_HEADERS)
        assert response.status_code == 200
        assert response.json() == []
        mock_registry.list_agents.assert_called_once()

    def test_list_returns_summary_fields(self, client, mock_registry):
        agents = [
            AgentSummary(
                name="alpha",
                description="Alpha agent",
                model="gpt-4o",
                skills_count=2,
                subagents_count=1,
            ),
            AgentSummary(
                name="beta",
                description=None,
                model="gpt-4o-mini",
                skills_count=0,
                subagents_count=0,
            ),
        ]
        mock_registry.list_agents.return_value = agents
        response = client.get("/v1/agents", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "alpha"
        assert data[0]["model"] == "gpt-4o"
        assert data[0]["skills_count"] == 2
        assert data[0]["subagents_count"] == 1
        assert data[1]["description"] is None

    def test_list_missing_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents")
        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()

    def test_list_wrong_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents", headers={"X-API-Key": "wrong-key"})
        assert response.status_code == 401
        mock_registry.list_agents.assert_not_called()


class TestGetAgent:

    def test_get_returns_full_detail(self, client, mock_registry):
        detail = AgentDetail(
            name="coder",
            description="A coding agent",
            model="claude-sonnet-4-6",
            max_turns=25,
            max_depth=3,
            model_params=ModelParams(temperature=0.0, max_tokens=8192),
            permission=Permission(read="allow", edit="allow"),
            skills=[SkillInfo(name="clean-code", description="Code quality")],
            subagents=[
                SubagentDetail(
                    name="explorer",
                    description="Explores code",
                    model="gpt-4o",
                    max_turns=10,
                    skills=[],
                    model_params=ModelParams(),
                    permission=Permission(read="allow"),
                ),
            ],
            context=None,
        )
        mock_registry.get_agent_detail.return_value = detail
        response = client.get("/v1/agents/coder", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "coder"
        assert data["model"] == "claude-sonnet-4-6"
        assert data["max_turns"] == 25
        assert data["max_depth"] == 3
        assert data["model_params"]["temperature"] == 0.0
        assert data["model_params"]["max_tokens"] == 8192
        assert data["permission"]["read"] == "allow"
        assert len(data["skills"]) == 1
        assert data["skills"][0]["name"] == "clean-code"
        assert len(data["subagents"]) == 1
        assert data["subagents"][0]["name"] == "explorer"
        mock_registry.get_agent_detail.assert_called_once_with("coder")

    def test_get_missing_agent_returns_404(self, client, mock_registry):
        mock_registry.get_agent_detail.return_value = None
        response = client.get("/v1/agents/unknown", headers=AUTH_HEADERS)
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "Not Found"
        assert "unknown" in detail["detail"]

    def test_get_agent_missing_auth_returns_401(self, client, mock_registry):
        response = client.get("/v1/agents/some-agent")
        assert response.status_code == 401
        mock_registry.get_agent_detail.assert_not_called()

    def test_get_agent_with_no_description(self, client, mock_registry):
        detail = AgentDetail(
            name="minimal",
            description=None,
            model="gpt-4o-mini",
            max_turns=10,
            max_depth=3,
            model_params=ModelParams(),
            permission=None,
            skills=[],
            subagents=[],
            context=None,
        )
        mock_registry.get_agent_detail.return_value = detail
        response = client.get("/v1/agents/minimal", headers=AUTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["description"] is None
        assert data["permission"] is None
        assert data["context"] is None
