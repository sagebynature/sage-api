"""Health check endpoints for liveness and readiness probes."""

from __future__ import annotations

from typing import Any

import redis.asyncio
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from sage_api.logging import get_logger
from sage_api.services.agent_registry import AgentRegistry

router = APIRouter(
    prefix="/health",
    tags=["health"],
    # NO auth dependency - health endpoints are exempt
)

logger = get_logger(__name__)


@router.get("/live", response_model=dict[str, str])
async def liveness() -> dict[str, str]:
    """Liveness probe - always returns 200 if the process is running."""
    return {"status": "alive"}


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe - checks Redis connectivity and agent registry population.

    Returns 200 if:
    - Redis responds to ping
    - Registry has at least one agent registered

    Returns 503 otherwise.
    """
    redis_client: redis.asyncio.Redis = request.app.state.redis
    registry: AgentRegistry = request.app.state.registry

    errors: list[str] = []

    # Check Redis connectivity
    try:
        await redis_client.ping()
    except Exception:
        logger.exception("redis_health_check_failed")
        errors.append("Redis unavailable")

    # Check registry has agents
    agents = registry.list_agents()
    if len(agents) == 0:
        errors.append("No agents registered")

    if errors:
        redis_error = "; ".join(errors) if errors else "Unknown error"
        content: dict[str, Any] = {
            "status": "not_ready",
            "redis": redis_error,
            "agents_loaded": 0,
        }
        return JSONResponse(status_code=503, content=content)

    return JSONResponse(
        status_code=200,
        content={"status": "ready", "redis": "connected", "agents_loaded": len(agents)},
    )
