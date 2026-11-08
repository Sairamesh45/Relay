"""Retry Policy, Attempt Tracing, and Retry Budget Enforcer.

Enforces bounded retry attempts, total request timeouts, non-retryable error rules,
attempt-level execution tracing, and sliding-window retry budget protection against
thundering herds.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.reliability.error_classifier import (
    RETRYABLE_CATEGORIES,
    ErrorCategory,
)

# Canonical non-retryable categories as defined in master requirements
NON_RETRYABLE_CATEGORIES: frozenset[ErrorCategory] = frozenset(
    {
        ErrorCategory.AUTHENTICATION_FAILED,
        ErrorCategory.PERMISSION_DENIED,
        ErrorCategory.UNSUPPORTED_PARAMETER,
        ErrorCategory.CONTENT_REJECTED,
        ErrorCategory.QUOTA_EXHAUSTED,
        ErrorCategory.CONTEXT_LENGTH_EXCEEDED,
    }
)


@dataclass
class RetryPolicy:
    """Configurable retry and failover policy."""

    max_attempts: int = 3
    max_failover_candidates: int = 3
    retryable_categories: frozenset[ErrorCategory] = RETRYABLE_CATEGORIES
    per_attempt_timeout: float = 15.0
    total_timeout: float = 60.0
    backoff_base_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 10.0
    jitter: bool = True
    retry_budget_ratio: float = 0.20

    def is_retryable(self, error_category: ErrorCategory | str | None) -> bool:
        """Evaluate if an error category is safe and permitted for retry/failover.

        Strictly rejects:
        - AUTHENTICATION_FAILED
        - PERMISSION_DENIED
        - UNSUPPORTED_PARAMETER
        - CONTENT_REJECTED
        - QUOTA_EXHAUSTED
        - CONTEXT_LENGTH_EXCEEDED
        """
        if error_category is None:
            return False

        if isinstance(error_category, ErrorCategory):
            cat = error_category
        elif isinstance(error_category, str):
            try:
                cat = ErrorCategory(error_category.upper())
            except ValueError:
                return False
        else:
            cat = error_category

        if cat in NON_RETRYABLE_CATEGORIES:
            return False

        return cat in self.retryable_categories

    def calculate_backoff(self, attempt_number: int) -> float:
        """Calculate exponential backoff with full jitter for attempt number >= 1."""
        exp = max(0, attempt_number - 1)
        base = min(
            self.backoff_base_seconds * (self.backoff_multiplier**exp),
            self.max_backoff_seconds,
        )

        if self.jitter:
            delay = random.uniform(0.5 * base, 1.5 * base)
        else:
            delay = base

        return min(delay, self.max_backoff_seconds)


@dataclass
class AttemptRecord:
    """Individual candidate dispatch execution record within a request trace."""

    attempt_number: int
    candidate_id: str
    provider: str
    model_id: str
    credential_id: uuid.UUID | str | None = None
    failover_level: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    latency_ms: float = 0.0
    status: str = "pending"  # "success", "failed", "skipped", "timeout"
    status_code: int | None = None
    error_category: str | None = None
    error_message: str | None = None

    def finish(
        self,
        status: str,
        latency_ms: float,
        status_code: int | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark attempt as complete with performance metrics."""
        self.end_time = datetime.now(UTC)
        self.status = status
        self.latency_ms = round(latency_ms, 2)
        self.status_code = status_code
        self.error_category = error_category
        self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        """Serialize attempt record."""
        return {
            "attempt": self.attempt_number,
            "candidate_id": self.candidate_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "credential_id": str(self.credential_id) if self.credential_id else None,
            "failover_level": self.failover_level,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "status_code": self.status_code,
            "error_category": self.error_category,
            "error_message": self.error_message,
        }


