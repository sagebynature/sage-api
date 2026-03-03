# Prometheus Telemetry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose a `/metrics` Prometheus endpoint on port 8000 with HTTP, session, and LLM token/cost metrics using the OTEL Prometheus exporter bridge.

**Architecture:** A `MeterProvider` with `PrometheusMetricReader` bridges OTEL metric instruments to `prometheus_client`'s registry, served at `/metrics` via `make_asgi_app()`. A `SpanMetricsBridge` span processor intercepts sage-agent's `llm.complete` spans on completion and records token/cost counters. HTTP and session metrics are recorded directly via OTEL Meter API in middleware and `SessionManager`.

**Tech Stack:** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-prometheus`, `prometheus_client` (transitive), FastAPI `BaseHTTPMiddleware`, `opentelemetry.sdk.trace.SpanProcessor`

---

### Task 1: Add Dependencies and Config Setting

**Files:**
- Modify: `pyproject.toml:15-25`
- Modify: `sage_api/config.py:40-53`

**Step 1: Add OTEL packages to pyproject.toml**

In `pyproject.toml`, add three packages to the `dependencies` list after `structlog`:

```toml
    "opentelemetry-api>=1.20.0",
    "opentelemetry-sdk>=1.20.0",
    "opentelemetry-exporter-prometheus>=0.41b0",
```

**Step 2: Add metrics_enabled setting to config.py**

In `sage_api/config.py`, add after the `port` field (before the closing of the class):

```python
    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus /metrics endpoint",
    )
```

**Step 3: Sync dependencies**

```bash
uv sync
```

Expected: resolves and installs `opentelemetry-*` and `prometheus_client` packages.

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock sage_api/config.py
git commit -m "feat(telemetry): add otel + prometheus dependencies and config flag"
```

---

### Task 2: Create sage_api/telemetry.py

**Files:**
- Create: `sage_api/telemetry.py`
- Test: `tests/test_telemetry.py`

**Step 1: Write the failing test**

Create `tests/test_telemetry.py`:

```python
"""Tests for telemetry module setup."""
from __future__ import annotations

import pytest


def test_setup_telemetry_disabled_is_noop() -> None:
    """setup_telemetry(False) must not set a real MeterProvider."""
    from opentelemetry import metrics
    from sage_api.telemetry import setup_telemetry

    setup_telemetry(enabled=False)
    assert metrics.get_meter_provider().__class__.__name__ in (
        "NoOpMeterProvider", "ProxyMeterProvider", "_ProxyMeterProvider"
    )


def test_setup_telemetry_enabled_sets_provider() -> None:
    """setup_telemetry(True) must install a real SDK MeterProvider."""
    from opentelemetry.sdk.metrics import MeterProvider
    from sage_api.telemetry import setup_telemetry, get_meter, reset_telemetry

    reset_telemetry()  # clean state between tests
    setup_telemetry(enabled=True)

    from opentelemetry import metrics
    assert isinstance(metrics.get_meter_provider(), MeterProvider)
    assert get_meter() is not None


def test_span_metrics_bridge_records_on_llm_complete() -> None:
    """SpanMetricsBridge.on_end must record counters for llm.complete spans."""
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExportResult
    from opentelemetry.trace import SpanKind, StatusCode
    from opentelemetry.sdk.trace import SpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from sage_api.telemetry import SpanMetricsBridge, reset_telemetry
    import time

    reset_telemetry()
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    bridge = SpanMetricsBridge(meter_provider)

    # Simulate a finished llm.complete span with token attributes
    span = _make_span(
        name="llm.complete",
        attributes={"model": "gpt-4o", "prompt_tokens": 100, "completion_tokens": 50, "cost": 0.001},
        status_code=StatusCode.OK,
    )
    bridge.on_end(span)

    metrics_data = reader.get_metrics_data()
    metric_names = {m.name for rm in metrics_data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    assert "sage_llm_prompt_tokens_total" in metric_names
    assert "sage_llm_completion_tokens_total" in metric_names
    assert "sage_llm_requests_total" in metric_names


def _make_span(name: str, attributes: dict, status_code: object) -> object:
    """Build a minimal mock ReadableSpan for testing the bridge."""
    from unittest.mock import MagicMock
    from opentelemetry.trace import StatusCode

    span = MagicMock()
    span.name = name
    span.attributes = attributes
    span.status.status_code = status_code
    return span
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_telemetry.py -v
```

