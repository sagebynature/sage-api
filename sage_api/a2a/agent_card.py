"""A2A AgentCard builder and discovery endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sage_api.models.schemas import AgentInfo
from sage_api.services.agent_registry import AgentRegistry

router = APIRouter(
    prefix="",
    tags=["a2a"],
)

AGENT_CARD_NAME = "sage-api"
AGENT_CARD_DESCRIPTION = "AI agent service powered by sage"
AGENT_CARD_VERSION = "1.0.0"


def build_agent_card(agents: list[AgentInfo], base_url: str) -> dict:
    """Build an A2A-compliant AgentCard dict from a list of agents.

    Args:
        agents: List of AgentInfo objects from the registry.
        base_url: Base URL of the server (used to construct the A2A endpoint URL).

    Returns:
        A dict conforming to the A2A spec v0.3.0 AgentCard structure.
    """
    skills = [
        {
            "id": agent.name,
            "name": agent.name,
            "description": agent.description or "",
            "tags": [],
        }
        for agent in agents
    ]

    return {
        "name": AGENT_CARD_NAME,
        "description": AGENT_CARD_DESCRIPTION,
        "url": f"{base_url}/a2a",
        "version": AGENT_CARD_VERSION,
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
        },
        "skills": skills,
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    }


def get_registry(request: Request) -> AgentRegistry:
    """Extract AgentRegistry from application state."""
    return request.app.state.registry


@router.get("/.well-known/agent-card.json")
async def get_agent_card(request: Request) -> JSONResponse:
    """Return the A2A AgentCard for this service.

    This endpoint is publicly accessible (no auth required) per the A2A spec.
    """
    registry = get_registry(request)
    agents = registry.list_agents()
    base_url = str(request.base_url).rstrip("/")
    card = build_agent_card(agents, base_url)
    return JSONResponse(content=card, media_type="application/json", headers={"Cache-Control": "no-cache"})
