"""Tests for sage_api.config module."""

import os
import pytest
from pydantic import ValidationError
from sage_api.config import Settings, get_settings


@pytest.fixture
def clear_settings_cache():
    """Clear the lru_cache for get_settings before and after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestSettingsDefaults:
    """Test that defaults are applied when environment variables are absent."""

    def test_defaults_applied(self, monkeypatch, clear_settings_cache):
        """Test that all default values are applied correctly."""
        # Set only the required API_KEY
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        # Clear any other SAGE_API_* env vars to ensure defaults
        for key in list(os.environ.keys()):
            if key.startswith("SAGE_API_") and key != "SAGE_API_API_KEY":
                monkeypatch.delenv(key, raising=False)

        settings = get_settings()

        assert settings.redis_url == "redis://localhost:6379/0"
        assert settings.api_key == "test-key"
        assert settings.agents_dir == "./agents"
        assert settings.session_ttl_seconds == 1800
        assert settings.request_timeout_seconds == 120
        assert settings.log_level == "INFO"
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000


class TestSettingsEnvVarOverride:
    """Test that environment variables override defaults."""

    def test_env_var_override(self, monkeypatch, clear_settings_cache):
        """Test that environment variables override default values."""
        monkeypatch.setenv("SAGE_API_API_KEY", "custom-key")
        monkeypatch.setenv("SAGE_API_REDIS_URL", "redis://custom:6379/1")
        monkeypatch.setenv("SAGE_API_SESSION_TTL_SECONDS", "3600")
        monkeypatch.setenv("SAGE_API_PORT", "9000")

        settings = get_settings()

        assert settings.api_key == "custom-key"
        assert settings.redis_url == "redis://custom:6379/1"
        assert settings.session_ttl_seconds == 3600
        assert settings.port == 9000
        # Defaults should still apply to non-overridden fields
        assert settings.log_level == "INFO"
        assert settings.host == "0.0.0.0"


class TestSettingsRequiredFields:
    """Test that required fields raise ValidationError when missing."""

    def test_api_key_required(self, monkeypatch, clear_settings_cache):
        """Test that SAGE_API_API_KEY is required and raises ValidationError when missing."""
        monkeypatch.delenv("SAGE_API_API_KEY", raising=False)

        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)

        errors = exc_info.value.errors()
        assert any(error["loc"] == ("api_key",) for error in errors)


class TestRedisUrlParsing:
    """Test that redis_url is parsed and validated correctly."""

    def test_redis_url_valid(self, monkeypatch, clear_settings_cache):
        """Test that a valid redis URL is accepted."""
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.setenv("SAGE_API_REDIS_URL", "redis://localhost:6379/2")

        settings = get_settings()

        assert settings.redis_url == "redis://localhost:6379/2"

    def test_redis_url_default(self, monkeypatch, clear_settings_cache):
        """Test that redis_url uses default when not set."""
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.delenv("SAGE_API_REDIS_URL", raising=False)

        settings = get_settings()

        assert settings.redis_url == "redis://localhost:6379/0"


class TestGetSettingsSingleton:
    """Test that get_settings returns a cached singleton instance."""

    def test_get_settings_caching(self, monkeypatch, clear_settings_cache):
        """Test that get_settings() returns the same instance on multiple calls."""
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")

        settings1 = get_settings()
        settings2 = get_settings()

        # Should be the same object (cached)
        assert settings1 is settings2


class TestNewConfigFields:
    def test_cors_origins_default_empty(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.delenv("SAGE_API_CORS_ORIGINS", raising=False)

        settings = get_settings()

        assert settings.cors_origins == []

    def test_cors_origins_from_env(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.setenv("SAGE_API_CORS_ORIGINS", '["http://localhost:3000","http://example.com"]')

        settings = get_settings()

        assert settings.cors_origins == ["http://localhost:3000", "http://example.com"]

    def test_rate_limit_rpm_default_zero(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.delenv("SAGE_API_RATE_LIMIT_RPM", raising=False)

        settings = get_settings()

        assert settings.rate_limit_rpm == 0

    def test_max_body_bytes_default_zero(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.delenv("SAGE_API_MAX_BODY_BYTES", raising=False)

        settings = get_settings()

        assert settings.max_body_bytes == 0

    def test_max_concurrent_streams_default_zero(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.delenv("SAGE_API_MAX_CONCURRENT_STREAMS", raising=False)

        settings = get_settings()

        assert settings.max_concurrent_streams == 0

    def test_rate_limit_fields_from_env(self, monkeypatch, clear_settings_cache):
        monkeypatch.setenv("SAGE_API_API_KEY", "test-key")
        monkeypatch.setenv("SAGE_API_RATE_LIMIT_RPM", "120")
        monkeypatch.setenv("SAGE_API_MAX_BODY_BYTES", "1048576")
        monkeypatch.setenv("SAGE_API_MAX_CONCURRENT_STREAMS", "7")

        settings = get_settings()

        assert settings.rate_limit_rpm == 120
        assert settings.max_body_bytes == 1048576
        assert settings.max_concurrent_streams == 7
