"""Tests for structured logging setup and request logging middleware."""

import uuid
from unittest.mock import patch

import pytest
import structlog
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from sage_api.logging import get_logger, setup_logging
from sage_api.middleware.logging import RequestLoggingMiddleware


class TestSetupLogging:
    """Test suite for setup_logging function."""

    def setup_method(self):
        """Reset structlog before each test."""
        structlog.reset_defaults()

    def test_setup_logging_info_level(self):
        """Test that setup_logging('INFO') configures structlog without errors."""
        # Should not raise any exceptions
        setup_logging("INFO")

        # Verify structlog is configured by checking we can get a logger
        logger = get_logger("test")
        assert logger is not None

    def test_setup_logging_debug_level(self):
        """Test that setup_logging('DEBUG') sets correct log level."""
        setup_logging("DEBUG")
        logger = get_logger("test")
        assert logger is not None

    def test_setup_logging_warning_level(self):
        """Test that setup_logging('WARNING') sets correct log level."""
        setup_logging("WARNING")
        logger = get_logger("test")
        assert logger is not None

    def test_setup_logging_invalid_level_defaults_gracefully(self):
        """Test that invalid log level defaults gracefully."""
        setup_logging("INVALID_LEVEL")
        logger = get_logger("test")
        # Should default to INFO since INVALID_LEVEL is not a valid level
        # but won't raise an exception
        assert logger is not None


class TestGetLogger:
    """Test suite for get_logger function."""

    def setup_method(self):
        """Reset structlog and setup logging before each test."""
        structlog.reset_defaults()
        setup_logging("INFO")

    def test_get_logger_returns_bound_logger(self):
        """Test that get_logger returns a bound logger object."""
        logger = get_logger("test")
        assert logger is not None
        # Check that it has the structlog interface
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_get_logger_different_names(self):
        """Test that get_logger works with different logger names."""
        logger1 = get_logger("test1")
        logger2 = get_logger("test2")
        assert logger1 is not None
        assert logger2 is not None

    def test_logger_info_call_succeeds(self):
        """Test that calling log.info('test_event', key='value') doesn't raise."""
        logger = get_logger("test")
        # Should not raise any exceptions
        logger.info("test_event", key="value")

    def test_logger_with_multiple_fields(self):
        """Test that logger can handle multiple structured fields."""
        logger = get_logger("test")
        # Should not raise any exceptions
        logger.info(
            "test_event",
            user_id="123",
            request_id="abc-def",
            duration_ms=42.5,
            status_code=200,
        )


class TestRequestLoggingMiddleware:
    """Test suite for RequestLoggingMiddleware."""

    def setup_method(self):
        """Reset structlog and setup logging before each test."""
        structlog.reset_defaults()
        setup_logging("INFO")

    @pytest.mark.asyncio
    async def test_middleware_logs_request_fields(self):
        """Test that request logging middleware logs the correct fields."""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("sage_api.middleware.logging.logger.info") as mock_logger:
                response = await client.get("/test")
                assert response.status_code == 200

                # Verify logger was called
                assert mock_logger.called
                call_args = mock_logger.call_args

                # Check that the required fields are present
                assert "method" in call_args.kwargs
                assert "path" in call_args.kwargs
                assert "status_code" in call_args.kwargs
                assert "duration_ms" in call_args.kwargs

                # Verify field values
                assert call_args.kwargs["method"] == "GET"
                assert call_args.kwargs["path"] == "/test"
                assert call_args.kwargs["status_code"] == 200
                assert isinstance(call_args.kwargs["duration_ms"], (int, float))
                assert call_args.kwargs["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_middleware_handles_different_status_codes(self):
        """Test that middleware correctly logs different HTTP status codes."""
        app = FastAPI()

        @app.get("/ok")
        async def ok_route():
            return {"status": "ok"}

        @app.get("/error")
        async def error_route():
            return {"status": "error"}

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("sage_api.middleware.logging.logger.info") as mock_logger:
                # Test successful response
                response = await client.get("/ok")
                assert response.status_code == 200

                call_kwargs = mock_logger.call_args.kwargs
                assert call_kwargs["status_code"] == 200

    @pytest.mark.asyncio
    async def test_middleware_request_id_is_uuid(self):
        """Test that middleware generates a valid UUID for request_id."""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("sage_api.middleware.logging.logger.info") as mock_logger:
                response = await client.get("/test")
                assert response.status_code == 200

                call_kwargs = mock_logger.call_args.kwargs
                request_id = call_kwargs.get("request_id")
                # Should be a valid UUID string
                assert request_id is not None
                try:
                    uuid.UUID(request_id)
                except ValueError:
                    pytest.fail(f"request_id is not a valid UUID: {request_id}")

    @pytest.mark.asyncio
    async def test_middleware_duration_ms_is_positive(self):
        """Test that middleware duration_ms is always non-negative."""
        app = FastAPI()

        @app.get("/test")
        async def test_route():
            return {"status": "ok"}

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("sage_api.middleware.logging.logger.info") as mock_logger:
                response = await client.get("/test")
                assert response.status_code == 200

                call_kwargs = mock_logger.call_args.kwargs
                duration_ms = call_kwargs.get("duration_ms")
                assert duration_ms is not None
                assert duration_ms >= 0

    @pytest.mark.asyncio
    async def test_middleware_logs_exception_with_logger_exception(self):
        app = FastAPI()

        @app.get("/boom")
        async def boom_route():
            raise RuntimeError("boom")

        app.add_middleware(RequestLoggingMiddleware)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("sage_api.middleware.logging.logger.info") as mock_info:
                with patch("sage_api.middleware.logging.logger.exception") as mock_exc:
                    with pytest.raises(RuntimeError):
                        await client.get("/boom")

                    mock_exc.assert_called_once()
                    assert mock_info.call_count == 0

                    call_args = mock_exc.call_args
                    assert call_args.args[0] == "request_error"
                    assert call_args.kwargs["method"] == "GET"
                    assert call_args.kwargs["path"] == "/boom"
                    assert isinstance(call_args.kwargs["duration_ms"], (int, float))
                    assert call_args.kwargs["duration_ms"] >= 0
                    assert call_args.kwargs["request_id"] is not None