@dataclass
class ExecutionTrace:
    """End-to-end multi-attempt execution trace for an incoming request."""

    request_id: str
    attempts: list[AttemptRecord] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    total_attempts: int = 0
    total_latency_ms: float = 0.0
    final_status: str = "pending"
    selected_candidate_id: str | None = None
    failover_level: int = 0

    def record_attempt(self, record: AttemptRecord) -> None:
        """Add completed or in-progress attempt to the execution trace."""
        self.attempts.append(record)
        self.total_attempts = len(self.attempts)

    def finish(
        self,
        final_status: str,
        selected_candidate_id: str | None = None,
        failover_level: int = 0,
    ) -> None:
        """Conclude the execution trace."""
        self.end_time = datetime.now(UTC)
        self.final_status = final_status
        self.selected_candidate_id = selected_candidate_id
        self.failover_level = failover_level
        self.total_latency_ms = round(sum(a.latency_ms for a in self.attempts), 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize complete trace to dictionary."""
        return {
            "request_id": self.request_id,
            "total_attempts": self.total_attempts,
            "total_latency_ms": self.total_latency_ms,
            "final_status": self.final_status,
            "selected_candidate_id": self.selected_candidate_id,
            "failover_level": self.failover_level,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "attempts": [a.to_dict() for a in self.attempts],
        }


class RetryBudgetEnforcer:
    """Sliding-window retry budget enforcer preventing gateway retry storms."""

    def __init__(
        self,
        window_seconds: float = 600.0,
        budget_ratio: float = 0.20,
        min_requests_threshold: int = 10,
    ) -> None:
        self.window_seconds = window_seconds
        self.budget_ratio = budget_ratio
        self.min_requests_threshold = min_requests_threshold
        # List of (timestamp, is_retry)
        self._history: list[tuple[float, bool]] = []

    def _purge_old_entries(self, now: float) -> None:
        cutoff = now - self.window_seconds
        # Remove entries outside window
        self._history = [entry for entry in self._history if entry[0] >= cutoff]

    def record_request(self) -> None:
        """Record an incoming top-level request."""
        now = time.time()
        self._purge_old_entries(now)
        self._history.append((now, False))

    def record_retry(self) -> None:
        """Record a retry or failover attempt."""
        now = time.time()
        self._purge_old_entries(now)
        self._history.append((now, True))

    def can_retry(self) -> bool:
        """Check whether retry budget allows an additional retry attempt.

        If total requests in the window are below min_requests_threshold, allows retry.
        If retry ratio exceeds budget_ratio, blocks retry.
        """
        now = time.time()
        self._purge_old_entries(now)

        total_requests = len(self._history)
        if total_requests < self.min_requests_threshold:
            # Below minimum volume threshold: allow retries
            return True

        retry_count = sum(1 for _, is_retry in self._history if is_retry)
        current_ratio = retry_count / total_requests

        return current_ratio <= self.budget_ratio

    def get_budget_status(self) -> dict[str, Any]:
        """Inspect current retry budget health and utilization."""
        now = time.time()
        self._purge_old_entries(now)
        total_requests = len(self._history)
        retry_count = sum(1 for _, is_retry in self._history if is_retry)
        current_ratio = (
            round(retry_count / total_requests, 4) if total_requests > 0 else 0.0
        )

        return {
            "window_seconds": self.window_seconds,
            "budget_ratio": self.budget_ratio,
            "total_requests": total_requests,
            "retry_count": retry_count,
            "current_ratio": current_ratio,
            "budget_exhausted": current_ratio > self.budget_ratio
            if total_requests >= self.min_requests_threshold
            else False,
        }

    def reset(self) -> None:
        """Clear history for testing."""
        self._history.clear()


# Singleton instance
_retry_budget_enforcer: RetryBudgetEnforcer | None = None


def get_retry_budget_enforcer() -> RetryBudgetEnforcer:
    """Dependency getter for RetryBudgetEnforcer."""
    global _retry_budget_enforcer
    if _retry_budget_enforcer is None:
        _retry_budget_enforcer = RetryBudgetEnforcer()
    return _retry_budget_enforcer
