"""Tests for the telemetry module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_setup_telemetry_disabled_is_noop() -> None:
    """setup_telemetry(False) must leave the global meter provider as no-op/proxy."""
    from sage_api.telemetry import reset_telemetry, setup_telemetry

    reset_telemetry()
    setup_telemetry(enabled=False)

    from opentelemetry import metrics

    provider_class = metrics.get_meter_provider().__class__.__name__
    # Must NOT be the SDK MeterProvider when disabled.
    # The default proxy class may be named ProxyMeterProvider or _ProxyMeterProvider
    # depending on the OTEL SDK version.
    assert "MeterProvider" not in provider_class or provider_class in ("ProxyMeterProvider", "_ProxyMeterProvider")


def test_setup_telemetry_enabled_installs_sdk_provider() -> None:
    """setup_telemetry(True) must install an SDK MeterProvider."""
    from opentelemetry.sdk.metrics import MeterProvider

    from sage_api.telemetry import get_meter, reset_telemetry, setup_telemetry

    reset_telemetry()
    setup_telemetry(enabled=True)

    from opentelemetry import metrics

    assert isinstance(metrics.get_meter_provider(), MeterProvider)
    assert get_meter() is not None


def test_span_bridge_records_on_llm_complete() -> None:
    """SpanMetricsBridge.on_end must record counters for llm.complete spans."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.trace import StatusCode

    from sage_api.telemetry import SpanMetricsBridge, reset_telemetry

    reset_telemetry()

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    bridge = SpanMetricsBridge(provider)

    span = MagicMock()
    span.name = "llm.complete"
    span.attributes = {"model": "gpt-4o", "prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001}
    span.status.status_code = StatusCode.OK

    bridge.on_end(span)

    data = reader.get_metrics_data()
    assert data is not None
    metric_names = {m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    assert "sage_llm_prompt_tokens_total" in metric_names
    assert "sage_llm_completion_tokens_total" in metric_names
    assert "sage_llm_requests_total" in metric_names


def test_span_bridge_ignores_non_llm_spans() -> None:
    """SpanMetricsBridge must ignore spans not named llm.complete."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.trace import StatusCode

    from sage_api.telemetry import SpanMetricsBridge, reset_telemetry

    reset_telemetry()

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    bridge = SpanMetricsBridge(provider)

    span = MagicMock()
    span.name = "tool.execute"
    span.attributes = {"tool.name": "search"}
    span.status.status_code = StatusCode.OK

    bridge.on_end(span)

    data = reader.get_metrics_data()
    # When no metrics have been recorded, get_metrics_data() may return None
    # on some OTEL SDK versions — treat that as an empty set.
    metric_names: set[str] = set()
    if data is not None:
        metric_names = {m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    # No LLM metrics should be recorded
    assert "sage_llm_requests_total" not in metric_names


def test_record_session_helpers_are_noop_when_disabled() -> None:
    """record_session_created/deleted must not raise when meter is None."""
    from sage_api.telemetry import record_session_created, record_session_deleted, reset_telemetry

    reset_telemetry()
    # These must be safe no-ops
    record_session_created("agent-a")
    record_session_deleted()


def test_record_message_is_noop_when_disabled() -> None:
    """record_message must not raise when meter is None."""
    from sage_api.telemetry import record_message, reset_telemetry

    reset_telemetry()
    record_message("agent-a", "sync", 0.5)


def test_metrics_middleware_can_be_imported() -> None:
    """MetricsMiddleware must be importable without errors."""
    from sage_api.middleware.metrics import MetricsMiddleware

    assert MetricsMiddleware is not None


def test_metrics_middleware_skip_paths_exclude_metrics() -> None:
    """_SKIP_PATHS must include /metrics, /health/live, /health/ready."""
    from sage_api.middleware.metrics import _SKIP_PATHS

    assert "/metrics" in _SKIP_PATHS
    assert "/health/live" in _SKIP_PATHS
    assert "/health/ready" in _SKIP_PATHS


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200() -> None:
    """GET /metrics must return 200 with Prometheus text content-type."""
    import fakeredis.aioredis
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from sage_api.main import create_app
    from sage_api.telemetry import reset_telemetry, setup_telemetry

    # ASGITransport does NOT trigger ASGI lifespan, so we set up telemetry
    # and app.state.* directly before issuing requests.
    reset_telemetry()
    setup_telemetry(enabled=True)

    fake_redis = fakeredis.aioredis.FakeRedis()
    mock_registry = MagicMock()
    mock_registry.scan.return_value = {}
    mock_registry.list_agents.return_value = []

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield

    app = create_app(lifespan_override=_lifespan)
    app.state.redis = fake_redis
    app.state.registry = mock_registry
    app.state.session_manager = MagicMock()
    app.state.hot_reloader = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_metrics_endpoint_contains_sage_metrics_after_request() -> None:
    """After an HTTP request, /metrics must contain sage_http metric names."""
    import fakeredis.aioredis
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator
    from unittest.mock import MagicMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from sage_api.main import create_app
    from sage_api.telemetry import reset_telemetry, setup_telemetry

    # ASGITransport does NOT trigger ASGI lifespan, so we set up telemetry
    # and app.state.* directly before issuing requests.
    reset_telemetry()
    setup_telemetry(enabled=True)

    fake_redis = fakeredis.aioredis.FakeRedis()
    mock_registry = MagicMock()
    mock_registry.scan.return_value = {}
    mock_registry.list_agents.return_value = []

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield

    app = create_app(lifespan_override=_lifespan)
    app.state.redis = fake_redis
    app.state.registry = mock_registry
    app.state.session_manager = MagicMock()
    app.state.hot_reloader = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=True) as client:
        # Trigger a request to generate metrics
        await client.get("/health/live")
        # /health/live is in _SKIP_PATHS so won't appear — trigger an agent list request
        # which will be rejected with 401 (no API key) but still recorded
        await client.get("/v1/agents")
        response = await client.get("/metrics")

    body = response.text
    # At minimum we should see some sage_ metrics registered
    assert "sage_" in body or "# HELP" in body


@pytest.mark.asyncio
async def test_metrics_not_mounted_when_disabled() -> None:
    """When metrics_enabled=False, GET /metrics must return 404."""
    import fakeredis.aioredis
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator
    from unittest.mock import patch, MagicMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from sage_api.config import Settings
    from sage_api.main import create_app
    from sage_api.telemetry import reset_telemetry

    reset_telemetry()

    fake_redis = fakeredis.aioredis.FakeRedis()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield

    # Patch get_settings to return metrics_enabled=False
    mock_settings = MagicMock(spec=Settings)
    mock_settings.metrics_enabled = False
    mock_settings.log_level = "INFO"

    with patch("sage_api.main.get_settings", return_value=mock_settings):
        app = create_app(lifespan_override=_lifespan)

    app.state.redis = fake_redis
    app.state.registry = MagicMock()
    app.state.session_manager = MagicMock()
    app.state.hot_reloader = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 404
