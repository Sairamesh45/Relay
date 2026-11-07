"""Tests for central ProviderManager registry and resolution."""

import pytest

from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.groq import GroqProvider
from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.base import BaseProvider
from app.providers.exceptions import ProviderConfigurationError
from app.providers.manager import ProviderManager, get_provider_manager
from app.providers.schemas.model import UnifiedModel
from app.providers.schemas.provider import ProviderInfo


class MockCustomProvider(BaseProvider):
    """Custom provider used to verify dynamic extensibility."""

    @property
    def provider_id(self) -> str:
        return "mock_custom"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            id="mock_custom",
            name="Mock Custom Provider",
            description="Dynamically added provider",
        )

    async def validate_credentials(self, api_key: str) -> bool:
        return api_key == "valid-mock-key"

    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        return [
            UnifiedModel(
                id="mock-model-v1",
                provider="mock_custom",
                name="Mock Model 1",
            )
        ]


def test_default_providers_registered() -> None:
    """Verify that default providers (gemini, groq, openrouter) are pre-registered."""
    mgr = ProviderManager()
    assert mgr.is_supported("gemini")
    assert mgr.is_supported("groq")
    assert mgr.is_supported("openrouter")

    gemini = mgr.get_provider("gemini")
    assert isinstance(gemini, GeminiProvider)
    assert gemini.provider_id == "gemini"

    groq = mgr.get_provider("groq")
    assert isinstance(groq, GroqProvider)
    assert groq.provider_id == "groq"

    openrouter = mgr.get_provider("openrouter")
    assert isinstance(openrouter, OpenRouterProvider)
    assert openrouter.provider_id == "openrouter"


def test_provider_resolution_case_insensitive() -> None:
    """Verify that provider lookup is case-insensitive and trims whitespace."""
    mgr = ProviderManager()
    assert isinstance(mgr.get_provider("GEMINI"), GeminiProvider)
    assert isinstance(mgr.get_provider(" Groq "), GroqProvider)
    assert isinstance(mgr.get_provider("OpenRouter"), OpenRouterProvider)


def test_unsupported_provider_raises_configuration_error() -> None:
    """Verify that querying an unknown provider raises ProviderConfigurationError with available list."""
    mgr = ProviderManager()
    with pytest.raises(ProviderConfigurationError) as exc_info:
        mgr.get_provider("non_existent_provider")

    assert "Unsupported provider 'non_existent_provider'" in str(exc_info.value)
    assert "gemini" in str(exc_info.value)

    with pytest.raises(ProviderConfigurationError):
        mgr.get_provider("")


def test_dynamic_provider_registration_without_modifying_adapters() -> None:
    """Verify that new provider adapters can be registered at runtime without altering core code."""
    mgr = ProviderManager()
    custom_adapter = MockCustomProvider()

    assert not mgr.is_supported("mock_custom")
    mgr.register_provider(custom_adapter)
    assert mgr.is_supported("mock_custom")

    resolved = mgr.get_provider("mock_custom")
    assert resolved is custom_adapter
    assert resolved.provider_info.name == "Mock Custom Provider"


def test_list_supported_providers_returns_metadata() -> None:
    """Verify that list_supported_providers returns full metadata for catalog display."""
    mgr = ProviderManager()
    providers = mgr.list_supported_providers()

    provider_ids = [p.id for p in providers]
    assert "gemini" in provider_ids
    assert "groq" in provider_ids
    assert "openrouter" in provider_ids

    for p in providers:
        assert p.id
        assert p.name
        assert p.docs_url


def test_singleton_provider_manager() -> None:
    """Verify that get_provider_manager returns the global singleton."""
    mgr1 = get_provider_manager()
    mgr2 = get_provider_manager()
    assert mgr1 is mgr2
