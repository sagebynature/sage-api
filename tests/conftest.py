"""Test configuration and fixtures."""

import sys
from pathlib import Path

# Add sage package to path for imports
sage_path = Path(__file__).parent.parent.parent / "sage"
if str(sage_path) not in sys.path:
    sys.path.insert(0, str(sage_path))




import pytest
from httpx import AsyncClient, ASGITransport
import fakeredis.aioredis


@pytest.fixture
async def fake_redis():
    """Provide a fake Redis client for testing."""
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
async def client():
    """Provide an async HTTP client for testing.

    Note: This fixture requires an 'app' fixture to be defined in the test module.
    For now, we provide a minimal implementation that can be overridden.
    """

    # Placeholder: In actual tests, override this with a real FastAPI app
    class MinimalApp:
        async def __call__(self, scope, receive, send):
            # Minimal ASGI app for testing
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"status":"ok"}',
                }
            )

    app = MinimalApp()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
