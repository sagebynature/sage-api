"""API Key authentication middleware for Sage API."""

import secrets
from fastapi import Header, HTTPException, Request
from sage_api.config import get_settings

# Paths that don't require API key authentication
EXEMPT_PATHS = {
    "/health/live",
    "/health/ready",
    "/.well-known/agent-card.json",
    "/docs",
    "/openapi.json",
    "/metrics",
}


async def verify_api_key(request: Request, x_api_key: str = Header(default=None)) -> None:
    """Verify API key from request header.

    Args:
        request: The incoming request.
        x_api_key: API key from X-API-Key header.

    Raises:
        HTTPException: If API key is missing or invalid (401 status).
    """
    # Skip authentication for exempt paths
    if request.url.path in EXEMPT_PATHS:
        return

    settings = get_settings()

    # Check if API key is provided
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Unauthorized",
                "detail": "Invalid or missing API key",
                "status_code": 401,
            },
        )

    # Compare API keys using timing-safe comparison
    if not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Unauthorized",
                "detail": "Invalid or missing API key",
                "status_code": 401,
            },
        )
