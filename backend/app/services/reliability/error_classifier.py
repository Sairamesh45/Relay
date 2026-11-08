"""Provider-independent 13-category error classification engine.

Normalizes provider errors across Google Gemini, Groq, OpenRouter, and standard
HTTP/network exceptions into canonical categories with strict zero-leakage redaction.
"""

from __future__ import annotations

import enum
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)


class ErrorCategory(enum.StrEnum):
    """Canonical 13 provider-independent error categories."""

    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    UNSUPPORTED_PARAMETER = "UNSUPPORTED_PARAMETER"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    CONTENT_REJECTED = "CONTENT_REJECTED"
    UNKNOWN = "UNKNOWN"


# Categories that are intrinsically retryable with bounded backoff and/or candidate failover
RETRYABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.RATE_LIMITED,
        ErrorCategory.PROVIDER_UNAVAILABLE,
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.NETWORK_ERROR,
        ErrorCategory.TIMEOUT,
    }
)

# Regex patterns for sanitizing secrets and keys from error messages and logs
_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),
    re.compile(r"x-goog-api-key:\s*[^\s,]+", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),
    re.compile(r"sk-or-v1-[0-9a-f]{40,}", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
]


def sanitize_error_text(text: str | None) -> str:
    """Sanitize error messages and log entries to guarantee zero secret leakage."""
    if not text:
        return ""
    sanitized = text
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


