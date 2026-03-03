"""OpenTelemetry metrics setup with Prometheus export and span bridge."""

from __future__ import annotations

from typing import Optional

from opentelemetry import context as context_api
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.trace import StatusCode

# ---------------------------------------------------------------------------
# Module-level state — initialised once by setup_telemetry()
# ---------------------------------------------------------------------------

_meter: metrics.Meter | None = None
_meter_provider: MeterProvider | None = None

# HTTP metric instruments
_http_requests_total: metrics.Counter | None = None
_http_request_duration: metrics.Histogram | None = None
_http_requests_active: metrics.UpDownCounter | None = None

# Session / message metric instruments
_sessions_created_total: metrics.Counter | None = None
_sessions_active: metrics.UpDownCounter | None = None
_messages_total: metrics.Counter | None = None
_message_duration: metrics.Histogram | None = None


def setup_telemetry(enabled: bool = True) -> None:
    """Initialise MeterProvider with PrometheusMetricReader and SpanMetricsBridge.

    Call once at application startup.  When *enabled* is False this is a
    complete no-op — all recording helpers become safe no-ops too.
    """
    global _meter, _meter_provider

    if not enabled:
        return

    from opentelemetry.exporter.prometheus import PrometheusMetricReader

    reader = PrometheusMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)
    _meter_provider = provider
    _meter = provider.get_meter("sage-api")
    _init_instruments(_meter)

    # Install a TracerProvider with SpanMetricsBridge so that llm.complete
    # spans emitted by sage-agent are captured as metric counters.
    # Note: if an agent's frontmatter configures `tracing: {enabled: true}`,
    # sage-agent will later replace this TracerProvider and LLM span metrics
    # will not be captured (HTTP/session metrics are unaffected).
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SpanMetricsBridge(provider))
    trace.set_tracer_provider(tracer_provider)


def reset_telemetry() -> None:
    """Reset module state.  **Test-only** — never call in production code."""
    global _meter, _meter_provider
    global _http_requests_total, _http_request_duration, _http_requests_active
    global _sessions_created_total, _sessions_active, _messages_total, _message_duration

    _meter = None
    _meter_provider = None
    _http_requests_total = None
    _http_request_duration = None
    _http_requests_active = None
    _sessions_created_total = None
    _sessions_active = None
    _messages_total = None
    _message_duration = None

    # Reset prometheus_client registry to avoid "Duplicated timeseries" errors in tests
    try:
        from prometheus_client import REGISTRY

        collectors = list(REGISTRY._names_to_collectors.values())
        for collector in set(collectors):
            try:
                REGISTRY.unregister(collector)
            except Exception:
                pass
    except Exception:
        pass


def get_meter() -> metrics.Meter | None:
    """Return the shared Meter, or ``None`` when telemetry is disabled."""
    return _meter


# ---------------------------------------------------------------------------
# Internal: instrument initialisation
# ---------------------------------------------------------------------------


def _init_instruments(meter: metrics.Meter) -> None:
    global _http_requests_total, _http_request_duration, _http_requests_active
    global _sessions_created_total, _sessions_active, _messages_total, _message_duration

    _http_requests_total = meter.create_counter(
        "sage_http_requests_total",
        description="Total HTTP requests",
    )
    _http_request_duration = meter.create_histogram(
        "sage_http_request_duration_seconds",
        description="HTTP request duration in seconds",
        unit="s",
    )
    _http_requests_active = meter.create_up_down_counter(
        "sage_http_requests_active",
        description="In-flight HTTP requests",
    )
    _sessions_created_total = meter.create_counter(
        "sage_sessions_created_total",
        description="Total sessions created",
    )
    _sessions_active = meter.create_up_down_counter(
        "sage_sessions_active",
        description="Currently active sessions",
    )
    _messages_total = meter.create_counter(
        "sage_messages_total",
        description="Total messages processed",
    )
    _message_duration = meter.create_histogram(
        "sage_message_duration_seconds",
        description="Agent message processing duration",
        unit="s",
    )


