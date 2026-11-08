"""Quota detection, header inspection, and capacity tracking service.

Inspects rate-limit headers (Retry-After, x-ratelimit-*), tracks remaining capacity,
and persists observations in QuotaState across credentials, models, and providers.
Strictly adheres to:
1. Never interprets missing quota as unlimited capacity.
2. Never invents reset times.
3. Never implements account rotation to bypass limits.
"""

from __future__ import annotations

import email.utils
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_credential import ProviderCredential
from app.models.reliability import (
    QuotaConfidence,
    QuotaResourceType,
    QuotaScope,
    QuotaState,
)


def parse_reset_duration(val: str | int | float | None) -> float | None:
    """Parse duration strings such as '2ms', '6s', '1m30s', '2h', or direct numeric seconds."""
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None

    # Check for direct numeric string or number
    try:
        return float(val_str)
    except ValueError:
        pass

    # Regex to extract combinations of hours, minutes, seconds, milliseconds
    pattern = re.compile(
        r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?"
    )
    match = pattern.fullmatch(val_str)
    if not match:
        return None

    hours_s, mins_s, secs_s, ms_s = match.groups()
    if not any([hours_s, mins_s, secs_s, ms_s]):
        return None

    total_seconds = 0.0
    if hours_s:
        total_seconds += float(hours_s) * 3600.0
    if mins_s:
        total_seconds += float(mins_s) * 60.0
    if secs_s:
        total_seconds += float(secs_s)
    if ms_s:
        total_seconds += float(ms_s) / 1000.0

    return total_seconds


def parse_retry_after(
    val: str | int | float | None,
) -> tuple[int | None, datetime | None]:
    """Parse Retry-After header into integer seconds and calculated UTC reset_at timestamp.

    Supports both delta-seconds (RFC 7231) and HTTP-date strings (RFC 2822 / RFC 7231).
    Never invents a timestamp if header value is absent or invalid.
    """
    if val is None:
        return None, None

    now = datetime.now(UTC)
    val_str = str(val).strip()
    if not val_str:
        return None, None

    # Try numeric seconds
    try:
        seconds = max(0, int(float(val_str)))
        reset_at = now + timedelta(seconds=seconds)
        return seconds, reset_at
    except ValueError:
        pass

    # Try HTTP-date
    try:
        parsed_dt = email.utils.parsedate_to_datetime(val_str)
        if parsed_dt:
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=UTC)
            else:
                parsed_dt = parsed_dt.astimezone(UTC)
            diff = (parsed_dt - now).total_seconds()
            seconds = max(0, int(diff))
            return seconds, parsed_dt
    except (ValueError, TypeError):
        pass

    return None, None


