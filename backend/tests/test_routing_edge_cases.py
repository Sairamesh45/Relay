"""Edge case and security verification tests for Phase 5 Intelligent Routing."""

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
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.chat_gateway import ChatGatewayService
from app.services.routing.candidates import CandidateDiscoveryService
from app.services.routing.context import RoutingContext
from app.services.virtual_key_service import VirtualKeyService


@pytest.mark.asyncio
async def test_explicit_routing_enforces_policy_provider_and_model_whitelists(
    db_session: AsyncSession,
) -> None:
    """Explicit request 'gemini:gemini-2.5-flash' MUST be rejected if policy excludes gemini or limits allowed_providers to groq."""
    discovery_svc = CandidateDiscoveryService()

    user = User(id=uuid.uuid4(), email=f"expl_sec_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred_gemini = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="gemini",
        encrypted_api_key=encrypt_api_key("gemini-sec-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gemini-sec-key"),
        status="active",
    )
    db_session.add(cred_gemini)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/gemini-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm_gemini = ProviderModel(
        unified_model_id=um.id,
        provider="gemini",
        provider_model_id="gemini-2.5-flash",
        credential_id=cred_gemini.id,
        availability_status="available",
    )
    db_session.add(pm_gemini)
    await db_session.flush()

    # Create virtual key with policy that excludes gemini
    key, _ = await VirtualKeyService().create_key(db_session, user, "Restricted Key")
    policy = key.routing_policy
    policy.allowed_providers = ["groq"]  # only groq allowed
    policy.excluded_providers = ["gemini"]
    await db_session.commit()

    # Explicit request for gemini
    req = ChatCompletionRequest(
        model="gemini:gemini-2.5-flash",
        messages=[ChatMessage(role="user", content="Hi")],
    )
    ctx = RoutingContext.from_request(user, key, policy, req)

    result = await discovery_svc.discover_candidates(db_session, ctx)
    # The explicit request to Gemini MUST NOT be eligible because Gemini is excluded / not in allowed_providers!
    assert len(result.eligible) == 0, (
        "Security violation: Explicit request bypassed allowed_providers and excluded_providers!"
    )


