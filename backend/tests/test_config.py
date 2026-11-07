import pytest

from app.core.config import Settings, get_settings


def test_default_settings_load_correctly() -> None:
    """Verify that default settings load with expected values when no overrides are given."""
    settings = Settings(_env_file=None)
    assert settings.APP_NAME == "Unified AI Gateway"
    assert settings.APP_ENV == "development"
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.LOG_LEVEL == "INFO"
    assert "gateway_db" in settings.DATABASE_URL
    assert "6379" in settings.REDIS_URL


def test_environment_variables_override_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that environment variables take precedence over default settings."""
    monkeypatch.setenv("APP_NAME", "Custom AI Gateway")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("API_V1_PREFIX", "/api/v2")

    custom_settings = Settings(_env_file=None)
    assert custom_settings.APP_NAME == "Custom AI Gateway"
    assert custom_settings.APP_ENV == "staging"
    assert custom_settings.LOG_LEVEL == "WARNING"
    assert custom_settings.API_V1_PREFIX == "/api/v2"


def test_boolean_configuration_parsed_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that string representations of booleans ('false', '0', 'true', '1') are parsed accurately."""
    monkeypatch.setenv("DEBUG", "false")
    settings_false = Settings(_env_file=None)
    assert settings_false.DEBUG is False

    monkeypatch.setenv("DEBUG", "1")
    settings_true = Settings(_env_file=None)
    assert settings_true.DEBUG is True

    monkeypatch.setenv("DEBUG", "true")
    settings_true_str = Settings(_env_file=None)
    assert settings_true_str.DEBUG is True


def test_application_configuration_accessible_through_settings_object() -> None:
    """Verify that configuration settings are accessible through the global get_settings() instance."""
    app_settings = get_settings()
    assert hasattr(app_settings, "DATABASE_URL")
    assert hasattr(app_settings, "REDIS_URL")
    assert hasattr(app_settings, "CORS_ORIGINS")
    assert isinstance(app_settings.CORS_ORIGINS, list)
    assert len(app_settings.CORS_ORIGINS) > 0
