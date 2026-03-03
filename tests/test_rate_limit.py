import asyncio

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from sage_api.config import get_settings
from sage_api.middleware.rate_limit import RateLimitMiddleware


@pytest.fixture(autouse=True)
def configure_test_settings(monkeypatch):
    monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def build_app(config):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.redis = FakeRedis()
    if config is not None:
        app.state.rate_limit_config = config
    app.add_middleware(RateLimitMiddleware)
    return app


@pytest.mark.asyncio
async def test_passthrough_when_rate_limit_config_missing():
    app = build_app(config=None)

    @app.post("/test")
    async def test_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/test", content=b"x" * 1024)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_passes_when_all_limits_are_zero_disabled():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.post("/v1/agents/test/messages/stream")
    async def stream_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.post(
                "/v1/agents/test/messages/stream",
                content=b"x" * 2048,
                headers={"x-api-key": "k-disabled"},
            )
            for _ in range(3)
        ]

    assert all(resp.status_code == 200 for resp in responses)


@pytest.mark.asyncio
async def test_body_size_above_max_returns_413():
    app = build_app(config={"rpm": 0, "max_body_bytes": 4, "max_concurrent_streams": 0})

    @app.post("/upload")
    async def upload_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", content=b"12345")

    assert response.status_code == 413
    assert response.json() == {
        "error": "Request Entity Too Large",
        "detail": "Body exceeds 4 bytes",
        "status_code": 413,
    }


@pytest.mark.asyncio
async def test_body_size_within_limit_passes():
    app = build_app(config={"rpm": 0, "max_body_bytes": 5, "max_concurrent_streams": 0})

    @app.post("/upload")
    async def upload_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", content=b"12345")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_body_size_check_disabled_when_max_body_zero():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.post("/upload")
    async def upload_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", content=b"x" * 8192)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_rpm_limit_first_n_pass_then_n_plus_one_429(monkeypatch):
    app = build_app(config={"rpm": 2, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.get("/limited")
    async def limited_route():
        return {"ok": True}

    monkeypatch.setattr("sage_api.middleware.rate_limit.time.time", lambda: 120.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/limited", headers={"x-api-key": "rpm-key"})
        second = await client.get("/limited", headers={"x-api-key": "rpm-key"})
        third = await client.get("/limited", headers={"x-api-key": "rpm-key"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers.get("Retry-After") == "60"
    assert third.json() == {
        "error": "Too Many Requests",
        "detail": "Rate limit of 2 requests per minute exceeded",
        "status_code": 429,
    }


@pytest.mark.asyncio
async def test_rpm_windows_are_isolated(monkeypatch):
    app = build_app(config={"rpm": 1, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.get("/limited")
    async def limited_route():
        return {"ok": True}

    current_ts = [60.0]  # mutable container so the lambda can advance it
    monkeypatch.setattr(
        "sage_api.middleware.rate_limit.time.time",
        lambda: current_ts[0],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/limited", headers={"x-api-key": "window-key"})
        current_ts[0] = 120.0
        second = await client.get("/limited", headers={"x-api-key": "window-key"})

    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_rpm_disabled_when_zero():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.get("/limited")
    async def limited_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [await client.get("/limited", headers={"x-api-key": "rpm-disabled"}) for _ in range(4)]

    assert all(resp.status_code == 200 for resp in responses)


@pytest.mark.asyncio
async def test_stream_cap_first_n_pass_then_n_plus_one_429():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 1})
    started = asyncio.Event()
    release = asyncio.Event()

    @app.post("/v1/agents/test/messages/stream")
    async def stream_route():
        started.set()
        await release.wait()
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_task = asyncio.create_task(
            client.post("/v1/agents/test/messages/stream", headers={"x-api-key": "stream-key"})
        )
        await started.wait()

        second = await client.post("/v1/agents/test/messages/stream", headers={"x-api-key": "stream-key"})
        release.set()
        first = await first_task

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {
        "error": "Too Many Streams",
        "detail": "Max 1 concurrent streams exceeded",
        "status_code": 429,
    }


@pytest.mark.asyncio
async def test_stream_counter_decrements_after_response_completes():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 1})

    @app.post("/v1/agents/test/messages/stream")
    async def stream_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/v1/agents/test/messages/stream", headers={"x-api-key": "stream-key"})
        second = await client.post("/v1/agents/test/messages/stream", headers={"x-api-key": "stream-key"})

    stream_value = await app.state.redis.get("streams:stream-key")

    assert first.status_code == 200
    assert second.status_code == 200
    assert stream_value == b"0"


@pytest.mark.asyncio
async def test_stream_cap_disabled_when_zero():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 0})

    @app.post("/v1/agents/test/messages/stream")
    async def stream_route():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.post("/v1/agents/test/messages/stream", headers={"x-api-key": "stream-disabled"})
            for _ in range(3)
        ]

    assert all(resp.status_code == 200 for resp in responses)


@pytest.mark.asyncio
async def test_exempt_paths_bypass_all_checks(monkeypatch):
    app = build_app(config={"rpm": 1, "max_body_bytes": 1, "max_concurrent_streams": 1})
    exempt_paths = [
        "/health/live",
        "/health/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/.well-known/agent-card.json",
    ]

    for path in exempt_paths:
        app.add_api_route(path, endpoint=lambda: {"ok": True}, methods=["GET", "POST"])

    monkeypatch.setattr("sage_api.middleware.rate_limit.time.time", lambda: 180.0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            for path in exempt_paths:
                response = await client.post(path, content=b"too-large", headers={"x-api-key": "exempt-key"})
                assert response.status_code == 200

    rpm_key = "ratelimit:exempt-key:3"
    stream_key = "streams:exempt-key"
    assert await app.state.redis.get(rpm_key) is None
    assert await app.state.redis.get(stream_key) is None


@pytest.mark.asyncio
async def test_non_stream_paths_do_not_count_toward_stream_limit():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 1})

    @app.post("/v1/agents/test/messages")
    async def non_stream_route(request: Request):
        payload = await request.body()
        await asyncio.sleep(0.05)
        return {"size": len(payload)}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_task = asyncio.create_task(
            client.post("/v1/agents/test/messages", content=b"one", headers={"x-api-key": "same-key"})
        )
        second_task = asyncio.create_task(
            client.post("/v1/agents/test/messages", content=b"two", headers={"x-api-key": "same-key"})
        )
        first, second = await asyncio.gather(first_task, second_task)

    stream_key = await app.state.redis.get("streams:same-key")
    assert first.status_code == 200
    assert second.status_code == 200
    assert stream_key is None


@pytest.mark.asyncio
async def test_a2a_post_path_counts_as_stream():
    app = build_app(config={"rpm": 0, "max_body_bytes": 0, "max_concurrent_streams": 1})
    started = asyncio.Event()
    release = asyncio.Event()

    @app.post("/a2a")
    async def a2a_route():
        started.set()
        await release.wait()
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_task = asyncio.create_task(client.post("/a2a", headers={"x-api-key": "a2a-key"}))
        await started.wait()

        second = await client.post("/a2a", headers={"x-api-key": "a2a-key"})
        release.set()
        first = await first_task

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {
        "error": "Too Many Streams",
        "detail": "Max 1 concurrent streams exceeded",
        "status_code": 429,
    }
