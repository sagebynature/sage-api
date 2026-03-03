# Prometheus Telemetry Design

**Date:** 2026-03-03
**Status:** Approved

## Overview

Add a Prometheus `/metrics` endpoint to sage-api exposing full-stack observability: HTTP request metrics, agent session/message metrics, and LLM token/cost metrics bridged from sage-agent's existing OpenTelemetry trace spans.

## Approach

OTEL-native metrics using `opentelemetry-exporter-prometheus`. A `MeterProvider` with `PrometheusMetricReader` bridges OTEL metric instruments to the `prometheus_client` registry, which is served as an ASGI app mounted at `/metrics`. A custom `SpanMetricsBridge` span processor sits on the global `TracerProvider` and intercepts sage-agent's `llm.complete` spans on completion to record token/cost counters as OTEL metrics.

## Architecture

```
sage-api process
├── FastAPI app (port 8000)
│   ├── GET /metrics  ← prometheus_client ASGI app (unauthenticated, auth-exempt)
│   ├── MetricsMiddleware  ← HTTP counters + histograms via OTEL Meter API
│   └── ... existing routes
│
├── OTEL MeterProvider
│   └── PrometheusMetricReader  ← bridges OTEL metrics → prometheus_client registry
│
├── OTEL TracerProvider (global, shared with sage-agent)
│   └── SpanMetricsBridge (SpanProcessor)
│       └── on llm.complete span end → records token/cost counters
│
└── sage_api/telemetry.py
    ├── setup_telemetry()  ← called in lifespan startup
    ├── get_meter()        ← returns shared Meter
    └── SpanMetricsBridge  ← SpanProcessor subclass
```

## Metrics Catalog

| Metric | Type | Labels | Source |
|--------|------|--------|--------|
| `sage_http_requests_total` | Counter | `method`, `endpoint`, `status_code` | MetricsMiddleware |
| `sage_http_request_duration_seconds` | Histogram | `method`, `endpoint` | MetricsMiddleware |
| `sage_http_requests_active` | UpDownCounter | `method`, `endpoint` | MetricsMiddleware |
| `sage_sessions_created_total` | Counter | `agent_name` | SessionManager |
| `sage_sessions_active` | UpDownCounter | — | SessionManager |
| `sage_messages_total` | Counter | `agent_name`, `mode` | SessionManager |
| `sage_message_duration_seconds` | Histogram | `agent_name`, `mode` | SessionManager |
| `sage_llm_prompt_tokens_total` | Counter | `model` | SpanMetricsBridge |
| `sage_llm_completion_tokens_total` | Counter | `model` | SpanMetricsBridge |
| `sage_llm_cost_dollars_total` | Counter | `model` | SpanMetricsBridge |
| `sage_llm_requests_total` | Counter | `model`, `status` | SpanMetricsBridge |

`mode` values: `sync`, `stream`. `status` values: `ok`, `error`.

## Files Changed

### New Files
- `sage_api/telemetry.py` — `setup_telemetry()`, `get_meter()`, `SpanMetricsBridge`, metric instrument singletons
- `sage_api/middleware/metrics.py` — `MetricsMiddleware` recording HTTP metrics via OTEL Meter API
- `tests/test_telemetry.py` — endpoint smoke test, metric name assertions, session gauge test

### Modified Files
- `sage_api/main.py` — call `setup_telemetry()` in lifespan, mount `/metrics` ASGI app, add `MetricsMiddleware`
- `sage_api/middleware/auth.py` — add `/metrics` to auth-exempt paths
- `sage_api/services/session_manager.py` — record session/message metrics at create/delete/send
- `sage_api/config.py` — add `SAGE_API_METRICS_ENABLED: bool = True`
- `pyproject.toml` — add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-prometheus`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SAGE_API_METRICS_ENABLED` | `true` | Enable/disable the entire metrics stack |

When `false`, `setup_telemetry()` is a no-op and `/metrics` is not mounted.

## Security

`/metrics` is unauthenticated (standard Prometheus scrape pattern). It is added to the auth middleware's exempt path list alongside `/health/live` and `/health/ready`. Network-level access control (K8s NetworkPolicy) is the recommended protection for production.

## Testing Strategy

- `GET /metrics` returns 200 with `Content-Type: text/plain; version=0.0.4`
- After a test request, assert `sage_http_requests_total` appears in output
- Create/delete a session in tests, assert `sage_sessions_active` gauge reflects changes
- `SAGE_API_METRICS_ENABLED=false` → `/metrics` returns 404

## Dependencies Added

```toml
"opentelemetry-api>=1.20",
"opentelemetry-sdk>=1.20",
"opentelemetry-exporter-prometheus>=0.41b0",
```

`opentelemetry-exporter-prometheus` pulls in `prometheus_client` transitively.
