"""Redis-backed rate limiting middleware.

Provides per-API-key request rate limiting (sliding window), request body
size enforcement, and concurrent SSE stream caps.  All limits are opt-in:
a zero value for any limit means that check is disabled.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sage_api.logging import get_logger

logger = get_logger(__name__)

_EXEMPT_PATHS = frozenset(
    {
        "/health/live",
        "/health/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/.well-known/agent-card.json",
    }
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        config = getattr(request.app.state, "rate_limit_config", None)
        if config is None:
            return await call_next(request)

        rpm: int = config.get("rpm", 0)
        max_body: int = config.get("max_body_bytes", 0)
        max_streams: int = config.get("max_concurrent_streams", 0)

        if max_body > 0:
            content_length = request.headers.get("content-length")
            if content_length is not None and int(content_length) > max_body:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Request Entity Too Large",
                        "detail": f"Body exceeds {max_body} bytes",
                        "status_code": 413,
                    },
                )

        api_key = request.headers.get("x-api-key", "anonymous")
        redis = getattr(request.app.state, "redis", None)

        if rpm > 0 and redis is not None:
            window_key = f"ratelimit:{api_key}:{int(time.time()) // 60}"
            current = await redis.incr(window_key)
            if current == 1:
                await redis.expire(window_key, 60)
            if current > rpm:
                logger.warning(
                    "rate_limit_exceeded",
                    api_key_prefix=api_key[:8],
                    rpm=rpm,
                    current=current,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too Many Requests",
                        "detail": f"Rate limit of {rpm} requests per minute exceeded",
                        "status_code": 429,
                    },
                    headers={"Retry-After": "60"},
                )

        is_stream = path.endswith("/stream") or (path == "/a2a" and request.method == "POST")
        stream_key = f"streams:{api_key}" if (max_streams > 0 and is_stream and redis is not None) else None

        if stream_key is not None:
            active = await redis.incr(stream_key)
            if active == 1:
                # Safety TTL: self-cleans if decrements are missed (e.g. process crash)
                await redis.expire(stream_key, 300)
            if active > max_streams:
                await redis.decr(stream_key)
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "Too Many Streams",
                        "detail": f"Max {max_streams} concurrent streams exceeded",
                        "status_code": 429,
                    },
                )

        try:
            response = await call_next(request)
            return response
        finally:
            if stream_key is not None:
                await redis.decr(stream_key)