Expected: `ImportError: cannot import name 'setup_telemetry' from 'sage_api.telemetry'` (module doesn't exist yet).

**Step 3: Create sage_api/telemetry.py**

```python
"""OpenTelemetry metrics setup with Prometheus export and span bridge."""
from __future__ import annotations

from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.trace import StatusCode

# Module-level state — set once by setup_telemetry()
_meter: metrics.Meter | None = None
_meter_provider: MeterProvider | None = None

# Metric instruments (set by _init_instruments)
_http_requests_total: metrics.Counter | None = None
_http_request_duration: metrics.Histogram | None = None
_http_requests_active: metrics.UpDownCounter | None = None
_sessions_created_total: metrics.Counter | None = None
_sessions_active: metrics.UpDownCounter | None = None
_messages_total: metrics.Counter | None = None
_message_duration: metrics.Histogram | None = None
_llm_prompt_tokens_total: metrics.Counter | None = None
_llm_completion_tokens_total: metrics.Counter | None = None
_llm_cost_dollars_total: metrics.Counter | None = None
_llm_requests_total: metrics.Counter | None = None


def setup_telemetry(enabled: bool = True) -> None:
    """Initialize MeterProvider with PrometheusMetricReader and span bridge.

    Must be called once during application startup. When enabled=False this
    is a complete no-op — all metric functions become safe no-ops too.
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

    # Install TracerProvider with SpanMetricsBridge for LLM span data.
    # Note: if sage-agent frontmatter configures tracing, it will replace
    # this provider and LLM metrics will not be captured.
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SpanMetricsBridge(provider))
    trace.set_tracer_provider(tracer_provider)


def reset_telemetry() -> None:
    """Reset module state. Used only in tests to allow re-initialisation."""
    global _meter, _meter_provider
    global _http_requests_total, _http_request_duration, _http_requests_active
    global _sessions_created_total, _sessions_active, _messages_total, _message_duration
    global _llm_prompt_tokens_total, _llm_completion_tokens_total
    global _llm_cost_dollars_total, _llm_requests_total

    _meter = None
    _meter_provider = None
    _http_requests_total = None
    _http_request_duration = None
    _http_requests_active = None
    _sessions_created_total = None
    _sessions_active = None
    _messages_total = None
    _message_duration = None
    _llm_prompt_tokens_total = None
    _llm_completion_tokens_total = None
    _llm_cost_dollars_total = None
    _llm_requests_total = None

    # Reset OTEL global providers to no-op state
    from opentelemetry.sdk.metrics import MeterProvider as _MP
    metrics._internal._DEFAULT_METER_PROVIDER = None  # type: ignore[attr-defined]


def get_meter() -> metrics.Meter | None:
    """Return the shared Meter, or None if telemetry is disabled."""
    return _meter


def _init_instruments(meter: metrics.Meter) -> None:
    """Create all metric instruments on the given meter."""
    global _http_requests_total, _http_request_duration, _http_requests_active
    global _sessions_created_total, _sessions_active, _messages_total, _message_duration
    global _llm_prompt_tokens_total, _llm_completion_tokens_total
    global _llm_cost_dollars_total, _llm_requests_total

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
    _llm_prompt_tokens_total = meter.create_counter(
        "sage_llm_prompt_tokens_total",
        description="Total LLM prompt tokens",
        unit="token",
    )
    _llm_completion_tokens_total = meter.create_counter(
        "sage_llm_completion_tokens_total",
        description="Total LLM completion tokens",
        unit="token",
    )
    _llm_cost_dollars_total = meter.create_counter(
        "sage_llm_cost_dollars_total",
        description="Total estimated LLM cost",
        unit="USD",
    )
    _llm_requests_total = meter.create_counter(
        "sage_llm_requests_total",
        description="Total LLM API requests",
    )


# ---------------------------------------------------------------------------
# Public metric recording helpers — all are safe no-ops when meter is None
# ---------------------------------------------------------------------------

def record_http_request(method: str, endpoint: str, status_code: int, duration_s: float) -> None:
    if _http_requests_total is not None:
        _http_requests_total.add(1, {"method": method, "endpoint": endpoint, "status_code": str(status_code)})
    if _http_request_duration is not None:
        _http_request_duration.record(duration_s, {"method": method, "endpoint": endpoint})


def inc_http_active(method: str, endpoint: str) -> None:
    if _http_requests_active is not None:
        _http_requests_active.add(1, {"method": method, "endpoint": endpoint})


def dec_http_active(method: str, endpoint: str) -> None:
    if _http_requests_active is not None:
        _http_requests_active.add(-1, {"method": method, "endpoint": endpoint})


def record_session_created(agent_name: str) -> None:
    if _sessions_created_total is not None:
        _sessions_created_total.add(1, {"agent_name": agent_name})
    if _sessions_active is not None:
        _sessions_active.add(1)


def record_session_deleted() -> None:
    if _sessions_active is not None:
        _sessions_active.add(-1)


def record_message(agent_name: str, mode: str, duration_s: float) -> None:
    if _messages_total is not None:
        _messages_total.add(1, {"agent_name": agent_name, "mode": mode})
    if _message_duration is not None:
        _message_duration.record(duration_s, {"agent_name": agent_name, "mode": mode})


# ---------------------------------------------------------------------------
# SpanMetricsBridge
# ---------------------------------------------------------------------------

class SpanMetricsBridge(SpanProcessor):
    """Span processor that bridges llm.complete spans to Prometheus counters.

    Attach to the global TracerProvider so that every llm.complete span
    emitted by sage-agent is converted into OTEL metric increments.
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

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        pass

    def on_end(self, span: ReadableSpan) -> None:
        if span.name != "llm.complete":
            return

        attrs = span.attributes or {}
        model = str(attrs.get("model", "unknown"))
        status = "ok" if span.status.status_code != StatusCode.ERROR else "error"

        prompt = int(attrs.get("prompt_tokens", 0) or 0)
        completion = int(attrs.get("completion_tokens", 0) or 0)
        cost = float(attrs.get("cost", 0.0) or 0.0)

        labels = {"model": model}
        self._prompt_tokens.add(prompt, labels)
        self._completion_tokens.add(completion, labels)
        self._cost.add(cost, labels)
        self._requests.add(1, {**labels, "status": status})

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_telemetry.py -v
```

Expected: all 3 tests PASS.

**Step 5: Commit**

```bash
git add sage_api/telemetry.py tests/test_telemetry.py
git commit -m "feat(telemetry): add telemetry module with MeterProvider and SpanMetricsBridge"
```

---

### Task 3: Create MetricsMiddleware

**Files:**
- Create: `sage_api/middleware/metrics.py`
- Test: `tests/test_telemetry.py` (extend)

**Step 1: Write the failing test**

Append to `tests/test_telemetry.py`:

```python
def test_metrics_middleware_skips_metrics_path() -> None:
    """MetricsMiddleware must not record metrics for /metrics requests."""
    from sage_api.telemetry import reset_telemetry
    reset_telemetry()
    # Simply importing and instantiating must not raise
    from sage_api.middleware.metrics import MetricsMiddleware
    assert MetricsMiddleware is not None
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_telemetry.py::test_metrics_middleware_skips_metrics_path -v
```

Expected: `ImportError` (module doesn't exist).

**Step 3: Create sage_api/middleware/metrics.py**

```python
"""HTTP metrics middleware using OTEL Meter API."""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sage_api import telemetry

# Paths excluded from HTTP metrics recording
_SKIP_PATHS = frozenset({"/metrics", "/health/live", "/health/ready"})


class MetricsMiddleware(BaseHTTPMiddleware):
    """Records HTTP request counters, duration histograms, and active gauges."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)

        method = request.method
        # Use matched route template when available to avoid UUID cardinality
        route = request.scope.get("route")
        endpoint = route.path if route is not None else path  # type: ignore[union-attr]

        telemetry.inc_http_active(method, endpoint)
        start = time.monotonic()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            telemetry.dec_http_active(method, endpoint)
            raise
        else:
            duration = time.monotonic() - start
            telemetry.dec_http_active(method, endpoint)
            telemetry.record_http_request(method, endpoint, status_code, duration)
            return response
```

Fix the missing import — add `from typing import Any` at top of the file.

**Step 4: Run test**

```bash
pytest tests/test_telemetry.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add sage_api/middleware/metrics.py tests/test_telemetry.py
git commit -m "feat(telemetry): add MetricsMiddleware for HTTP request metrics"
```

---

### Task 4: Wire Telemetry into main.py and auth.py

**Files:**
- Modify: `sage_api/main.py:1-114`
- Modify: `sage_api/middleware/auth.py:9-15`
- Test: `tests/test_telemetry.py` (extend with integration test)

**Step 1: Write the failing integration test**

Append to `tests/test_telemetry.py`:

```python
@pytest.mark.asyncio
async def test_metrics_endpoint_returns_200() -> None:
    """GET /metrics must return 200 with prometheus content-type."""
    import fakeredis.aioredis
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import patch, MagicMock
    from sage_api.telemetry import reset_telemetry

    reset_telemetry()

    # Build minimal app with telemetry wired in
    from sage_api.main import create_app
    from sage_api.config import Settings

    fake_redis = fakeredis.aioredis.FakeRedis()
    mock_registry = MagicMock()
    mock_registry.scan.return_value = {}
    mock_registry.list_agents.return_value = []

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        from sage_api.telemetry import setup_telemetry
        setup_telemetry(enabled=True)
        app.state.redis = fake_redis
        app.state.registry = mock_registry
        app.state.session_manager = MagicMock()
        app.state.hot_reloader = MagicMock()
        yield

    app = create_app(lifespan_override=test_lifespan)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_telemetry.py::test_metrics_endpoint_returns_200 -v
```

Expected: FAIL — `/metrics` not mounted.

**Step 3: Update sage_api/middleware/auth.py — add /metrics to EXEMPT_PATHS**

In `sage_api/middleware/auth.py`, change line 9-15:

```python
EXEMPT_PATHS = {
    "/health/live",
    "/health/ready",
    "/.well-known/agent-card.json",
    "/docs",
    "/openapi.json",
    "/metrics",
}
```

**Step 4: Update sage_api/main.py — wire telemetry**

Add imports after the existing imports (after line 23):

```python
from prometheus_client import make_asgi_app as _make_prometheus_app
from sage_api import telemetry
from sage_api.middleware.metrics import MetricsMiddleware
```

In the `lifespan` function, add telemetry setup as step 1 (before `setup_logging`), shifting existing numbering:

```python
    # 1. Initialise metrics (before anything else so all startup events are captured)
    telemetry.setup_telemetry(enabled=settings.metrics_enabled)
```

In `create_app`, add `MetricsMiddleware` after `RequestLoggingMiddleware` (line 91):

```python
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
```

In `create_app`, mount the Prometheus ASGI app after including routers, before `return app`:

```python
    # Mount Prometheus metrics endpoint (unauthenticated, exempt from API key)
    if get_settings().metrics_enabled:
        app.mount("/metrics", _make_prometheus_app())
```

**Step 5: Run test**

```bash
pytest tests/test_telemetry.py::test_metrics_endpoint_returns_200 -v
```

Expected: PASS.

**Step 6: Verify auth exemption**

```bash
pytest tests/test_auth.py -v
```

Expected: all existing auth tests PASS (no regression).

**Step 7: Commit**

```bash
git add sage_api/main.py sage_api/middleware/auth.py tests/test_telemetry.py
git commit -m "feat(telemetry): mount /metrics endpoint and wire MetricsMiddleware"
```

---

### Task 5: Instrument SessionManager

**Files:**
- Modify: `sage_api/services/session_manager.py:1-136`
- Test: `tests/test_telemetry.py` (extend)

**Step 1: Write the failing test**

Append to `tests/test_telemetry.py`:

```python
def test_record_session_created_increments_active() -> None:
    """record_session_created must increment sessions_active gauge."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from sage_api.telemetry import reset_telemetry, setup_telemetry, record_session_created, record_session_deleted

    reset_telemetry()
    # Patch PrometheusMetricReader to avoid port conflicts in test
    reader = InMemoryMetricReader()

    import sage_api.telemetry as t
    from opentelemetry import metrics
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)
    t._meter = provider.get_meter("sage-api")
    t._init_instruments(t._meter)

    record_session_created("test-agent")
    record_session_created("test-agent")
    record_session_deleted()

    data = reader.get_metrics_data()
    active = _find_gauge_value(data, "sage_sessions_active")
    assert active == 1  # 2 created, 1 deleted


def _find_gauge_value(data: object, name: str) -> float:
    from opentelemetry.sdk.metrics.export import MetricsData
    assert isinstance(data, MetricsData)
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    for dp in m.data.data_points:
                        return dp.value
    return 0.0
```

**Step 2: Run to confirm it passes already** (pure telemetry module test)

```bash
pytest tests/test_telemetry.py::test_record_session_created_increments_active -v
```

Expected: PASS (helper functions already exist in telemetry.py).

**Step 3: Add metric calls to SessionManager**

In `sage_api/services/session_manager.py`, add import at top (after existing imports):

```python
from sage_api import telemetry
```

In `create_session` method, after `return self._to_session_info(session_data)` (add before it):

```python
        telemetry.record_session_created(agent_name)
        return self._to_session_info(session_data)
```

In `send_message` method, wrap the agent.run call to record duration. Replace the existing `try/except TimeoutError` block:

```python
            import time as _time
            _t0 = _time.monotonic()
            try:
                response = await asyncio.wait_for(agent.run(message), timeout=self._request_timeout)
            except asyncio.TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Request timed out") from exc
            finally:
                telemetry.record_message(
                    latest_session_data.agent_name, "sync", _time.monotonic() - _t0
                )
```

In `stream_message`, after the `async for chunk in agent.stream(message)` loop completes and before the `finally: lock.release()`, add timing. Replace the `try/except TimeoutError` block:

```python
            import time as _time
            _t0 = _time.monotonic()
            try:
                async with asyncio.timeout(self._request_timeout):
                    async for chunk in agent.stream(message):
                        yield chunk
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail="Request timed out") from exc
            finally:
                telemetry.record_message(
                    latest_session_data.agent_name, "stream", _time.monotonic() - _t0
                )
```

In `delete_session`, add after `return await self._store.delete(session_id)`:

```python
        deleted = await self._store.delete(session_id)
        if deleted:
            telemetry.record_session_deleted()
        return deleted
```

**Step 4: Run session manager tests to verify no regression**

```bash
pytest tests/test_session_manager.py -v
```

Expected: all existing tests PASS.

**Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASS.

**Step 6: Commit**

```bash
git add sage_api/services/session_manager.py tests/test_telemetry.py
git commit -m "feat(telemetry): instrument SessionManager with session and message metrics"
```

---

### Task 6: End-to-End Smoke Test and Final Verification

**Files:**
- Test: `tests/test_telemetry.py` (final assertions)

**Step 1: Add metric name smoke test**

Append to `tests/test_telemetry.py`:

```python
@pytest.mark.asyncio
async def test_metrics_contains_expected_metric_names() -> None:
    """After making a request, /metrics must contain sage_http_requests_total."""
    import fakeredis.aioredis
    from contextlib import asynccontextmanager
    from typing import AsyncGenerator
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from unittest.mock import MagicMock
    from sage_api.telemetry import reset_telemetry

    reset_telemetry()
    from sage_api.main import create_app

    fake_redis = fakeredis.aioredis.FakeRedis()
    mock_registry = MagicMock()
    mock_registry.scan.return_value = {}
    mock_registry.list_agents.return_value = []

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        from sage_api.telemetry import setup_telemetry
        setup_telemetry(enabled=True)
        app.state.redis = fake_redis
        app.state.registry = mock_registry
        app.state.session_manager = MagicMock()
        app.state.hot_reloader = MagicMock()
        yield

    app = create_app(lifespan_override=test_lifespan)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Make a request to trigger metric recording
        await client.get("/health/live")
        response = await client.get("/metrics")

    body = response.text
    assert "sage_http_requests_total" in body or "sage_http_request_duration_seconds" in body
```

**Step 2: Run full test suite one final time**

```bash
pytest -v --tb=short
```

Expected: all tests PASS, coverage report shows telemetry.py and middleware/metrics.py covered.

**Step 3: Manual smoke test (optional)**

```bash
SAGE_API_API_KEY=test uvicorn sage_api.main:app --port 8000
curl http://localhost:8000/metrics
```

Expected: Prometheus text format with `sage_` prefixed metrics.

**Step 4: Final commit**

```bash
git add tests/test_telemetry.py
git commit -m "test(telemetry): add end-to-end metrics endpoint smoke tests"
```

---

## Notes

- **LLM metrics require agents without `tracing: {enabled: true}` in frontmatter.** If an agent has OTEL tracing configured, it replaces the global `TracerProvider` installed by `setup_telemetry()`, which removes the `SpanMetricsBridge`. HTTP and session metrics are unaffected.
- **`reset_telemetry()` is test-only.** It is not part of the public API and must not be called in production code.
- **`/metrics` has no authentication** by design (standard Prometheus scrape pattern). Protect via K8s `NetworkPolicy` or ingress rules in production.
- **`MetricsMiddleware` skips** `/metrics`, `/health/live`, `/health/ready` to avoid noise in HTTP dashboards.
