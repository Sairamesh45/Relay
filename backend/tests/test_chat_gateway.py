"""Tests for Chat Gateway translation, response normalization, streaming, and rate limiting."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.core.gateway_errors import OpenAIHTTPException
from app.models.gateway_request_log import GatewayRequestLog
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.groq import GroqProvider
from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.manager import ProviderManager
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)
from app.services.chat_gateway import ChatGatewayService
from app.services.gateway_usage import GatewayUsageService
from app.services.model_resolver import ModelResolverService
from app.services.rate_limiter import RateLimiterService
from app.services.virtual_key_service import VirtualKeyService


@pytest.fixture
def test_setup():
    return {
        "manager": ProviderManager(),
        "resolver": ModelResolverService(),
        "rate_limiter": RateLimiterService(default_rpm=5),
        "usage_svc": GatewayUsageService(),
    }


@pytest.mark.asyncio
async def test_groq_chat_completion_non_streaming(db_session: AsyncSession) -> None:
    """Verify Groq non-streaming request translation, response normalization, and usage tracking."""
    user = User(id=uuid.uuid4(), email=f"groq_chat_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Test Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-test-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-test-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(
        canonical_id=f"test-llama/llama-3.3-70b-versatile-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred.id,
        availability_status="available",
    )
    db_session.add(pm)
    await db_session.commit()

    # Mock Groq API response
    groq_api_response = {
        "id": "chatcmpl-mock-groq-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "llama-3.3-70b-versatile",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from Groq LPU!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gsk-test-key"
        body = json.loads(request.content)
        assert body["model"] == "llama-3.3-70b-versatile"
        assert body["messages"][0]["content"] == "Hello Groq"
        return httpx.Response(200, json=groq_api_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = ProviderManager()
        groq_prov = GroqProvider(http_client=client)
        mgr.register_provider(groq_prov)

        gateway_svc = ChatGatewayService(provider_manager=mgr)
        chat_req = ChatCompletionRequest(
            model="groq:llama-3.3-70b-versatile",
            messages=[ChatMessage(role="user", content="Hello Groq")],
            temperature=0.7,
        )

        response = await gateway_svc.create_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        )

        assert response.id == "chatcmpl-mock-groq-123"
        assert response.model == "groq:llama-3.3-70b-versatile"
        assert response.choices[0].message.content == "Hello from Groq LPU!"
        assert response.choices[0].finish_reason == "stop"
        assert response.usage.total_tokens == 20

        # Verify audit log recorded
        log = (
            await db_session.execute(
                select(GatewayRequestLog).where(
                    GatewayRequestLog.virtual_api_key_id == key_record.id
                )
            )
        ).scalar_one()
        assert log.status == "success"
        assert log.total_tokens == 20
        assert log.provider == "groq"


@pytest.mark.asyncio
async def test_gemini_chat_completion_translation_and_normalization(
    db_session: AsyncSession,
) -> None:
    """Verify Gemini request translation (system_instruction, contents) and candidate parsing."""
    user = User(id=uuid.uuid4(), email=f"gem_chat_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Gemini Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="gemini",
        encrypted_api_key=encrypt_api_key("gemini-test-secret"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gemini-test-secret"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(
        canonical_id=f"test-google/gemini-2.5-flash-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="gemini",
        provider_model_id="gemini-2.5-flash",
        credential_id=cred.id,
        availability_status="available",
    )
    db_session.add(pm)
    await db_session.commit()

    gemini_api_response = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Hello from Gemini Flash!"}],
                    "role": "model",
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 15,
            "candidatesTokenCount": 6,
            "totalTokenCount": 21,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "gemini-test-secret"
        assert "models/gemini-2.5-flash:generateContent" in str(request.url)
        body = json.loads(request.content)

        # Verify translation of system role into system_instruction
        assert (
            body["system_instruction"]["parts"][0]["text"]
            == "You are a helpful assistant."
        )
        # Verify user message in contents
        assert body["contents"][0]["role"] == "user"
        assert body["contents"][0]["parts"][0]["text"] == "Hi Gemini"
        return httpx.Response(200, json=gemini_api_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = ProviderManager()
        gemini_prov = GeminiProvider(http_client=client)
        mgr.register_provider(gemini_prov)

        gateway_svc = ChatGatewayService(provider_manager=mgr)
        chat_req = ChatCompletionRequest(
            model="gemini:gemini-2.5-flash",
            messages=[
                ChatMessage(role="system", content="You are a helpful assistant."),
                ChatMessage(role="user", content="Hi Gemini"),
            ],
            temperature=0.2,
        )

        response = await gateway_svc.create_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        )

        assert response.model == "gemini:gemini-2.5-flash"
        assert response.choices[0].message.content == "Hello from Gemini Flash!"
        assert response.choices[0].finish_reason == "stop"
        assert response.usage.total_tokens == 21


@pytest.mark.asyncio
async def test_streaming_chat_completion_sse_chunks(db_session: AsyncSession) -> None:
    """Verify Server-Sent Events streaming chunks, finish reason, and terminal [DONE] marker."""
    user = User(id=uuid.uuid4(), email=f"stream_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Stream Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="openrouter",
        encrypted_api_key=encrypt_api_key("or-test-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("or-test-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test-openai/gpt-4o-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="openrouter",
        provider_model_id="openai/gpt-4o:free",
        credential_id=cred.id,
        availability_status="available",
        input_price_per_million=0,
        output_price_per_million=0,
    )
    db_session.add(pm)
    await db_session.commit()

    sse_data = (
        'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n'
        'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=sse_data,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = ProviderManager()
        or_prov = OpenRouterProvider(http_client=client)
        mgr.register_provider(or_prov)

        gateway_svc = ChatGatewayService(provider_manager=mgr)
        chat_req = ChatCompletionRequest(
            model="openrouter:openai/gpt-4o:free",
            messages=[ChatMessage(role="user", content="Stream test")],
            stream=True,
        )

        chunks: list[str] = []
        async for chunk_str in gateway_svc.stream_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        ):
            chunks.append(chunk_str)

        assert len(chunks) == 3
        assert "Hello" in chunks[0]
        assert "world" in chunks[1]
        assert chunks[2] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_rate_limiting_enforcement_and_retry_after(
    db_session: AsyncSession,
) -> None:
    """Verify that requests exceeding RPM threshold raise 429 with Retry-After header."""
    user = User(id=uuid.uuid4(), email=f"rl_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "RL Key")

    # Rate limiter configured with limit=2
    rate_limiter = RateLimiterService(default_rpm=2)

    # 1st request succeeds
    await rate_limiter.check_rate_limit(db_session, key_record.id)

    # 2nd request succeeds
    await rate_limiter.check_rate_limit(db_session, key_record.id)

    # 3rd request must be blocked with 429
    with pytest.raises(OpenAIHTTPException) as exc_info:
        await rate_limiter.check_rate_limit(db_session, key_record.id)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"]["type"] == "rate_limit_error"
    assert "Retry-After" in exc_info.value.headers