class QuotaService:
    """Service for discovering, recording, and querying quota observations."""

    @staticmethod
    def extract_quota_observations_from_headers(
        provider: str,
        headers: dict[str, Any] | httpx.Headers,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        source: str = "header",
    ) -> list[dict[str, Any]]:
        """Parse standard and provider-specific rate-limit headers into quota observations.

        Supports:
        - Groq: x-ratelimit-*-requests, x-ratelimit-*-tokens
        - OpenAI/OpenRouter: x-ratelimit-*, credits headers
        - Generic: Retry-After
        """
        now = datetime.now(UTC)
        norm_headers = {k.lower(): str(v) for k, v in headers.items()}
        observations: list[dict[str, Any]] = []

        # Groq limits are model-specific; general headers default to credential scope
        scope = QuotaScope.MODEL if model_id else QuotaScope.CREDENTIAL

        # ---------------------------------------------------------------------
        # 1. Requests Quota (RPM)
        # ---------------------------------------------------------------------
        rem_req_str = norm_headers.get(
            "x-ratelimit-remaining-requests"
        ) or norm_headers.get("x-ratelimit-remaining")
        limit_req_str = norm_headers.get(
            "x-ratelimit-limit-requests"
        ) or norm_headers.get("x-ratelimit-limit")
        reset_req_str = norm_headers.get(
            "x-ratelimit-reset-requests"
        ) or norm_headers.get("x-ratelimit-reset")

        if (
            rem_req_str is not None
            or limit_req_str is not None
            or reset_req_str is not None
        ):
            rem_req: int | None = None
            limit_req: int | None = None
            reset_req_at: datetime | None = None
            retry_after_req: int | None = None

            if rem_req_str is not None:
                try:
                    rem_req = int(float(rem_req_str))
                except ValueError:
                    pass

            if limit_req_str is not None:
                try:
                    limit_req = int(float(limit_req_str))
                except ValueError:
                    pass

            if reset_req_str is not None:
                duration = parse_reset_duration(reset_req_str)
                if duration is not None:
                    retry_after_req = max(0, int(duration))
                    reset_req_at = now + timedelta(seconds=duration)
                else:
                    # Try timestamp or HTTP date
                    retry_after_req, reset_req_at = parse_retry_after(reset_req_str)

            observations.append(
                {
                    "credential_id": credential_id,
                    "provider": provider.lower().strip(),
                    "quota_scope": scope.value
                    if isinstance(scope, QuotaScope)
                    else str(scope),
                    "model_id": model_id,
                    "resource_type": QuotaResourceType.REQUESTS.value,
                    "limit": limit_req,
                    "remaining": rem_req,
                    "reset_at": reset_req_at,
                    "retry_after": retry_after_req,
                    "confidence": QuotaConfidence.CONFIRMED.value,
                    "source": source,
                    "observed_at": now,
                }
            )

        # ---------------------------------------------------------------------
        # 2. Tokens Quota (TPM / TPD)
        # ---------------------------------------------------------------------
        rem_tok_str = norm_headers.get("x-ratelimit-remaining-tokens")
        limit_tok_str = norm_headers.get("x-ratelimit-limit-tokens")
        reset_tok_str = norm_headers.get("x-ratelimit-reset-tokens")

        if (
            rem_tok_str is not None
            or limit_tok_str is not None
            or reset_tok_str is not None
        ):
            rem_tok: int | None = None
            limit_tok: int | None = None
            reset_tok_at: datetime | None = None
            retry_after_tok: int | None = None

            if rem_tok_str is not None:
                try:
                    rem_tok = int(float(rem_tok_str))
                except ValueError:
                    pass

            if limit_tok_str is not None:
                try:
                    limit_tok = int(float(limit_tok_str))
                except ValueError:
                    pass

            if reset_tok_str is not None:
                duration = parse_reset_duration(reset_tok_str)
                if duration is not None:
                    retry_after_tok = max(0, int(duration))
                    reset_tok_at = now + timedelta(seconds=duration)
                else:
                    retry_after_tok, reset_tok_at = parse_retry_after(reset_tok_str)

            observations.append(
                {
                    "credential_id": credential_id,
                    "provider": provider.lower().strip(),
                    "quota_scope": scope.value
                    if isinstance(scope, QuotaScope)
                    else str(scope),
                    "model_id": model_id,
                    "resource_type": QuotaResourceType.TOKENS.value,
                    "limit": limit_tok,
                    "remaining": rem_tok,
                    "reset_at": reset_tok_at,
                    "retry_after": retry_after_tok,
                    "confidence": QuotaConfidence.CONFIRMED.value,
                    "source": source,
                    "observed_at": now,
                }
            )

        # ---------------------------------------------------------------------
        # 3. Credits / Currency Quota (e.g. OpenRouter)
        # ---------------------------------------------------------------------
        rem_cred_str = norm_headers.get(
            "x-ratelimit-remaining-credits"
        ) or norm_headers.get("x-openrouter-credits-remaining")
        limit_cred_str = norm_headers.get(
            "x-ratelimit-limit-credits"
        ) or norm_headers.get("x-openrouter-credits-limit")
        if rem_cred_str is not None or limit_cred_str is not None:
            rem_cred: int | None = None
            limit_cred: int | None = None
            if rem_cred_str is not None:
                try:
                    rem_cred = int(float(rem_cred_str))
                except ValueError:
                    pass
            if limit_cred_str is not None:
                try:
                    limit_cred = int(float(limit_cred_str))
                except ValueError:
                    pass

            observations.append(
                {
                    "credential_id": credential_id,
                    "provider": provider.lower().strip(),
                    "quota_scope": QuotaScope.CREDENTIAL.value,
                    "model_id": None,
                    "resource_type": QuotaResourceType.CREDITS.value,
                    "limit": limit_cred,
                    "remaining": rem_cred,
                    "reset_at": None,
                    "retry_after": None,
                    "confidence": QuotaConfidence.CONFIRMED.value,
                    "source": source,
                    "observed_at": now,
                }
            )

        # ---------------------------------------------------------------------
        # 4. Standalone Retry-After Header
        # ---------------------------------------------------------------------
        retry_header = norm_headers.get("retry-after")
        if retry_header and not observations:
            sec, reset_at = parse_retry_after(retry_header)
            if sec is not None:
                observations.append(
                    {
                        "credential_id": credential_id,
                        "provider": provider.lower().strip(),
                        "quota_scope": scope.value
                        if isinstance(scope, QuotaScope)
                        else str(scope),
                        "model_id": model_id,
                        "resource_type": QuotaResourceType.REQUESTS.value,
                        "limit": None,
                        "remaining": 0,  # 0 indicates blocked until reset
                        "reset_at": reset_at,
                        "retry_after": sec,
                        "confidence": QuotaConfidence.CONFIRMED.value,
                        "source": "retry_after_header",
                        "observed_at": now,
                    }
                )

        return observations

    async def record_quota_observation(
        self,
        db: AsyncSession,
        observation: dict[str, Any],
    ) -> QuotaState:
        """Upsert a quota observation record in the QuotaState table."""
        cred_id = observation.get("credential_id")
        provider = str(observation.get("provider", "unknown")).lower().strip()
        scope = str(observation.get("quota_scope", QuotaScope.CREDENTIAL.value))
        model_id = observation.get("model_id")
        res_type = str(
            observation.get("resource_type", QuotaResourceType.REQUESTS.value)
        )

        # Query existing row for the same dimension
        stmt = select(QuotaState).where(
            QuotaState.credential_id == cred_id,
            QuotaState.provider == provider,
            QuotaState.quota_scope == scope,
            QuotaState.resource_type == res_type,
        )
        if model_id is not None:
            stmt = stmt.where(QuotaState.model_id == model_id)
        else:
            stmt = stmt.where(QuotaState.model_id.is_(None))

        result = await db.execute(stmt)
        record = result.scalars().first()

        now = observation.get("observed_at") or datetime.now(UTC)

        if record is None:
            record = QuotaState(
                credential_id=cred_id,
                provider=provider,
                quota_scope=scope,
                model_id=model_id,
                resource_type=res_type,
                limit=observation.get("limit"),
                remaining=observation.get("remaining"),
                reset_at=observation.get("reset_at"),
                retry_after=observation.get("retry_after"),
                confidence=observation.get("confidence", QuotaConfidence.UNKNOWN.value),
                source=observation.get("source", "header"),
                observed_at=now,
            )
            db.add(record)
        else:
            record.limit = observation.get("limit", record.limit)
            record.remaining = observation.get("remaining", record.remaining)
            record.reset_at = observation.get("reset_at", record.reset_at)
            record.retry_after = observation.get("retry_after", record.retry_after)
            record.confidence = observation.get("confidence", record.confidence)
            record.source = observation.get("source", record.source)
            record.observed_at = now

        await db.flush()
        return record

    async def process_response_headers(
        self,
        db: AsyncSession,
        provider: str,
        headers: dict[str, Any] | httpx.Headers,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> list[QuotaState]:
        """Extract and persist all quota observations from response headers."""
        parsed = self.extract_quota_observations_from_headers(
            provider=provider,
            headers=headers,
            credential_id=credential_id,
            model_id=model_id,
        )
        saved: list[QuotaState] = []
        for obs in parsed:
            rec = await self.record_quota_observation(db, obs)
            saved.append(rec)
        return saved

    async def get_quota_states(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None = None,
        provider: str | None = None,
        credential_id: uuid.UUID | None = None,
        quota_scope: str | None = None,
        resource_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QuotaState], int]:
        """Retrieve paginated quota states with user scoping and multi-dimensional filters."""
        query = select(QuotaState)

        if user_id is not None:
            # Join credential to enforce user ownership
            query = query.join(
                ProviderCredential,
                QuotaState.credential_id == ProviderCredential.id,
            ).where(ProviderCredential.user_id == user_id)

        if provider:
            query = query.where(QuotaState.provider == provider.lower().strip())
        if credential_id:
            query = query.where(QuotaState.credential_id == credential_id)
        if quota_scope:
            query = query.where(QuotaState.quota_scope == quota_scope.lower().strip())
        if resource_type:
            query = query.where(
                QuotaState.resource_type == resource_type.lower().strip()
            )

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_res = await db.execute(count_query)
        total = total_res.scalar_one() or 0

        # Order by observed_at descending
        paged_query = (
            query.order_by(QuotaState.observed_at.desc()).limit(limit).offset(offset)
        )
        res = await db.execute(paged_query)
        items = list(res.scalars().all())

        return items, total

    async def check_quota_availability(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        model_id: str | None = None,
        required_tokens: int = 1,
    ) -> tuple[bool, str | None]:
        """Check whether capacity exists for the given credential and model.

        Returns (is_available, exhaustion_reason).
        Never treats missing quota as unlimited, but allows request if not confirmed exhausted.
        """
        now = datetime.now(UTC)

        stmt = select(QuotaState).where(
            QuotaState.credential_id == credential_id,
        )
        if model_id:
            stmt = stmt.where(
                (QuotaState.model_id == model_id) | (QuotaState.model_id.is_(None))
            )

        res = await db.execute(stmt)
        records = list(res.scalars().all())

        for rec in records:
            # Check if confirmed exhausted and reset is in the future
            if rec.remaining is not None and rec.remaining <= 0:
                if rec.reset_at and rec.reset_at > now:
                    wait_sec = int((rec.reset_at - now).total_seconds())
                    return (
                        False,
                        f"Quota exhausted for {rec.resource_type} on {rec.provider} (resets in {wait_sec}s)",
                    )
                if rec.retry_after and rec.retry_after > 0:
                    return (
                        False,
                        f"Quota rate-limited for {rec.resource_type} on {rec.provider} (retry after {rec.retry_after}s)",
                    )

        return True, None


# Singleton instance provider
_quota_service: QuotaService | None = None


def get_quota_service() -> QuotaService:
    """Dependency injection provider for QuotaService."""
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService()
    return _quota_service
