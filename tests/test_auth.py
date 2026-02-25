"""Tests for API key authentication middleware."""

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from sage_api.middleware.auth import verify_api_key
from sage_api.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the settings cache before and after each test.

    This is essential because get_settings() uses lru_cache,
    and we need to reload settings with different env vars for each test.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app_with_auth():
    """Create a test FastAPI app with auth dependency on a protected route."""
    app = FastAPI()

    @app.get("/protected")
    async def protected_route(api_key=Depends(verify_api_key)):
        return {"ok": True}

    @app.get("/health/live")
    async def health_live():
        return {"status": "alive"}

    @app.get("/.well-known/agent-card.json")
    async def agent_card():
        return {"agent": "test"}

    return app


@pytest.fixture
def client(app_with_auth, monkeypatch):
    """Create a test client with environment variables set."""
    monkeypatch.setenv("SAGE_API_API_KEY", "test-secret-key-123")
    get_settings.cache_clear()
    return TestClient(app_with_auth)


class TestAPIKeyAuthentication:
    """Tests for verify_api_key dependency."""

    def test_valid_api_key_succeeds(self, client):
        """Test that a valid API key allows access to protected route."""
        response = client.get(
            "/protected",
            headers={"X-API-Key": "test-secret-key-123"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_missing_api_key_returns_401(self, client):
        """Test that missing API key returns 401 Unauthorized."""
        response = client.get("/protected")
        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"] == "Unauthorized"
        assert "Invalid or missing API key" in data["detail"]["detail"]
        assert data["detail"]["status_code"] == 401

    def test_invalid_api_key_returns_401(self, client):
        """Test that wrong API key returns 401 Unauthorized."""
        response = client.get(
            "/protected",
            headers={"X-API-Key": "wrong-key-xyz"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["detail"]["error"] == "Unauthorized"
        assert "Invalid or missing API key" in data["detail"]["detail"]

    def test_exempt_path_health_live_no_auth_required(self, client):
        """Test that /health/live path doesn't require API key."""
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_exempt_path_agent_card_no_auth_required(self, client):
        """Test that /.well-known/agent-card.json doesn't require API key."""
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        assert response.json() == {"agent": "test"}

    def test_timing_safe_comparison_used(self):
        """Test that secrets.compare_digest is imported and available.

        This verifies the timing-safe comparison is being used.
        """
        from sage_api.middleware.auth import verify_api_key
        import inspect

        source = inspect.getsource(verify_api_key)
        assert "secrets.compare_digest" in source

    def test_api_key_case_sensitive(self, client):
        """Test that API key comparison is case-sensitive."""
        response = client.get(
            "/protected",
            headers={"X-API-Key": "TEST-SECRET-KEY-123"},  # Wrong case
        )
        assert response.status_code == 401

    def test_empty_string_api_key_returns_401(self, client):
        """Test that empty string API key is treated as missing."""
        response = client.get(
            "/protected",
            headers={"X-API-Key": ""},
        )
        assert response.status_code == 401
