"""Error handling middleware for Sage API.

Provides centralized exception handlers for FastAPI applications,
ensuring consistent ErrorResponse JSON bodies for all error cases.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sage_api.exceptions import DomainException
from sage_api.logging import get_logger

logger = get_logger(__name__)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException with consistent ErrorResponse body.

    If the exception detail is a dict (e.g., from auth middleware), the
    ``"error"`` key is extracted as the error message. Otherwise, the
    raw detail string is used.

    Args:
        request: The incoming HTTP request.
        exc: The raised HTTPException.

    Returns:
        JSONResponse with ErrorResponse-compatible body.
    """
    if isinstance(exc.detail, dict):
        error_message = exc.detail.get("error", str(exc.detail))
        detail_text = exc.detail.get("detail")
    else:
        error_message = str(exc.detail) if exc.detail is not None else "HTTP Error"
        detail_text = exc.detail if isinstance(exc.detail, str) else None

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_message,
            "detail": detail_text,
            "status_code": exc.status_code,
        },
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic RequestValidationError with field-level details.

    Args:
        request: The incoming HTTP request.
        exc: The raised RequestValidationError.

    Returns:
        JSONResponse with 422 status and field error details.
    """
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation Error",
            "detail": str(exc.errors()),
            "status_code": 422,
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle any unhandled exception with a generic 500 response.

    Logs the full exception for debugging without exposing internal
    details to API clients.

    Args:
        request: The incoming HTTP request.
        exc: The unhandled exception.

    Returns:
        JSONResponse with 500 status and generic error message.
    """
    logger.exception(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        exc_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": None,
            "status_code": 500,
        },
    )


async def domain_exception_handler(request: Request, exc: DomainException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error,
            "detail": exc.detail,
            "status_code": exc.status_code,
        },
    )


def add_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the given FastAPI application."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(DomainException, domain_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