# ---------------------------------------------------------------------------
# Public recording helpers — all are safe no-ops when meter is None
# ---------------------------------------------------------------------------


def record_http_request(method: str, endpoint: str, status_code: int, duration_s: float) -> None:
    """Record a completed HTTP request."""
    if _http_requests_total is not None:
        _http_requests_total.add(1, {"method": method, "endpoint": endpoint, "status_code": str(status_code)})
    if _http_request_duration is not None:
        _http_request_duration.record(duration_s, {"method": method, "endpoint": endpoint})


def inc_http_active(method: str, endpoint: str) -> None:
    """Increment in-flight HTTP request gauge."""
    if _http_requests_active is not None:
        _http_requests_active.add(1, {"method": method, "endpoint": endpoint})


def dec_http_active(method: str, endpoint: str) -> None:
    """Decrement in-flight HTTP request gauge."""
    if _http_requests_active is not None:
        _http_requests_active.add(-1, {"method": method, "endpoint": endpoint})


def record_session_created(agent_name: str) -> None:
    """Record a new session being created."""
    if _sessions_created_total is not None:
        _sessions_created_total.add(1, {"agent_name": agent_name})
    if _sessions_active is not None:
        _sessions_active.add(1)


def record_session_deleted() -> None:
    """Record a session being deleted."""
    if _sessions_active is not None:
        _sessions_active.add(-1)


def record_message(agent_name: str, mode: str, duration_s: float) -> None:
    """Record a completed message (sync or stream).

    Args:
        agent_name: Name of the agent that processed the message.
        mode: ``"sync"`` or ``"stream"``.
        duration_s: Wall-clock seconds from request start to completion.
    """
    if _messages_total is not None:
        _messages_total.add(1, {"agent_name": agent_name, "mode": mode})
    if _message_duration is not None:
        _message_duration.record(duration_s, {"agent_name": agent_name, "mode": mode})


# ---------------------------------------------------------------------------
# SpanMetricsBridge
# ---------------------------------------------------------------------------


class SpanMetricsBridge(SpanProcessor):
    """Bridges ``llm.complete`` spans from sage-agent to Prometheus counters.

    Attach to the global ``TracerProvider`` so that every ``llm.complete``
    span emitted by sage-agent is converted to OTEL metric increments.
    LLM metrics are scoped to ``sage-api.span-bridge`` to keep them
    separate from the main ``sage-api`` meter.
    """

    def __init__(self, meter_provider: MeterProvider) -> None:
        meter = meter_provider.get_meter("sage-api.span-bridge")
        self._prompt_tokens = meter.create_counter(
            "sage_llm_prompt_tokens_total",
            description="Total LLM prompt tokens",
            unit="token",
        )
        self._completion_tokens = meter.create_counter(
            "sage_llm_completion_tokens_total",
            description="Total LLM completion tokens",
            unit="token",
        )
        self._cost = meter.create_counter(
            "sage_llm_cost_dollars_total",
            description="Total estimated LLM cost",
            unit="USD",
        )
        self._requests = meter.create_counter(
            "sage_llm_requests_total",
            description="Total LLM API requests",
        )

    def on_start(self, span: Span, parent_context: Optional[context_api.Context] = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        if span.name != "llm.complete":
            return

        attrs = span.attributes or {}
        model = str(attrs.get("model", "unknown"))
        status = "error" if span.status.status_code == StatusCode.ERROR else "ok"

        raw_prompt = attrs.get("prompt_tokens", 0) or 0
        raw_completion = attrs.get("completion_tokens", 0) or 0
        raw_cost = attrs.get("cost", 0.0) or 0.0
        prompt = int(raw_prompt) if isinstance(raw_prompt, (int, float)) else 0
        completion = int(raw_completion) if isinstance(raw_completion, (int, float)) else 0
        cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else 0.0

        labels: dict[str, str] = {"model": model}
        self._prompt_tokens.add(prompt, labels)
        self._completion_tokens.add(completion, labels)
        self._cost.add(cost, labels)
        self._requests.add(1, {**labels, "status": status})

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
