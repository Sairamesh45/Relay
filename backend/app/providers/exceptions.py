"""Normalized exception hierarchy for AI provider operations."""


class ProviderError(Exception):
    """Base exception for all AI provider integration errors."""

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after

    def __str__(self) -> str:
        parts = [self.message]
        if self.provider:
            parts.append(f"[provider={self.provider}]")
        if self.status_code:
            parts.append(f"[status={self.status_code}]")
        if self.retry_after:
            parts.append(f"[retry_after={self.retry_after}s]")
        return " ".join(parts)


class InvalidCredentialsError(ProviderError):
    """Raised when authentication fails or provider rejects credentials (HTTP 401/403)."""

    pass


class RateLimitError(ProviderError):
    """Raised when requests exceed provider rate limits or quotas (HTTP 429)."""

    pass


class ProviderUnavailableError(ProviderError):
    """Raised when provider service is down, overloaded, or unreachable (HTTP 5xx/Connection errors)."""

    pass


class ProviderTimeoutError(ProviderError):
    """Raised when an HTTP request to a provider times out."""

    pass


class ProviderRequestError(ProviderError):
    """Raised when a request is rejected due to bad arguments (HTTP 400) or malformed responses."""

    pass


class ProviderConfigurationError(ProviderError):
    """Raised when an unsupported provider is requested or adapter configuration is invalid."""

    pass
