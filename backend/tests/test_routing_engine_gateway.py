"""End-to-end tests for Gateway execution with Intelligent Routing Engine (auto, fast, smart, explicit)."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.core.gateway_errors import OpenAIHTTPException
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.providers.adapters.groq import GroqProvider
from app.providers.manager import ProviderManager
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)
from app.services.chat_gateway import ChatGatewayService
from app.services.routing.engine import (
    CandidateDiscoveryContext,
    get_routing_engine,
)
from app.services.routing.scoring import ScoredCandidate
from app.services.virtual_key_service import VirtualKeyService


@pytest.mark.asyncio
async def test_gateway_chat_completion_with_auto_routing(
    db_session: AsyncSession,
) -> None:
    """Verify that 'model': 'auto' uses key's policy, selects top candidate, dispatches, and logs audit."""
    user = User(id=uuid.uuid4(), email=f"auto_gw_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Auto Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-auto-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-auto-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/auto-model-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred.id,
        availability_status="available",
        supports_tools=True,
        supports_streaming=True,
    )
    db_session.add(pm)
    await db_session.commit()

    # Mock Groq upstream
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gsk-auto-key"
        body = json.loads(request.content)
        assert body["model"] == "llama-3.3-70b-versatile"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-auto-123",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "llama-3.3-70b-versatile",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Auto routed response!",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = ProviderManager()
        mgr.register_provider(GroqProvider(http_client=client))

        gateway_svc = ChatGatewayService(provider_manager=mgr)
        chat_req = ChatCompletionRequest(
            model="auto",
            messages=[ChatMessage(role="user", content="Hello auto router")],
        )

        response = await gateway_svc.create_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        )

        assert response.id == "chatcmpl-auto-123"
        assert response.choices[0].message.content == "Auto routed response!"

        # Verify RoutingDecisionLog was written
        decision_stmt = select(RoutingDecisionLog).where(
            RoutingDecisionLog.virtual_api_key_id == key_record.id
        )
        decision_res = await db_session.execute(decision_stmt)
        decision_log = decision_res.scalar_one_or_none()
        assert decision_log is not None
        assert decision_log.routing_mode == "auto"
        assert decision_log.selected_provider == "groq"
        assert decision_log.selected_model == "llama-3.3-70b-versatile"
        assert decision_log.selected_credential_id == cred.id


@pytest.mark.asyncio
async def test_gateway_chat_completion_with_fast_routing(
    db_session: AsyncSession,
) -> None:
    """Verify that 'model': 'fast' activates Speed First preset weights."""
    user = User(id=uuid.uuid4(), email=f"fast_gw_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Fast Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-fast-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-fast-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/fast-model-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.1-8b-instant",
        credential_id=cred.id,
        availability_status="available",
    )
    db_session.add(pm)
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-fast-123",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "llama-3.1-8b-instant",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Fast response!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 5,
                    "total_tokens": 10,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        mgr = ProviderManager()
        mgr.register_provider(GroqProvider(http_client=client))

        gateway_svc = ChatGatewayService(provider_manager=mgr)
        chat_req = ChatCompletionRequest(
            model="fast",
            messages=[ChatMessage(role="user", content="Quick response please")],
        )

        response = await gateway_svc.create_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        )

        assert response.id == "chatcmpl-fast-123"

        decision_stmt = select(RoutingDecisionLog).where(
            RoutingDecisionLog.virtual_api_key_id == key_record.id
        )
        decision_log = (await db_session.execute(decision_stmt)).scalar_one()
        assert decision_log.routing_mode == "fast"
        assert decision_log.score_breakdown["effective_weights"]["speed"] == 0.60


