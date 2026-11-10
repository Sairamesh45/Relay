"""Central registry and resolution manager for AI provider adapters."""

import httpx

from app.core.config import get_settings
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.groq import GroqProvider
from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.base import BaseProvider
from app.providers.exceptions import ProviderConfigurationError
from app.providers.schemas.provider import ProviderInfo

PROVIDER_ALIASES: dict[str, str] = {
    "google": "gemini",
    "google-gemini": "gemini",
    "google_gemini": "gemini",
}


class ProviderManager:
    """Central registry and coordinator for AI provider adapters.

    Enables dynamic registration and resolution of provider adapters without modifying
    calling code or API endpoints.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._http_client = http_client or self._build_http_client()
        self._register_default_adapters()

    @staticmethod
    def _build_http_client() -> httpx.AsyncClient:
        settings = get_settings()
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.PROVIDER_REQUEST_TIMEOUT,
                connect=settings.PROVIDER_CONNECT_TIMEOUT,
            ),
            limits=httpx.Limits(
                max_connections=settings.PROVIDER_MAX_CONNECTIONS,
                max_keepalive_connections=settings.PROVIDER_MAX_KEEPALIVE_CONNECTIONS,
            ),
            http2=True,
        )

    def _register_default_adapters(self) -> None:
        """Register the built-in initial Phase 2 provider adapters."""
        self.register_provider(GeminiProvider(http_client=self._http_client))
        self.register_provider(GroqProvider(http_client=self._http_client))
        self.register_provider(OpenRouterProvider(http_client=self._http_client))

    async def close(self) -> None:
        """Close the shared upstream transport during application shutdown."""
        await self._http_client.aclose()

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

        clean_id = provider_id.strip().lower()
        provider_key = PROVIDER_ALIASES.get(clean_id, clean_id)
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
        clean_id = provider_id.strip().lower()
        provider_key = PROVIDER_ALIASES.get(clean_id, clean_id)
        return provider_key in self._providers

    def list_supported_providers(self) -> list[ProviderInfo]:
        """Return metadata for all currently registered providers."""
        return [adapter.provider_info for adapter in self._providers.values()]


# Central singleton instance
provider_manager = ProviderManager()


def get_provider_manager() -> ProviderManager:
    """FastAPI dependency for accessing the central provider manager."""
    return provider_manager
