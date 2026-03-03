"""Structured logging configuration using structlog."""

import logging
import logging.config
from pathlib import Path
from typing import Any

import structlog

_LOGGING_CONF = Path(__file__).resolve().parent.parent / "logging.conf"


def setup_logging(log_level: str = "INFO") -> None:
    """Configure logging from logging.conf, then layer structlog on top.

    Args:
        log_level: Logging level as a string (e.g., "DEBUG", "INFO", "WARNING", "ERROR").
                  Defaults to "INFO". Invalid levels default to INFO.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    if _LOGGING_CONF.exists():
        try:
            logging.config.fileConfig(str(_LOGGING_CONF), disable_existing_loggers=False)
        except Exception:
            logging.basicConfig(level=level)
    else:
        logging.basicConfig(level=level)

    logging.getLogger().setLevel(level)

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
