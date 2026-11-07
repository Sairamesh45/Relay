"""Central registry and resolution manager for AI provider adapters."""

from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.groq import GroqProvider
from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.base import BaseProvider
from app.providers.exceptions import ProviderConfigurationError
from app.providers.schemas.provider import ProviderInfo


class ProviderManager:
    """Central registry and coordinator for AI provider adapters.

    Enables dynamic registration and resolution of provider adapters without modifying
    calling code or API endpoints.
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._register_default_adapters()

    def _register_default_adapters(self) -> None:
        """Register the built-in initial Phase 2 provider adapters."""
        self.register_provider(GeminiProvider())
        self.register_provider(GroqProvider())
        self.register_provider(OpenRouterProvider())

    def register_provider(self, provider: BaseProvider) -> None:
        """Register an adapter instance into the provider registry."""
        provider_key = provider.provider_id.strip().lower()
        self._providers[provider_key] = provider

    def get_provider(self, provider_id: str) -> BaseProvider:
        """Resolve a registered provider adapter by identifier.

        Raises ProviderConfigurationError if the provider is unsupported or unregistered.
        """
        if not provider_id:
            raise ProviderConfigurationError("Provider identifier cannot be empty.")

        provider_key = provider_id.strip().lower()
        if provider_key not in self._providers:
            available = sorted(self._providers.keys())
            raise ProviderConfigurationError(
                f"Unsupported provider '{provider_id}'. Supported providers are: {available}",
                provider=provider_id,
            )

        return self._providers[provider_key]

    def is_supported(self, provider_id: str) -> bool:
        """Check whether a given provider identifier is currently registered."""
        if not provider_id:
            return False
        return provider_id.strip().lower() in self._providers

    def list_supported_providers(self) -> list[ProviderInfo]:
        """Return metadata for all currently registered providers."""
        return [adapter.provider_info for adapter in self._providers.values()]


# Central singleton instance
provider_manager = ProviderManager()


def get_provider_manager() -> ProviderManager:
    """FastAPI dependency for accessing the central provider manager."""
    return provider_manager