@pytest.mark.asyncio
async def test_explicit_routing_enforces_virtual_key_permissions(
    db_session: AsyncSession,
) -> None:
    """Explicit request 'gemini:gemini-2.5-flash' MUST be rejected if key.permissions restricts models to 'groq:*'."""
    discovery_svc = CandidateDiscoveryService()

    user = User(id=uuid.uuid4(), email=f"perm_sec_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="gemini",
        encrypted_api_key=encrypt_api_key("gemini-perm-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gemini-perm-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/gemini-perm-{uuid.uuid4().hex[:8]}")
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
    await db_session.flush()

    # Create key with explicit permissions limiting to groq only
    key, _ = await VirtualKeyService().create_key(
        db_session, user, "Groq Only Key", permissions={"models": ["groq:*"]}
    )
    policy = key.routing_policy
    await db_session.commit()

    req = ChatCompletionRequest(
        model="gemini:gemini-2.5-flash",
        messages=[ChatMessage(role="user", content="Hi")],
    )
    ctx = RoutingContext.from_request(user, key, policy, req)

    result = await discovery_svc.discover_candidates(db_session, ctx)
    assert len(result.eligible) == 0, (
        "Security violation: Virtual key permissions were bypassed by explicit routing!"
    )


@pytest.mark.asyncio
async def test_unknown_alias_rejected_and_not_auto_routed(
    db_session: AsyncSession,
) -> None:
    """Request with unknown model string without colon like 'random-nonexistent-model' must be rejected, NOT treated as auto!"""
    user = User(
        id=uuid.uuid4(), email=f"unknown_alias_{uuid.uuid4().hex[:8]}@example.com"
    )
    db_session.add(user)
    await db_session.flush()

    key, _ = await VirtualKeyService().create_key(db_session, user, "Test Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("groq-alias-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("groq-alias-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/groq-alias-{uuid.uuid4().hex[:8]}")
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

    gateway = ChatGatewayService()
    req = ChatCompletionRequest(
        model="random-nonexistent-model",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    # Must raise model not found / invalid request 404 or 400
    with pytest.raises(OpenAIHTTPException) as exc_info:
        await gateway.create_chat_completion(
            db=db_session, user=user, key=key, request=req
        )
    assert exc_info.value.status_code in (400, 404)


@pytest.mark.asyncio
async def test_routing_decision_log_request_id_correlates_with_gateway(
    db_session: AsyncSession,
) -> None:
    """Verify RoutingDecisionLog records the exact same request_id as the gateway request."""
    user = User(id=uuid.uuid4(), email=f"corr_gw_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key, _ = await VirtualKeyService().create_key(db_session, user, "Corr Key")

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk-corr-key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gsk-corr-key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/corr-model-{uuid.uuid4().hex[:8]}")
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

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-corr-123",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "llama-3.3-70b-versatile",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Done"},
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
        gateway = ChatGatewayService(provider_manager=mgr)

        req = ChatCompletionRequest(
            model="auto",
            messages=[ChatMessage(role="user", content="Test")],
        )
        response = await gateway.create_chat_completion(
            db=db_session, user=user, key=key, request=req
        )
        assert response is not None

    # Now verify RoutingDecisionLog request_id matches GatewayRequestLog request_id!
    from app.models.gateway_request_log import GatewayRequestLog

    gw_log = (
        await db_session.execute(
            select(GatewayRequestLog)
            .where(GatewayRequestLog.virtual_api_key_id == key.id)
            .order_by(GatewayRequestLog.created_at.desc())
        )
    ).scalar_one()

    dec_log = (
        await db_session.execute(
            select(RoutingDecisionLog)
            .where(RoutingDecisionLog.virtual_api_key_id == key.id)
            .order_by(RoutingDecisionLog.created_at.desc())
        )
    ).scalar_one()

    assert gw_log.request_id == dec_log.request_id, (
        f"Mismatch: GatewayRequestLog.request_id={gw_log.request_id} != RoutingDecisionLog.request_id={dec_log.request_id}"
    )


@pytest.mark.asyncio
async def test_structured_output_json_schema_detection() -> None:
    """Verify that response_format with 'json_schema' sets requires_structured_output=True."""
    from app.models.routing_policy import VirtualKeyRoutingPolicy
    from app.schemas.chat import ChatCompletionRequest, ChatMessage
    from app.services.routing.context import RoutingContext

    user = User(id=uuid.uuid4(), email="u@example.com")
    policy = VirtualKeyRoutingPolicy()
    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Give json")],
        response_format={"type": "json_schema", "json_schema": {"name": "test"}},
    )
    ctx = RoutingContext.from_request(user=user, key=None, policy=policy, request=req)
    assert ctx.requires_structured_output is True


@pytest.mark.asyncio
async def test_preview_routing_respects_preferred_credential(
    db_session: AsyncSession,
) -> None:
    """Verify preview endpoint selects the preferred credential rather than lowest UUID."""
    from app.api.routes.keys import preview_routing
    from app.schemas.routing import RoutingPreviewRequest

    user = User(id=uuid.uuid4(), email=f"prev_pref_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    # Ensure Credential A has a lower UUID string, Credential B has a higher UUID string
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    if str(u1) > str(u2):
        u1, u2 = u2, u1
    id_a, id_b = u1, u2

    cred_a = ProviderCredential(
        id=id_a,
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-a"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-a"),
        status="active",
        display_name="Account A",
    )
    cred_b = ProviderCredential(
        id=id_b,
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-b"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-b"),
        status="active",
        display_name="Account B",
    )
    db_session.add_all([cred_a, cred_b])
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/prev-model-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm_a = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred_a.id,
        availability_status="available",
    )
    pm_b = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred_b.id,
        availability_status="available",
    )
    db_session.add_all([pm_a, pm_b])
    await db_session.flush()

    key, _ = await VirtualKeyService().create_key(db_session, user, "Preview Key")
    policy = key.routing_policy
    policy.credential_selection_strategy = "preferred"
    policy.preferred_credential_id = cred_b.id
    await db_session.commit()

    from app.services.routing.candidates import get_candidate_discovery_service
    from app.services.routing.engine import get_routing_engine
    from app.services.routing.metrics import get_routing_metrics_service
    from app.services.routing.scoring import get_model_scorer

    resp = await preview_routing(
        key_id=key.id,
        payload=RoutingPreviewRequest(model="auto"),
        user=user,
        db=db_session,
        key_service=VirtualKeyService(),
        routing_engine=get_routing_engine(),
        discovery_service=get_candidate_discovery_service(),
        scorer=get_model_scorer(),
        metrics_service=get_routing_metrics_service(),
    )

    assert resp.selected_candidate is not None
    assert resp.selected_candidate.credential_id == id_b, (
        f"Expected preferred credential {id_b}, but got {resp.selected_candidate.credential_id}"
    )
