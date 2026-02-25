"""REST endpoints for agent discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from sage_api.middleware.auth import verify_api_key
from sage_api.models.schemas import AgentInfo, ErrorResponse
from sage_api.services.agent_registry import AgentRegistry

router = APIRouter(
    prefix="/v1",
    tags=["agents"],
    dependencies=[Depends(verify_api_key)],
)


def get_registry(request: Request) -> AgentRegistry:
    """Extract AgentRegistry from application state."""
    return request.app.state.registry


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents(
    registry: AgentRegistry = Depends(get_registry),
) -> list[AgentInfo]:
    """List all available agents."""
    return registry.list_agents()


@router.get("/agents/{name}", response_model=AgentInfo)
async def get_agent(
    name: str,
    registry: AgentRegistry = Depends(get_registry),
) -> AgentInfo:
    """Get agent by name.

    Returns 404 if the agent is not found.
    """
    config = registry.get_template(name)
    if config is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error="Not Found",
                detail=f"Agent '{name}' not found",
                status_code=404,
            ).model_dump(),
        )
    return AgentInfo(
        name=config.name,
        description=config.description,
        capabilities=[],
    )