@pytest.mark.asyncio
async def test_gateway_no_eligible_candidates_returns_404(
    db_session: AsyncSession,
) -> None:
    """Verify that when no eligible candidate satisfies constraints, clear 404 is returned."""
    user = User(id=uuid.uuid4(), email=f"empty_gw_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Empty Key")

    # User has no credentials at all
    mgr = ProviderManager()
    gateway_svc = ChatGatewayService(provider_manager=mgr)
    chat_req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Hello")],
    )

    with pytest.raises(OpenAIHTTPException) as exc_info:
        await gateway_svc.create_chat_completion(
            db=db_session, user=user, key=key_record, request=chat_req
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_get_ranked_candidates_side_effect_free(
    db_session: AsyncSession,
) -> None:
    """Verify get_ranked_candidates returns scored candidates without creating decision logs or mutating state."""
    user = User(id=uuid.uuid4(), email=f"sideeffect_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "SE Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-test-se"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-test-se"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/se-model-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred.id,
        availability_status="available",
        supports_tools=True,
        supports_streaming=True,
    )
    db_session.add(pm)
    await db_session.commit()

    engine = get_routing_engine()
    policy = await engine.get_or_create_policy(db_session, key_record, user)

    chat_req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Ranked candidates test")],
    )
    ctx = CandidateDiscoveryContext.from_request(
        user=user,
        key=key_record,
        policy=policy,
        request=chat_req,
    )

    ranked_candidates = await engine.get_ranked_candidates(db_session, ctx)

    assert len(ranked_candidates) == 1
    assert isinstance(ranked_candidates[0], ScoredCandidate)
    assert ranked_candidates[0].candidate.provider == "groq"
    assert ranked_candidates[0].candidate.provider_model_id == "llama-3.3-70b-versatile"
    assert ranked_candidates[0].score_breakdown.final_score > 0

    # Verify no RoutingDecisionLog was written (side-effect free)
    stmt = select(RoutingDecisionLog).where(
        RoutingDecisionLog.virtual_api_key_id == key_record.id
    )
    logs = (await db_session.execute(stmt)).scalars().all()
    assert len(logs) == 0


@pytest.mark.asyncio
async def test_get_ranked_candidates_empty_pool_returns_empty_list(
    db_session: AsyncSession,
) -> None:
    """Verify get_ranked_candidates returns [] rather than raising 404 when no candidates match."""
    user = User(id=uuid.uuid4(), email=f"empty_pool_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(
        db_session, user, "Empty Pool Key"
    )
    engine = get_routing_engine()
    policy = await engine.get_or_create_policy(db_session, key_record, user)

    chat_req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="No models")],
    )
    ctx = CandidateDiscoveryContext.from_request(
        user=user,
        key=key_record,
        policy=policy,
        request=chat_req,
    )

    ranked_candidates = await engine.get_ranked_candidates(db_session, ctx)
    assert ranked_candidates == []


@pytest.mark.asyncio
async def test_get_ranked_candidates_ranks_multiple_candidates(
    db_session: AsyncSession,
) -> None:
    """Verify get_ranked_candidates ranks multiple candidates deterministically in descending score order."""
    user = User(id=uuid.uuid4(), email=f"multi_cand_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(db_session, user, "Multi Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-test-multi"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-test-multi"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um1 = UnifiedModel(canonical_id=f"test/model1-{uuid.uuid4().hex[:8]}")
    um2 = UnifiedModel(canonical_id=f"test/model2-{uuid.uuid4().hex[:8]}")
    db_session.add_all([um1, um2])
    await db_session.flush()

    pm1 = ProviderModel(
        unified_model_id=um1.id,
        provider="groq",
        provider_model_id="llama-3.1-8b-instant",
        credential_id=cred.id,
        availability_status="available",
        input_price_per_million=0.05,
        output_price_per_million=0.08,
    )
    pm2 = ProviderModel(
        unified_model_id=um2.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred.id,
        availability_status="available",
        input_price_per_million=0.59,
        output_price_per_million=0.79,
    )
    db_session.add_all([pm1, pm2])
    await db_session.commit()

    engine = get_routing_engine()
    policy = await engine.get_or_create_policy(db_session, key_record, user)

    chat_req = ChatCompletionRequest(
        model="cheap",  # cost-optimized preset emphasizes lower pricing
        messages=[ChatMessage(role="user", content="Rank candidates test")],
    )
    ctx = CandidateDiscoveryContext.from_request(
        user=user,
        key=key_record,
        policy=policy,
        request=chat_req,
    )

    ranked = await engine.get_ranked_candidates(db_session, ctx)
    assert len(ranked) == 2
    # The cheaper model (llama-3.1-8b-instant) should rank higher on cost-optimized
    assert (
        ranked[0].score_breakdown.final_score >= ranked[1].score_breakdown.final_score
    )
    assert ranked[0].candidate.provider_model_id == "llama-3.1-8b-instant"
