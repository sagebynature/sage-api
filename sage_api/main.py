"""FastAPI application factory for sage-api."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI

from sage_api.a2a import a2a_router, agent_card_router
from sage_api.api.agents import router as agents_router
from sage_api.api.health import router as health_router
from sage_api.api.messages import router as messages_router
from sage_api.api.sessions import router as sessions_router
from sage_api.config import get_settings
from sage_api.logging import get_logger, setup_logging
from sage_api.middleware.errors import add_exception_handlers
from sage_api.middleware.logging import RequestLoggingMiddleware
from sage_api.services.agent_registry import AgentRegistry
from sage_api.services.hot_reload import AgentHotReloader
from sage_api.services.session_manager import SessionManager
from sage_api.services.session_store import RedisSessionStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    settings = get_settings()

    # 1. Configure structured logging first
    setup_logging(settings.log_level)
    logger = get_logger(__name__)

    # 2. Connect to Redis (used by health checks via app.state.redis)
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    # 3. Build and populate the agent registry
    registry = AgentRegistry(agents_dir=settings.agents_dir)
    registry.scan()

    # 4. Build session store and session manager
    #    RedisSessionStore now receives the shared redis_client.
    session_store = RedisSessionStore(
        redis_client=redis_client,
        session_ttl=settings.session_ttl_seconds,
    )
    session_manager = SessionManager(
        registry=registry,
        store=session_store,
        request_timeout=settings.request_timeout_seconds,
    )

    # 5. Start hot-reloader
    hot_reloader = AgentHotReloader()
    await hot_reloader.start(agents_dir=settings.agents_dir, registry=registry)

    # 6. Expose services on app state
    app.state.redis = redis_client
    app.state.registry = registry
    app.state.session_manager = session_manager
    app.state.hot_reloader = hot_reloader

    logger.info("sage-api started")

    yield

    # --- Shutdown ---
    await session_manager.close_all()
    await hot_reloader.stop()
    await redis_client.aclose()
    await session_store.close()
    logger.info("sage-api stopped")


def create_app(lifespan_override=None) -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Fully configured FastAPI application instance.
    """
    app = FastAPI(
        title="sage-api",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan_override if lifespan_override is not None else lifespan,
    )

    # Add middleware (last added = first executed)
    app.add_middleware(RequestLoggingMiddleware)

    # Register exception handlers
    add_exception_handlers(app)

    # Include all routers
    app.include_router(agents_router)
    app.include_router(sessions_router)
    app.include_router(messages_router)
    app.include_router(health_router)
    app.include_router(agent_card_router)  # GET /.well-known/agent-card.json
    app.include_router(a2a_router)  # POST /a2a

    return app


# Module-level app instance — allows `uvicorn sage_api.main:app`
app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("sage_api.main:app", host=settings.host, port=settings.port, reload=False)
