"""Comprehensive tests for provider-independent 13-category error classification engine."""

import httpx
import pytest

from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.services.reliability.error_classifier import (
    RETRYABLE_CATEGORIES,
    ClassifiedError,
    ErrorCategory,
    classify_provider_error,
    sanitize_dict,
    sanitize_error_text,
)


def test_sanitize_error_text_removes_api_keys() -> None:
    """Verify zero-leakage rule scrubs API keys and bearer tokens from error messages."""
    raw_google = "Error calling Gemini with key AIzaSyD1234567890abcdefghijklmnopqrstuv"
    raw_groq = "Invalid Authorization: Bearer gsk_1234567890abcdef1234567890abcdef12"
    raw_openrouter = "Failed with key sk-or-v1-abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
    raw_openai_style = "Authorization failed for sk-1234567890abcdef1234567890"

    assert "AIzaSy" not in sanitize_error_text(raw_google)
    assert "gsk_" not in sanitize_error_text(raw_groq)
    assert "sk-or-v1" not in sanitize_error_text(raw_openrouter)
    assert "sk-" not in sanitize_error_text(raw_openai_style)
    assert "[REDACTED_SECRET]" in sanitize_error_text(raw_google)
    assert "[REDACTED_SECRET]" in sanitize_error_text(raw_groq)


def test_sanitize_dict_removes_sensitive_headers() -> None:
    """Verify headers dictionary scrubs authorization and api key fields."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer super-secret-token",
        "x-goog-api-key": "AIzaSyD1234567890abcdefghijklmnopqrstuv",
        "nested": {
            "api_key": "secret-nested-key",
            "safe_field": "safe_value",
        },
    }
    cleaned = sanitize_dict(headers)
    assert cleaned["Content-Type"] == "application/json"
    assert cleaned["Authorization"] == "[REDACTED]"
    assert cleaned["x-goog-api-key"] == "[REDACTED]"
    assert cleaned["nested"]["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["safe_field"] == "safe_value"


@pytest.mark.parametrize(
    "status,body,expected_cat,expected_retryable",
    [
        (
            429,
            {"error": {"message": "Rate limit exceeded"}},
            ErrorCategory.RATE_LIMITED,
            True,
        ),
        (
            503,
            {"error": {"message": "Service unavailable"}},
            ErrorCategory.PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            502,
            {"error": {"message": "Bad gateway"}},
            ErrorCategory.PROVIDER_UNAVAILABLE,
            True,
        ),
        (
            500,
            {"error": {"message": "Internal server error"}},
            ErrorCategory.SERVER_ERROR,
            True,
        ),
        (504, {"error": {"message": "Gateway timeout"}}, ErrorCategory.TIMEOUT, True),
        (
            401,
            {"error": {"message": "Invalid API Key"}},
            ErrorCategory.AUTHENTICATION_FAILED,
            False,
        ),
        (
            403,
            {"error": {"message": "Permission denied for tier"}},
            ErrorCategory.PERMISSION_DENIED,
            False,
        ),
        (
            404,
            {"error": {"message": "model_not_found"}},
            ErrorCategory.MODEL_UNAVAILABLE,
            False,
        ),
        (
            400,
            {"error": {"message": "unsupported parameter 'temperature_top_k'"}},
            ErrorCategory.UNSUPPORTED_PARAMETER,
            False,
        ),
        (
            400,
            {"error": {"message": "maximum context length is 8192 tokens"}},
            ErrorCategory.CONTEXT_LENGTH_EXCEEDED,
            False,
        ),
        (
            402,
            {"error": {"message": "Insufficient credits"}},
            ErrorCategory.QUOTA_EXHAUSTED,
            False,
        ),
        (
            400,
            {"error": {"message": "safety violation: harm category detected"}},
            ErrorCategory.CONTENT_REJECTED,
            False,
        ),
    ],
)
def test_all_13_categories_classification(
    status: int,
    body: dict,
    expected_cat: ErrorCategory,
    expected_retryable: bool,
) -> None:
    """Verify each canonical category is correctly resolved and retryability matches specifications."""
    classified = classify_provider_error(
        provider="test-provider",
        status_code=status,
        response_body=body,
    )
    assert classified.category == expected_cat
    assert classified.retryable == expected_retryable
    if expected_retryable:
        assert classified.category in RETRYABLE_CATEGORIES
    else:
        assert classified.category not in RETRYABLE_CATEGORIES


def test_classify_groq_rate_limit_with_reset_header() -> None:
    """Verify Groq 429 response parses x-ratelimit-reset-requests duration string."""
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "0",
        "x-ratelimit-reset-requests": "6s",
    }
    body = {
        "error": {"message": "Rate limit reached for model llama-3.3-70b-versatile"}
    }

    classified = classify_provider_error(
        provider="groq",
        status_code=429,
        response_headers=headers,
        response_body=body,
    )

    assert classified.category == ErrorCategory.RATE_LIMITED
    assert classified.retryable is True
    assert classified.retry_after == 6.0
    assert classified.provider == "groq"


def test_classify_gemini_bad_key_encoded_as_400() -> None:
    """Verify Gemini's custom HTTP 400 API_KEY_INVALID is classified as AUTHENTICATION_FAILED."""
    body = {
        "error": {
            "code": 400,
            "message": "API_KEY_INVALID: API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
        }
    }
    classified = classify_provider_error(
        provider="gemini",
        status_code=400,
        response_body=body,
    )

    assert classified.category == ErrorCategory.AUTHENTICATION_FAILED
    assert classified.retryable is False
    assert classified.status_code == 400
    assert "API_KEY_INVALID" in classified.message


