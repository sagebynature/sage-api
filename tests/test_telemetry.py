"""Tests for the telemetry module."""

from __future__ import annotations

from unittest.mock import MagicMock


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
