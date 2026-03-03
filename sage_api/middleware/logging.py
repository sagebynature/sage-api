"""HTTP request logging middleware for structured request/response tracking."""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sage_api.logging import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests with structured fields.

    Logs the following fields for each request:
    - request_id: Unique UUID for request tracking
    - method: HTTP method (GET, POST, etc.)
    - path: Request path
    - status_code: HTTP response status code
    - duration_ms: Request duration in milliseconds
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process the request and log relevant information.

        Args:
            request: The incoming HTTP request
            call_next: Callable to process the request through the application

        Returns:
            The HTTP response from the application
        """
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = time.monotonic()

        response = await call_next(request)

        response.headers["X-Request-ID"] = request_id
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response
