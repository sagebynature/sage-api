"""HTTP metrics middleware using OTEL Meter API helpers."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from sage_api import telemetry

# Paths excluded from HTTP metrics recording (health + metrics itself)
_SKIP_PATHS = frozenset({"/metrics", "/health/live", "/health/ready"})


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records HTTP request counters, duration histograms, and active gauges.

    Skips recording for ``/metrics``, ``/health/live``, and ``/health/ready``
    to avoid noise in HTTP dashboards.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)

        method = request.method
        # Use matched route template when available to avoid high cardinality
        # from session/message UUIDs.  Falls back to raw path if no route matched.
        route = request.scope.get("route")
        endpoint: str = getattr(route, "path", path)

        telemetry.inc_http_active(method, endpoint)
        start = time.monotonic()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            telemetry.dec_http_active(method, endpoint)
            raise
        duration = time.monotonic() - start
        telemetry.dec_http_active(method, endpoint)
        telemetry.record_http_request(method, endpoint, status_code, duration)
        return response
