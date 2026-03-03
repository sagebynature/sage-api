"""Domain exceptions for Sage API.

These exceptions decouple service-layer error signaling from HTTP transport
concerns.  The middleware error handler converts them into consistent
``ErrorResponse`` JSON bodies automatically.
"""

from __future__ import annotations


class DomainException(Exception):
    """Base class for all domain-level exceptions.

    Subclasses set ``status_code`` and ``error`` as class attributes.
    Handlers read these to build the HTTP response.
    """

    status_code: int = 500
    error: str = "Internal Error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(detail or self.error)


class NotFoundError(DomainException):
    """Raised when a requested resource does not exist."""

    status_code = 404
    error = "Not Found"


class ConflictError(DomainException):
    """Raised when a request conflicts with current state (e.g. concurrent access)."""

    status_code = 409
    error = "Conflict"


class RequestTimeoutError(DomainException):
    """Raised when a downstream operation exceeds its timeout."""

    status_code = 504
    error = "Request Timed Out"


class ServiceUnavailableError(DomainException):
    """Raised when the service cannot fulfil a request (e.g. no agents registered)."""

    status_code = 503
    error = "Service Unavailable"
