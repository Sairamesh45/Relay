"""Tests for ModelSyncService idempotency, reconciliation, and audit logging."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.models.model_sync_log import ModelSyncLog
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.user import User
from app.providers.base import BaseProvider
from app.providers.exceptions import InvalidCredentialsError, ProviderTimeoutError
from app.providers.manager import ProviderManager
from app.providers.schemas.model import CapabilityConfidence
from app.providers.schemas.model import UnifiedModel as ProviderRawModel
from app.providers.schemas.provider import ProviderInfo
from app.services.model_normalizer import ModelNormalizer
from app.services.model_sync import ModelSyncService


class MockSyncProvider(BaseProvider):
    def __init__(
        self,
        provider_id: str,
        return_models: list[ProviderRawModel],
        should_fail: bool = False,
        fail_type: str = "timeout",
    ) -> None:
        super().__init__()
        self._provider_id = provider_id
        self.return_models = return_models
        self.should_fail = should_fail
        self.fail_type = fail_type

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(id=self._provider_id, name="Mock Sync Provider")

    async def validate_credentials(self, api_key: str) -> bool:
        if self.should_fail and self.fail_type == "auth":
            raise InvalidCredentialsError("Invalid key", provider=self._provider_id)
        return True

    async def list_models(self, api_key: str) -> list[ProviderRawModel]:
        if self.should_fail:
            if self.fail_type == "auth":
                raise InvalidCredentialsError("Invalid key", provider=self._provider_id)
            raise ProviderTimeoutError("Network timeout", provider=self._provider_id)
        return self.return_models


@pytest.fixture
def sync_env() -> tuple[ProviderManager, ModelNormalizer, ModelSyncService]:
    mgr = ProviderManager()
    normalizer = ModelNormalizer()
    service = ModelSyncService(provider_manager=mgr, normalizer=normalizer)
    return mgr, normalizer, service


@pytest.mark.asyncio
async def test_sync_credential_creation_and_idempotence(
    db_session: AsyncSession,
    sync_env: tuple[ProviderManager, ModelNormalizer, ModelSyncService],
) -> None:
    mgr, normalizer, sync_service = sync_env

    # Setup mock user and credential
    user = User(id=uuid.uuid4(), email=f"sync_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    raw_key = "test-sync-key-12345"
    encrypted_key = encrypt_api_key(raw_key)
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="mock_p1",
        encrypted_api_key=encrypted_key,
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key),
        status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    # Mock provider offering 2 models
    models_v1 = [
        ProviderRawModel(
            id="mock-model-a",
            provider="mock_p1",
            name="Mock Model A",
            context_window=8192,
            input_modalities=["text"],
            output_modalities=["text"],
            supports_streaming=True,
            capabilities_confidence={
                "supports_streaming": CapabilityConfidence.CONFIRMED.value
            },
        ),
        ProviderRawModel(
            id="mock-model-b",
            provider="mock_p1",
            name="Mock Model B",
            context_window=16384,
            input_modalities=["text", "image"],
            output_modalities=["text"],
            supports_tools=True,
            capabilities_confidence={
                "supports_tools": CapabilityConfidence.CONFIRMED.value
            },
        ),
    ]
    mock_provider = MockSyncProvider("mock_p1", return_models=models_v1)
    mgr.register_provider(mock_provider)

    # First Sync Run
    res1 = await sync_service.sync_credential(db_session, user, cred)
    assert res1.status == "completed"
    assert res1.models_discovered == 2
    assert res1.models_added == 2
    assert res1.models_updated == 0

    # Verify rows in DB
    pms = (
        (
            await db_session.execute(
                select(ProviderModel).where(ProviderModel.credential_id == cred.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(pms) == 2
    assert all(pm.availability_status == "available" for pm in pms)

    # Second Sync Run (Idempotency test: same models returned)
    res2 = await sync_service.sync_credential(db_session, user, cred)
    assert res2.status == "completed"
    assert res2.models_discovered == 2
    assert res2.models_added == 0
    assert res2.models_updated == 2

    # Verify no duplicate ProviderModel rows created
    pms2 = (
        (
            await db_session.execute(
                select(ProviderModel).where(ProviderModel.credential_id == cred.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(pms2) == 2


@pytest.mark.asyncio
async def test_sync_reconciliation_marks_unavailable(
    db_session: AsyncSession,
    sync_env: tuple[ProviderManager, ModelNormalizer, ModelSyncService],
) -> None:
    mgr, normalizer, sync_service = sync_env

    user = User(id=uuid.uuid4(), email=f"recon_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    raw_key = "test-recon-key"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="mock_p2",
        encrypted_api_key=encrypt_api_key(raw_key),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key),
        status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    # Initial run: 2 models returned
    m1 = ProviderRawModel(id="mod-1", provider="mock_p2", name="Mod 1")
    m2 = ProviderRawModel(id="mod-2", provider="mock_p2", name="Mod 2")
    mock_prov = MockSyncProvider("mock_p2", return_models=[m1, m2])
    mgr.register_provider(mock_prov)

    await sync_service.sync_credential(db_session, user, cred)

    # Second run: upstream provider no longer returns mod-2 (only mod-1)
    mock_prov.return_models = [m1]
    res = await sync_service.sync_credential(db_session, user, cred)

    assert res.models_discovered == 1
    assert res.models_marked_unavailable == 1

    # Check database state: mod-2 should be unavailable, mod-1 available
    pm2 = (
        await db_session.execute(
            select(ProviderModel).where(
                ProviderModel.credential_id == cred.id,
                ProviderModel.provider_model_id == "mod-2",
            )
        )
    ).scalar_one()
    assert pm2.availability_status == "unavailable"

    pm1 = (
        await db_session.execute(
            select(ProviderModel).where(
                ProviderModel.credential_id == cred.id,
                ProviderModel.provider_model_id == "mod-1",
            )
        )
    ).scalar_one()
    assert pm1.availability_status == "available"


@pytest.mark.asyncio
async def test_sync_provider_failure_does_not_mark_unavailable(
    db_session: AsyncSession,
    sync_env: tuple[ProviderManager, ModelNormalizer, ModelSyncService],
) -> None:
    mgr, normalizer, sync_service = sync_env

    user = User(id=uuid.uuid4(), email=f"fail_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="mock_p3",
        encrypted_api_key=encrypt_api_key("key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    # First sync: 1 model created
    cred_id = cred.id
    m1 = ProviderRawModel(id="stable-model", provider="mock_p3", name="Stable Model")
    mock_prov = MockSyncProvider("mock_p3", return_models=[m1])
    mgr.register_provider(mock_prov)
    await sync_service.sync_credential(db_session, user, cred)

    # Second sync: provider has an outage
    mock_prov.should_fail = True
    mock_prov.fail_type = "timeout"
    res = await sync_service.sync_credential(db_session, user, cred)

    assert res.status == "failed"
    assert "Network timeout" in (res.error_summary or "")

    # Crucial rule: previously available model must NOT be marked unavailable due to transient failure!
    pm = (
        await db_session.execute(
            select(ProviderModel).where(
                ProviderModel.credential_id == cred_id,
                ProviderModel.provider_model_id == "stable-model",
            )
        )
    ).scalar_one()
    assert pm.availability_status == "available"

    # Audit log check
    log = (
        await db_session.execute(
            select(ModelSyncLog).where(
                ModelSyncLog.credential_id == cred_id,
                ModelSyncLog.status == "failed",
            )
        )
    ).scalar_one()
    assert "Network timeout" in (log.error_summary or "")


@pytest.mark.asyncio
async def test_sync_successful_empty_response_marks_models_unavailable(
    db_session: AsyncSession,
    sync_env: tuple[ProviderManager, ModelNormalizer, ModelSyncService],
) -> None:
    """Verify that a successful empty model response from provider reconciles models as unavailable."""
    mgr, normalizer, sync_service = sync_env

    user = User(id=uuid.uuid4(), email=f"empty_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="mock_empty_prov",
        encrypted_api_key=encrypt_api_key("key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key_empty"),
        status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    # Sync 1: 1 model available
    m1 = ProviderRawModel(
        id="model-to-disappear", provider="mock_empty_prov", name="Disappearing Model"
    )
    mock_prov = MockSyncProvider("mock_empty_prov", return_models=[m1])
    mgr.register_provider(mock_prov)
    res1 = await sync_service.sync_credential(db_session, user, cred)
    assert res1.status == "completed"
    assert res1.models_added == 1

    # Sync 2: Provider returns empty list successfully (e.g. models decommissioned)
    mock_prov.return_models = []
    res2 = await sync_service.sync_credential(db_session, user, cred)
    assert res2.status == "completed"
    assert res2.models_discovered == 0
    assert res2.models_marked_unavailable == 1

    # Model in DB is now marked unavailable
    pm = (
        await db_session.execute(
            select(ProviderModel).where(
                ProviderModel.credential_id == cred.id,
                ProviderModel.provider_model_id == "model-to-disappear",
            )
        )
    ).scalar_one()
    assert pm.availability_status == "unavailable"


@pytest.mark.asyncio
async def test_partial_sync_failure_does_not_abort_successful_providers(
    db_session: AsyncSession,
    sync_env: tuple[ProviderManager, ModelNormalizer, ModelSyncService],
) -> None:
    """Verify partial failure report when one provider fails and another succeeds for the user."""
    mgr, normalizer, sync_service = sync_env

    user = User(id=uuid.uuid4(), email=f"partial_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred_a_id = uuid.uuid4()
    # Cred 1: Provider A (will succeed)
    cred_a = ProviderCredential(
        id=cred_a_id,
        user_id=user.id,
        provider="prov_ok",
        encrypted_api_key=encrypt_api_key("key_a"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key_a"),
        status="active",
    )
    # Cred 2: Provider B (will fail)
    cred_b = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="prov_err",
        encrypted_api_key=encrypt_api_key("key_b"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key_b"),
        status="active",
    )
    db_session.add_all([cred_a, cred_b])
    await db_session.commit()

    mA = ProviderRawModel(id="model-a", provider="prov_ok", name="Model A")
    prov_ok = MockSyncProvider("prov_ok", return_models=[mA], should_fail=False)
    prov_err = MockSyncProvider(
        "prov_err", return_models=[], should_fail=True, fail_type="timeout"
    )
    mgr.register_provider(prov_ok)
    mgr.register_provider(prov_err)

    report = await sync_service.sync_for_user(db_session, user)

    assert report.status == "partial_failure"
    assert len(report.credentials_synced) == 2
    assert report.total_added == 1
    assert len(report.errors) == 1
    assert "prov_err" in report.errors[0]

    # Verify prov_ok model was committed to database despite prov_err failure
    pm_a = (
        await db_session.execute(
            select(ProviderModel).where(
                ProviderModel.credential_id == cred_a_id,
                ProviderModel.provider_model_id == "model-a",
            )
        )
    ).scalar_one()
    assert pm_a.availability_status == "available"
