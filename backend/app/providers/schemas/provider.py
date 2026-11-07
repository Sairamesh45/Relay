"""Provider metadata schemas."""

from pydantic import BaseModel, Field


class ProviderInfo(BaseModel):
    """Metadata describing a supported AI provider."""

    id: str = Field(
        ..., description="Machine-readable provider identifier (e.g., 'gemini')"
    )
    name: str = Field(
        ..., description="Human-readable provider name (e.g., 'Google Gemini')"
    )
    description: str | None = Field(
        None, description="Brief description of the provider"
    )
    website_url: str | None = Field(None, description="Official provider website")
    docs_url: str | None = Field(
        None, description="Official developer documentation URL"
    )


class ProviderListResponse(BaseModel):
    """Response payload for listing all supported providers."""

    providers: list[ProviderInfo]
