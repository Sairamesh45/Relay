"""OpenAI-compatible error formatting and exception structures."""

from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field


class OpenAIErrorDetail(BaseModel):
    """OpenAI standard error payload body."""

    message: str
    type: str = Field(
        ..., description="Error type e.g. authentication_error, invalid_request_error"
    )
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    """Top-level OpenAI error envelope."""

    error: OpenAIErrorDetail


class OpenAIHTTPException(HTTPException):
    """Custom HTTPException that produces OpenAI-compliant error payloads."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        code: str | None = None,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        detail: dict[str, Any] = {
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
                "param": param,
            }
        }
        super().__init__(status_code=status_code, detail=detail, headers=headers)


def openai_auth_error(
    message: str = "Incorrect API key provided.",
    code: str = "invalid_api_key",
) -> OpenAIHTTPException:
    """Return 401 Authentication Error."""
    return OpenAIHTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        message=message,
        error_type="authentication_error",
        code=code,
        headers={"WWW-Authenticate": "Bearer"},
    )


def openai_invalid_request_error(
    message: str,
    code: str | None = None,
    param: str | None = None,
) -> OpenAIHTTPException:
    """Return 400 Invalid Request Error."""
    return OpenAIHTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=message,
        error_type="invalid_request_error",
        code=code,
        param=param,
    )


def openai_model_not_found_error(
    model_id: str,
) -> OpenAIHTTPException:
    """Return 404 Model Not Found Error."""
    return OpenAIHTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        message=f"The model '{model_id}' does not exist or you do not have access to it.",
        error_type="invalid_request_error",
        code="model_not_found",
    )


def openai_rate_limit_error(
    message: str = "Rate limit reached for requests.",
    retry_after: int = 60,
) -> OpenAIHTTPException:
    """Return 429 Rate Limit Error."""
    return OpenAIHTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        message=message,
        error_type="rate_limit_error",
        code="rate_limit_exceeded",
        headers={"Retry-After": str(retry_after)},
    )


def openai_provider_error(
    message: str,
    status_code: int = status.HTTP_502_BAD_GATEWAY,
    code: str = "provider_error",
) -> OpenAIHTTPException:
    """Return 502/504 Upstream Provider Error."""
    return OpenAIHTTPException(
        status_code=status_code,
        message=message,
        error_type="api_error",
        code=code,
    )


def openai_internal_error(
    message: str = "Internal gateway error",
    code: str = "internal_error",
) -> OpenAIHTTPException:
    """Return 500 Internal Error."""
    return OpenAIHTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message=message,
        error_type="api_error",
        code=code,
    )
