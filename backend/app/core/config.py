import json
from functools import lru_cache

from pydantic import field_validator, model_validator
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
    RATE_LIMIT_REDIS_REQUIRED: bool = False
    RATE_LIMIT_REDIS_KEY_PREFIX: str = "relay:rate-limit"

    # Database Connection Pool Configuration
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 40
    DB_POOL_TIMEOUT: float = 10.0
    DB_POOL_RECYCLE: int = 300

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
    SUPABASE_JWT_SECRET: str | None = None

    # Google OAuth & Relay Native JWT Configuration
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    JWT_SECRET_KEY: str = "relay_dev_jwt_secret_key_change_in_production_32b_min"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_DOMAIN: str | None = None

    # Provider & Credential Configuration
    CREDENTIAL_ENCRYPTION_KEY: str | None = None
    CREDENTIAL_ENCRYPTION_ACTIVE_VERSION: int = 1
    CREDENTIAL_ENCRYPTION_KEY_RING: dict[int, str] | None = None
    PROVIDER_REQUEST_TIMEOUT: float = 30.0
    PROVIDER_CONNECT_TIMEOUT: float = 5.0
    PROVIDER_MAX_CONNECTIONS: int = 200
    PROVIDER_MAX_KEEPALIVE_CONNECTIONS: int = 50
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

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        """Reject development defaults when the application is run in production."""
        if self.APP_ENV.lower() != "production":
            return self

        insecure_defaults = (
            "relay_dev_jwt_secret_key_change_in_production_32b_min",
            "uag_dev_hmac_secret_key_change_in_production_32b_min",
        )
        if self.JWT_SECRET_KEY in insecure_defaults:
            raise ValueError("JWT_SECRET_KEY must be replaced in production.")
        if self.VIRTUAL_KEY_HMAC_SECRET in insecure_defaults:
            raise ValueError(
                "VIRTUAL_KEY_HMAC_SECRET must be replaced in production."
            )
        if not self.CREDENTIAL_ENCRYPTION_KEY:
            raise ValueError(
                "CREDENTIAL_ENCRYPTION_KEY is required in production."
            )
        if not self.AUTH_COOKIE_SECURE:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production.")
        if self.ENABLE_DEV_AUTH:
            raise ValueError("ENABLE_DEV_AUTH must be false in production.")
        if "localhost" in self.REDIS_URL or "127.0.0.1" in self.REDIS_URL:
            raise ValueError("REDIS_URL must point to a production Redis service.")
        if any(
            "localhost" in origin or "127.0.0.1" in origin
            for origin in self.CORS_ORIGINS
        ):
            raise ValueError(
                "CORS_ORIGINS must not contain localhost in production."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of application settings."""
    return Settings()


settings = get_settings()