def test_classify_gemini_safety_block_as_content_rejected() -> None:
    """Verify Gemini safety/content filter blocks are classified as CONTENT_REJECTED."""
    body = {
        "error": {
            "code": 400,
            "message": "Candidate generation blocked due to SAFETY policy violation.",
            "status": "FAILED_PRECONDITION",
        }
    }
    classified = classify_provider_error(
        provider="gemini",
        status_code=400,
        response_body=body,
    )

    assert classified.category == ErrorCategory.CONTENT_REJECTED
    assert classified.retryable is False


def test_classify_openrouter_402_insufficient_credits() -> None:
    """Verify OpenRouter 402 Insufficient credits maps to QUOTA_EXHAUSTED."""
    body = {
        "error": {
            "code": 402,
            "message": "Insufficient credits to complete this generation request.",
        }
    }
    classified = classify_provider_error(
        provider="openrouter",
        status_code=402,
        response_body=body,
    )

    assert classified.category == ErrorCategory.QUOTA_EXHAUSTED
    assert classified.retryable is False


def test_classify_httpx_timeout_and_network_exceptions() -> None:
    """Verify raw httpx transport exceptions map correctly to TIMEOUT and NETWORK_ERROR."""
    timeout_exc = httpx.ReadTimeout("Read timed out on socket")
    classified_timeout = classify_provider_error(error=timeout_exc, provider="groq")
    assert classified_timeout.category == ErrorCategory.TIMEOUT
    assert classified_timeout.retryable is True
    assert classified_timeout.status_code == 504

    connect_exc = httpx.ConnectError(
        "Failed to establish new connection: [Errno 111] Connection refused"
    )
    classified_net = classify_provider_error(error=connect_exc, provider="gemini")
    assert classified_net.category == ErrorCategory.NETWORK_ERROR
    assert classified_net.retryable is True


def test_classify_provider_error_subclasses() -> None:
    """Verify existing app.providers.exceptions map cleanly to canonical categories."""
    rl_err = RateLimitError(
        "RPM exceeded", provider="groq", status_code=429, retry_after=12.5
    )
    classified_rl = classify_provider_error(error=rl_err, provider="groq")
    assert classified_rl.category == ErrorCategory.RATE_LIMITED
    assert classified_rl.retry_after == 12.5
    assert classified_rl.retryable is True

    auth_err = InvalidCredentialsError(
        "Bad key", provider="openrouter", status_code=401
    )
    classified_auth = classify_provider_error(error=auth_err, provider="openrouter")
    assert classified_auth.category == ErrorCategory.AUTHENTICATION_FAILED
    assert classified_auth.retryable is False

    unavail_err = ProviderUnavailableError(
        "Down for maintenance", provider="gemini", status_code=503
    )
    classified_unavail = classify_provider_error(error=unavail_err, provider="gemini")
    assert classified_unavail.category == ErrorCategory.PROVIDER_UNAVAILABLE
    assert classified_unavail.retryable is True

    to_err = ProviderTimeoutError("Gateway timeout", provider="groq", status_code=504)
    classified_to = classify_provider_error(error=to_err, provider="groq")
    assert classified_to.category == ErrorCategory.TIMEOUT
    assert classified_to.retryable is True


def test_classified_error_to_dict_redacts_secrets() -> None:
    """Verify to_dict() guarantees complete redaction on exported payload."""
    raw_msg = "Error using key Bearer gsk_secret_1234567890abcdef1234567890"
    classified = ClassifiedError(
        category=ErrorCategory.AUTHENTICATION_FAILED,
        retryable=False,
        provider="groq",
        status_code=401,
        message=raw_msg,
        details={"auth_header": "Bearer secret-xyz", "model": "llama-3.3-70b"},
    )
    dumped = classified.to_dict()
    assert "gsk_secret" not in dumped["message"]
    assert "[REDACTED_SECRET]" in dumped["message"]
    assert dumped["details"]["auth_header"] == "[REDACTED]"
    assert dumped["details"]["model"] == "llama-3.3-70b"
