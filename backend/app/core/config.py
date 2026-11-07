import json
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    APP_NAME: str = "Unified AI Gateway"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    DATABASE_URL: str = (
        "postgresql+asyncpg://gateway_user:gateway_password@localhost:5432/gateway_db"
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    LOG_LEVEL: str = "INFO"

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Supabase Infrastructure Configuration
    NEXT_PUBLIC_SUPABASE_URL: str | None = None
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: str | None = None
    SUPABASE_SECRET_KEY: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None

    # Provider & Credential Configuration
    CREDENTIAL_ENCRYPTION_KEY: str | None = None
    CREDENTIAL_ENCRYPTION_ACTIVE_VERSION: int = 1
    CREDENTIAL_ENCRYPTION_KEY_RING: dict[int, str] | None = None
    PROVIDER_REQUEST_TIMEOUT: float = 30.0
    ENABLE_DEV_AUTH: bool = False

    # Virtual API Key & Gateway Configuration
    VIRTUAL_KEY_HMAC_SECRET: str = (
        "uag_dev_hmac_secret_key_change_in_production_32b_min"
    )
    GATEWAY_RATE_LIMIT_RPM: int = 60

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_database_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed]
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        elif isinstance(v, list):
            return [str(item).strip() for item in v]
        return []

    @field_validator("CREDENTIAL_ENCRYPTION_KEY_RING", mode="before")
    @classmethod
    def assemble_key_ring(cls, v: object) -> dict[int, str] | None:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("{") and v_stripped.endswith("}"):
                try:
                    parsed = json.loads(v_stripped)
                    if isinstance(parsed, dict):
                        return {int(k): str(val).strip() for k, val in parsed.items()}
                except (json.JSONDecodeError, ValueError):
                    pass
        elif isinstance(v, dict):
            return {int(k): str(val).strip() for k, val in v.items()}
        return None


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()


settings = get_settings()
