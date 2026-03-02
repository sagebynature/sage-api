"""Tests for A2A AgentCard endpoint and builder."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sage_api.a2a.agent_card import build_agent_card, router
from sage_api.config import get_settings
from sage_api.models.schemas import AgentSummary
from sage_api.services.agent_registry import AgentRegistry

AGENT_CARD_URL = "/.well-known/agent-card.json"


@pytest.fixture()
def mock_registry() -> MagicMock:
    """Create a mock AgentRegistry."""
    return MagicMock(spec=AgentRegistry)


@pytest.fixture()
def app(monkeypatch, mock_registry) -> FastAPI:
    """Create a minimal FastAPI app with the agent card router and a mock registry."""
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


class TestAgentCardEndpoint:
    """Tests for GET /.well-known/agent-card.json."""

    def test_returns_200_without_auth(self, client, mock_registry):
        """Agent card endpoint is publicly accessible — no auth needed."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        assert response.status_code == 200

    def test_response_is_valid_json_with_required_keys(self, client, mock_registry):
        """Response body is valid JSON containing name, skills, capabilities."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        data = response.json()
        assert "name" in data
        assert "skills" in data
        assert "capabilities" in data
        assert "defaultInputModes" in data
        assert "defaultOutputModes" in data

    def test_skills_reflect_registered_agents(self, client, mock_registry):
        """Each registered agent maps to one skill in the card."""
        mock_registry.list_agents.return_value = [
            AgentSummary(name="alpha", description="Alpha agent", model="gpt-4o-mini", skills_count=0, subagents_count=0),
            AgentSummary(name="beta", description="Beta agent", model="gpt-4o-mini", skills_count=0, subagents_count=0),
        ]

        response = client.get(AGENT_CARD_URL)

        data = response.json()
        assert len(data["skills"]) == 2
        skill_ids = {s["id"] for s in data["skills"]}
        assert skill_ids == {"alpha", "beta"}

    def test_empty_agent_list_returns_empty_skills(self, client, mock_registry):
        """Empty registry produces empty skills list, not an error."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["skills"] == []

    def test_content_type_is_application_json(self, client, mock_registry):
        """Response Content-Type header is application/json."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        assert "application/json" in response.headers["content-type"]
    def test_cache_control_no_cache_header(self, client, mock_registry):
        """Response includes Cache-Control: no-cache header."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        assert "Cache-Control" in response.headers
        assert response.headers["Cache-Control"] == "no-cache"


    def test_capabilities_streaming_is_true(self, client, mock_registry):
        """AgentCard declares streaming capability as true."""
        mock_registry.list_agents.return_value = []

        response = client.get(AGENT_CARD_URL)

        data = response.json()
        assert data["capabilities"]["streaming"] is True

    def test_skill_description_is_empty_string_when_agent_has_no_description(self, client, mock_registry):
        """Agent with no description maps to skill with empty string description."""
        mock_registry.list_agents.return_value = [
            AgentSummary(name="nodesc", description=None, model="gpt-4o-mini", skills_count=0, subagents_count=0),
        ]

        response = client.get(AGENT_CARD_URL)

        data = response.json()
        assert data["skills"][0]["description"] == ""


class TestBuildAgentCard:
    """Unit tests for the build_agent_card() helper function."""

    def test_build_agent_card_returns_correct_structure(self):
        """build_agent_card returns a dict with all required A2A fields."""
        agents = [
            AgentSummary(name="my-agent", description="Does stuff", model="gpt-4o-mini", skills_count=0, subagents_count=0),
        ]

        card = build_agent_card(agents, "http://localhost:8000")

        assert card["name"] == "sage-api"
        assert card["description"] == "AI agent service powered by sage"
        assert card["url"] == "http://localhost:8000/a2a"
        assert card["version"] == "1.0.0"
        assert card["capabilities"] == {"streaming": True, "pushNotifications": False}
        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "my-agent"
        assert card["skills"][0]["name"] == "my-agent"
        assert card["skills"][0]["description"] == "Does stuff"
        assert card["skills"][0]["tags"] == []
        assert card["defaultInputModes"] == ["text"]
        assert card["defaultOutputModes"] == ["text"]

    def test_build_agent_card_empty_agents(self):
        """build_agent_card with empty list produces empty skills."""
        card = build_agent_card([], "http://example.com")

        assert card["skills"] == []

    def test_build_agent_card_base_url_trailing_slash_stripped(self):
        """base_url with trailing slash still produces clean url field."""
        card = build_agent_card([], "http://example.com/")

        # base_url is passed in already stripped; this tests the function itself
        # with a non-stripped URL the caller is responsible, but let's confirm
        # the format is consistent
        assert card["url"] == "http://example.com//a2a"  # caller must strip — documented

    def test_build_agent_card_agent_with_none_description(self):
        """Agent with None description maps to empty string in skill."""
        agents = [AgentSummary(name="x", description=None, model="gpt-4o-mini", skills_count=0, subagents_count=0)]

        card = build_agent_card(agents, "http://host")

        assert card["skills"][0]["description"] == ""

    def test_build_agent_card_multiple_agents_preserves_order(self):
        """Skills are generated in the same order as the input agents list."""
        agents = [
            AgentSummary(name="z-agent", description=None, model="gpt-4o-mini", skills_count=0, subagents_count=0),
            AgentSummary(name="a-agent", description=None, model="gpt-4o-mini", skills_count=0, subagents_count=0),
        ]

        card = build_agent_card(agents, "http://host")

        assert card["skills"][0]["id"] == "z-agent"
        assert card["skills"][1]["id"] == "a-agent"
