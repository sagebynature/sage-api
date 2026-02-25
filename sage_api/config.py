"""Settings and configuration for sage-api."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="SAGE_API_",
        env_file=".env",
        case_sensitive=False,
    )

    # Required fields
    api_key: str = Field(..., description="API key for authentication")

    # Optional fields with defaults
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    agents_dir: str = Field(
        default="./agents",
        description="Directory path for agent files",
    )
    session_ttl_seconds: int = Field(
        default=1800,
        description="Session time-to-live in seconds",
        ge=1,
    )
    request_timeout_seconds: int = Field(
        default=120,
        description="Request timeout in seconds",
        ge=1,
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    host: str = Field(
        default="0.0.0.0",
        description="Host address to bind to",
    )
    port: int = Field(
        default=8000,
        description="Port to bind to",
        ge=1,
        le=65535,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the cached settings instance for FastAPI dependency injection.

    Returns:
        Settings: The application settings singleton.

    Note:
        Call this function with Depends() in FastAPI routes to inject
        the settings instance. The lru_cache decorator ensures only one
        instance is created per process.
    """
    return Settings()  # type: ignore[call-arg]
