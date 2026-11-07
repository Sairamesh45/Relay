from app.core.config import Settings, get_settings


def test_settings_defaults() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.PROJECT_NAME == "Unified AI Gateway"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.PORT == 8000
