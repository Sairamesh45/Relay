"""Core Chat Gateway Service orchestrating model resolution, rate limiting, provider dispatch, and usage logging."""

import logging
import time
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_errors import openai_internal_error, openai_provider_error
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.providers.manager import ProviderManager, get_provider_manager
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.services.gateway_usage import GatewayUsageService, get_gateway_usage_service
from app.services.model_resolver import (
    ModelResolverService,
    ResolvedOffering,
    get_model_resolver_service,
)
from app.services.rate_limiter import RateLimiterService, get_rate_limiter_service
from app.services.reliability.failover_engine import (
    FailoverExecutionEngine,
)
from app.services.routing.engine import RoutingEngine, get_routing_engine

logger = logging.getLogger(__name__)


class ChatGatewayService:
    """Gateway service coordinating rate limiting, model resolution, translation dispatch, and usage auditing."""

    def __init__(
        self,
        model_resolver: ModelResolverService | None = None,
        provider_manager: ProviderManager | None = None,
        rate_limiter: RateLimiterService | None = None,
        usage_service: GatewayUsageService | None = None,
        routing_engine: RoutingEngine | None = None,
        failover_engine: FailoverExecutionEngine | None = None,
    ) -> None:
        self.model_resolver = model_resolver or get_model_resolver_service()
        self.provider_manager = provider_manager or get_provider_manager()
        self.rate_limiter = rate_limiter or get_rate_limiter_service()
        self.usage_service = usage_service or get_gateway_usage_service()
        self.routing_engine = routing_engine or get_routing_engine()
        self.failover_engine = failover_engine or FailoverExecutionEngine(
            routing_engine=self.routing_engine,
            provider_manager=self.provider_manager,
            usage_service=self.usage_service,
        )
        self._custom_resolver = model_resolver is not None

    async def create_chat_completion(
        self,
        db: AsyncSession,
        user: User,
        key: VirtualAPIKey,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """Handle non-streaming OpenAI-compatible chat completion requests."""
        request_id = f"req_{uuid.uuid4().hex}"
        start_time = time.perf_counter()

        # 1. Rate limiting check
        await self.rate_limiter.check_rate_limit(db, key.id)

        # 2. If a custom resolver was explicitly provided (e.g. legacy mocks in tests), preserve legacy behavior
        if self._custom_resolver:
            resolved: ResolvedOffering = await self.model_resolver.resolve_model(
                db, user, request.model
            )
            adapter = self.provider_manager.get_provider(resolved.provider)

            try:
                response = await adapter.create_chat_completion(
                    api_key=resolved.raw_api_key,
                    request=request,
                    provider_model_id=resolved.provider_model_id,
                )
                latency_ms = int((time.perf_counter() - start_time) * 1000)

                input_tokens = response.usage.prompt_tokens if response.usage else None
                output_tokens = (
                    response.usage.completion_tokens if response.usage else None
                )
                total_tokens = response.usage.total_tokens if response.usage else None

                await self.usage_service.record_request(
                    db=db,
                    user_id=user.id,
                    virtual_api_key_id=key.id,
                    provider_credential_id=uuid.UUID(resolved.credential_id),
                    provider=resolved.provider,
                    provider_model_id=resolved.provider_model_id,
                    gateway_model_id=resolved.gateway_model_id,
                    request_id=request_id,
                    status="success",
                    status_code=200,
                    latency_ms=latency_ms,
                    streaming=False,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                return response

            except (
                RateLimitError,
                ProviderTimeoutError,
                ProviderUnavailableError,
                InvalidCredentialsError,
            ) as exc:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                status_code = getattr(exc, "status_code", 502) or 502

                await self.usage_service.record_request(
                    db=db,
                    user_id=user.id,
                    virtual_api_key_id=key.id,
                    provider_credential_id=uuid.UUID(resolved.credential_id),
                    provider=resolved.provider,
                    provider_model_id=resolved.provider_model_id,
                    gateway_model_id=resolved.gateway_model_id,
                    request_id=request_id,
                    status="error",
                    status_code=status_code,
                    latency_ms=latency_ms,
                    streaming=False,
                    error_code=type(exc).__name__,
                    error_summary=exc.message,
                )
                raise openai_provider_error(
                    message=f"Upstream provider '{resolved.provider}' error: {exc.message}",
                    status_code=status_code,
                ) from exc

            except Exception as exc:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                logger.error(
                    "Unexpected error in chat completion gateway: %s",
                    exc,
                    exc_info=True,
                )

                await self.usage_service.record_request(
                    db=db,
                    user_id=user.id,
                    virtual_api_key_id=key.id,
                    provider_credential_id=uuid.UUID(resolved.credential_id),
                    provider=resolved.provider,
                    provider_model_id=resolved.provider_model_id,
                    gateway_model_id=resolved.gateway_model_id,
                    request_id=request_id,
                    status="error",
                    status_code=500,
                    latency_ms=latency_ms,
                    streaming=False,
                    error_code=type(exc).__name__,
                    error_summary=str(exc),
                )
                raise openai_internal_error(
                    "An unexpected error occurred while processing the request."
                ) from exc

        # 3. Default path: Automatic 3-Level Failover & Execution Engine
        policy = await self.routing_engine.get_or_create_policy(db, key, user)
        response, trace = await self.failover_engine.execute_chat_completion(
            db=db,
            user=user,
            key=key,
            request=request,
            request_id=request_id,
            policy=policy,
        )
        return response

    async def stream_chat_completion(
        self,
        db: AsyncSession,
        user: User,
        key: VirtualAPIKey,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[str, None]:
        """Handle streaming OpenAI-compatible chat completion requests via Server-Sent Events."""
        request_id = f"req_{uuid.uuid4().hex}"
        start_time = time.perf_counter()

        # 1. Rate limiting check
        await self.rate_limiter.check_rate_limit(db, key.id)

        # 2. If a custom resolver was explicitly provided, preserve legacy behavior
        if self._custom_resolver:
            resolved: ResolvedOffering = await self.model_resolver.resolve_model(
                db, user, request.model
            )
            adapter = self.provider_manager.get_provider(resolved.provider)

            input_tokens: int | None = None
            output_tokens: int | None = None
            total_tokens: int | None = None
            status = "success"
            error_summary: str | None = None
            error_code: str | None = None
            status_code = 200

            try:
                async for chunk in adapter.stream_chat_completion(
                    api_key=resolved.raw_api_key,
                    request=request,
                    provider_model_id=resolved.provider_model_id,
                ):
                    if chunk.usage:
                        input_tokens = chunk.usage.prompt_tokens
                        output_tokens = chunk.usage.completion_tokens
                        total_tokens = chunk.usage.total_tokens

                    yield f"data: {chunk.model_dump_json()}\n\n"

                yield "data: [DONE]\n\n"

            except (
                RateLimitError,
                ProviderTimeoutError,
                ProviderUnavailableError,
                InvalidCredentialsError,
            ) as exc:
                status = "error"
                error_code = type(exc).__name__
                error_summary = exc.message
                status_code = getattr(exc, "status_code", 502) or 502
                logger.warning(
                    "Streaming error for provider %s: %s",
                    resolved.provider,
                    exc.message,
                )
                raise openai_provider_error(
                    message=f"Upstream provider '{resolved.provider}' streaming error: {exc.message}",
                    status_code=status_code,
                ) from exc

            except Exception as exc:
                status = "error"
                error_code = type(exc).__name__
                error_summary = str(exc)
                status_code = 500
                logger.error("Unexpected streaming error: %s", exc, exc_info=True)
                raise openai_internal_error(
                    "An unexpected error occurred during stream generation."
                ) from exc

            finally:
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                try:
                    await self.usage_service.record_request(
                        db=db,
                        user_id=user.id,
                        virtual_api_key_id=key.id,
                        provider_credential_id=uuid.UUID(resolved.credential_id),
                        provider=resolved.provider,
                        provider_model_id=resolved.provider_model_id,
                        gateway_model_id=resolved.gateway_model_id,
                        request_id=request_id,
                        status=status,
                        status_code=status_code,
                        latency_ms=latency_ms,
                        streaming=True,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        error_code=error_code,
                        error_summary=error_summary,
                    )
                except Exception as e:
                    logger.error("Failed to record streaming audit log: %s", e)
            return

        # 3. Default path: Failover & Execution Engine streaming with pre-chunk failover and post-chunk terminal SSE
        policy = await self.routing_engine.get_or_create_policy(db, key, user)
        async for chunk_str in self.failover_engine.execute_stream_chat_completion(
            db=db,
            user=user,
            key=key,
            request=request,
            request_id=request_id,
            policy=policy,
        ):
            yield chunk_str


# Singleton instance
chat_gateway_service = ChatGatewayService()


def get_chat_gateway_service() -> ChatGatewayService:
    """FastAPI dependency provider for ChatGatewayService."""
    return chat_gateway_service
