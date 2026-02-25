"""Structured logging configuration using structlog."""

import logging
import sys
from typing import Any

import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON output for production, console for dev.

    Args:
        log_level: Logging level as a string (e.g., "DEBUG", "INFO", "WARNING", "ERROR").
                  Defaults to "INFO". Invalid levels default to INFO.
    """
    # Set stdlib logging level
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, stream=sys.stdout)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Get a structlog bound logger.

    Args:
        name: Logger name, typically the module name (__name__).

    Returns:
        A structlog bound logger instance for structured logging.
    """
    return structlog.get_logger(name)