def sanitize_dict(data: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively scrub authorization headers, keys, and tokens from dictionaries."""
    if not data:
        return {}
    sensitive_keywords = (
        "authorization",
        "auth",
        "x-goog-api-key",
        "api-key",
        "api_key",
        "apikey",
        "token",
        "secret",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "password",
        "credential",
    )
    cleaned: dict[str, Any] = {}
    for k, v in data.items():
        k_lower = str(k).lower()
        if any(kw in k_lower for kw in sensitive_keywords):
            cleaned[k] = "[REDACTED]"
        elif isinstance(v, dict):
            cleaned[k] = sanitize_dict(v)
        elif isinstance(v, list):
            cleaned[k] = [
                sanitize_dict(item)
                if isinstance(item, dict)
                else sanitize_error_text(str(item))
                for item in v
            ]
        elif isinstance(v, str):
            cleaned[k] = sanitize_error_text(v)
        else:
            cleaned[k] = v
    return cleaned


@dataclass
class ClassifiedError:
    """Normalized provider-independent error classification result."""

    category: ErrorCategory
    retryable: bool
    provider: str
    status_code: int | None = None
    message: str = ""
    retry_after: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    raw_error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert classification result to sanitized dictionary."""
        return {
            "category": self.category.value,
            "retryable": self.retryable,
            "provider": self.provider,
            "status_code": self.status_code,
            "message": sanitize_error_text(self.message),
            "retry_after": self.retry_after,
            "details": sanitize_dict(self.details),
            "raw_error_type": self.raw_error_type,
        }


def _parse_retry_after(headers: dict[str, Any] | None) -> float | None:
    """Extract and parse Retry-After header as seconds float if present."""
    if not headers:
        return None
    for header_name in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
        val = headers.get(header_name)
        if val is not None:
            try:
                # Handle direct float/integer seconds
                return float(val)
            except (ValueError, TypeError):
                # Handle duration strings e.g. "2s", "500ms"
                val_str = str(val).strip().lower()
                if val_str.endswith("ms"):
                    try:
                        return float(val_str[:-2]) / 1000.0
                    except ValueError:
                        pass
                elif val_str.endswith("s"):
                    try:
                        return float(val_str[:-1])
                    except ValueError:
                        pass
    return None


def classify_provider_error(
    error: Exception | None = None,
    provider: str = "",
    status_code: int | None = None,
    response_headers: dict[str, Any] | None = None,
    response_body: dict[str, Any] | str | None = None,
) -> ClassifiedError:
    """Classify any provider response or exception into one of 13 canonical categories.

    Translates raw provider responses, status codes, and error bodies from Gemini, Groq,
    and OpenRouter, applying the zero-leakage rule to all message strings.
    """
    prov = (provider or "unknown").lower().strip()
    effective_status: int | None = None
    if isinstance(status_code, int):
        effective_status = status_code
    elif isinstance(status_code, str) and status_code.isdigit():
        effective_status = int(status_code)

    retry_after = _parse_retry_after(response_headers)
    raw_type = type(error).__name__ if error else None

    # Parse and normalize body
    parsed_body: dict[str, Any] = {}
    raw_body_text = ""
    if isinstance(response_body, dict):
        parsed_body = response_body
        raw_body_text = json.dumps(response_body)
    elif isinstance(response_body, str):
        raw_body_text = response_body
        try:
            parsed_body = json.loads(response_body)
        except (ValueError, TypeError):
            parsed_body = {"raw": response_body}

    # Extract status code from ProviderError subclasses if not explicitly passed
    if effective_status is None and isinstance(error, ProviderError):
        effective_status = error.status_code
        if isinstance(error, RateLimitError) and error.retry_after is not None:
            retry_after = retry_after or error.retry_after

    error_msg = str(error) if error else ""
    if not error_msg and "message" in parsed_body:
        error_msg = str(parsed_body.get("message", ""))
    elif not error_msg and "error" in parsed_body:
        err_obj = parsed_body["error"]
        if isinstance(err_obj, dict):
            error_msg = str(err_obj.get("message", ""))
        else:
            error_msg = str(err_obj)

    sanitized_msg = sanitize_error_text(error_msg or f"Provider error from {prov}")
    body_str_lower = (raw_body_text + " " + error_msg).lower()

    # -------------------------------------------------------------------------
    # 1. Network, Transport, and Timeout Exceptions
    # -------------------------------------------------------------------------
    if (
        isinstance(
            error,
            (
                httpx.TimeoutException,
                TimeoutError,
                ProviderTimeoutError,
            ),
        )
        or effective_status == 504
    ):
        return ClassifiedError(
            category=ErrorCategory.TIMEOUT,
            retryable=True,
            provider=prov,
            status_code=effective_status or 504,
            message=sanitized_msg or "Upstream provider connection or read timed out",
            retry_after=retry_after,
            details={"raw_error": raw_type},
            raw_error_type=raw_type,
        )

    if isinstance(
        error,
        (
            httpx.ConnectError,
            httpx.NetworkError,
            ConnectionResetError,
            ConnectionRefusedError,
        ),
    ):
        return ClassifiedError(
            category=ErrorCategory.NETWORK_ERROR,
            retryable=True,
            provider=prov,
            status_code=effective_status,
            message=sanitized_msg
            or "Network transport error contacting upstream provider",
            retry_after=retry_after,
            details={"raw_error": raw_type},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 2. Authentication & Authorization Failures
    # -------------------------------------------------------------------------
    # Check for invalid credentials (401, Google 400 API_KEY_INVALID, OpenRouter 401)
    is_auth_failure = (
        isinstance(error, InvalidCredentialsError)
        or effective_status == 401
        or "api_key_invalid" in body_str_lower
        or "api key not valid" in body_str_lower
        or "invalid api key" in body_str_lower
        or "invalid_api_key" in body_str_lower
        or "unauthorized" in body_str_lower
        and effective_status in (400, 401, 403)
    )
    if is_auth_failure:
        return ClassifiedError(
            category=ErrorCategory.AUTHENTICATION_FAILED,
            retryable=False,
            provider=prov,
            status_code=effective_status or 401,
            message=sanitized_msg
            or "Authentication failed: invalid or revoked provider credentials",
            retry_after=None,
            details={"reason": "invalid_credentials"},
            raw_error_type=raw_type,
        )

    # Check for permission denied (403, tier unauthorized, organization forbidden)
    if (
        effective_status == 403
        or "permission_denied" in body_str_lower
        or "forbidden" in body_str_lower
    ):
        return ClassifiedError(
            category=ErrorCategory.PERMISSION_DENIED,
            retryable=False,
            provider=prov,
            status_code=effective_status or 403,
            message=sanitized_msg
            or "Permission denied: access forbidden for requested resource or tier",
            retry_after=None,
            details={"reason": "permission_denied"},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 3. Quota Exhaustion & Rate Limits
    # -------------------------------------------------------------------------
    # OpenRouter HTTP 402 "Insufficient credits" or explicit permanent quota exhaustion
    is_transient_rate_limit = (
        effective_status == 429
        or isinstance(error, RateLimitError)
        or "rate limit" in body_str_lower
        or "rate_limit" in body_str_lower
        or "tpm" in body_str_lower
        or "rpm" in body_str_lower
    )
    is_quota_exhausted = (
        effective_status == 402
        or isinstance(error, QuotaExhaustedError)
        or "insufficient credits" in body_str_lower
        or "insufficient_quota" in body_str_lower
        or ("quota exceeded" in raw_body_text.lower() and not is_transient_rate_limit)
        or "exceeded your current quota" in body_str_lower
        or "credit balance" in body_str_lower
        or "credit balance is exhausted" in body_str_lower
    )
    if is_quota_exhausted and not is_transient_rate_limit:
        return ClassifiedError(
            category=ErrorCategory.QUOTA_EXHAUSTED,
            retryable=False,
            provider=prov,
            status_code=effective_status or 402,
            message=sanitized_msg
            or "Upstream provider quota or credit balance exhausted (HTTP 402 Payment Required)",
            retry_after=retry_after,
            details={"reason": "quota_exhausted"},
            raw_error_type=raw_type,
        )

    if (
        effective_status == 429
        or isinstance(error, RateLimitError)
        or "resource_exhausted" in body_str_lower
    ):
        # Check if rate limit mentions tokens or requests (transient rate limiting)
        return ClassifiedError(
            category=ErrorCategory.RATE_LIMITED,
            retryable=True,
            provider=prov,
            status_code=429,
            message=sanitized_msg
            or "Provider rate limit exceeded (RPM/TPM limit reached)",
            retry_after=retry_after,
            details={"retry_after": retry_after},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 4. Model Unavailability & Configuration
    # -------------------------------------------------------------------------
    is_model_unavailable = (
        effective_status == 404
        or "model_not_found" in body_str_lower
        or "does not exist" in body_str_lower
        or "is not found" in body_str_lower
        or "model unavailable" in body_str_lower
        or "decommissioned" in body_str_lower
    )
    if is_model_unavailable:
        return ClassifiedError(
            category=ErrorCategory.MODEL_UNAVAILABLE,
            retryable=False,
            provider=prov,
            status_code=effective_status or 404,
            message=sanitized_msg
            or "Requested model is unavailable or not found for this provider",
            retry_after=None,
            details={"reason": "model_not_found"},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 5. Content Rejection & Moderation
    # -------------------------------------------------------------------------
    is_content_rejected = (
        "content_filter" in body_str_lower
        or "moderation" in body_str_lower
        or "safety" in body_str_lower
        or "blocklist" in body_str_lower
        or "prohibited_content" in body_str_lower
        or "harm_category" in body_str_lower
    )
    if is_content_rejected and effective_status in (400, 422, None):
        return ClassifiedError(
            category=ErrorCategory.CONTENT_REJECTED,
            retryable=False,
            provider=prov,
            status_code=effective_status or 400,
            message=sanitized_msg
            or "Request rejected by upstream safety or content moderation policies",
            retry_after=None,
            details={"reason": "content_filter"},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 6. Context Window Exceeded
    # -------------------------------------------------------------------------
    is_context_exceeded = (
        "context_length_exceeded" in body_str_lower
        or "maximum context length" in body_str_lower
        or "too many tokens" in body_str_lower
        or "input token limit" in body_str_lower
        or "token limit exceeded" in body_str_lower
    )
    if is_context_exceeded:
        return ClassifiedError(
            category=ErrorCategory.CONTEXT_LENGTH_EXCEEDED,
            retryable=False,
            provider=prov,
            status_code=effective_status or 400,
            message=sanitized_msg
            or "Prompt tokens exceeded the model's maximum context length",
            retry_after=None,
            details={"reason": "context_overflow"},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 7. Unsupported Parameter or Malformed Client Request
    # -------------------------------------------------------------------------
    is_unsupported_param = (
        "unsupported parameter" in body_str_lower
        or "unknown field" in body_str_lower
        or "extra inputs are not permitted" in body_str_lower
        or "unsupported_parameter" in body_str_lower
        or "invalid parameter" in body_str_lower
    )
    if is_unsupported_param or (
        effective_status == 400
        and not is_auth_failure
        and not is_context_exceeded
        and not is_content_rejected
    ):
        category = (
            ErrorCategory.UNSUPPORTED_PARAMETER
            if is_unsupported_param
            else ErrorCategory.UNSUPPORTED_PARAMETER
        )
        return ClassifiedError(
            category=category,
            retryable=False,
            provider=prov,
            status_code=400,
            message=sanitized_msg
            or "Provider rejected request due to unsupported parameter or invalid schema",
            retry_after=None,
            details={"reason": "invalid_parameter"},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 8. Provider Server Errors & Temporary Outages
    # -------------------------------------------------------------------------
    if effective_status in (502, 503) or isinstance(error, ProviderUnavailableError):
        return ClassifiedError(
            category=ErrorCategory.PROVIDER_UNAVAILABLE,
            retryable=True,
            provider=prov,
            status_code=effective_status or 503,
            message=sanitized_msg
            or "Upstream provider is temporarily unavailable or overloaded",
            retry_after=retry_after,
            details={"status": effective_status},
            raw_error_type=raw_type,
        )

    if effective_status is not None and effective_status >= 500:
        return ClassifiedError(
            category=ErrorCategory.SERVER_ERROR,
            retryable=True,
            provider=prov,
            status_code=effective_status,
            message=sanitized_msg
            or f"Upstream provider returned internal server error {effective_status}",
            retry_after=retry_after,
            details={"status": effective_status},
            raw_error_type=raw_type,
        )

    # -------------------------------------------------------------------------
    # 9. Fallback: Unknown
    # -------------------------------------------------------------------------
    is_retryable = effective_status is not None and effective_status >= 500
    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        retryable=is_retryable,
        provider=prov,
        status_code=effective_status,
        message=sanitized_msg or "Unclassified provider error",
        retry_after=retry_after,
        details={"raw_error": raw_type},
        raw_error_type=raw_type,
    )
