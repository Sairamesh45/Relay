"""add_performance_and_composite_indexes

Revision ID: c8e12f345678
Revises: efce784a4187
Create Date: 2026-11-08 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e12f345678"
down_revision: str | None = "efce784a4187"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. gateway_request_logs: composite indexes for filtering and LRU routing
    op.create_index(
        "ix_gateway_logs_user_provider_created",
        "gateway_request_logs",
        ["user_id", "provider", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_gateway_logs_user_status_created",
        "gateway_request_logs",
        ["user_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_gateway_logs_user_cred_created",
        "gateway_request_logs",
        ["user_id", "provider_credential_id", "created_at"],
        unique=False,
    )

    # 2. reliability_events: composite indexes for chronological event filtering
    op.create_index(
        "ix_reliability_events_cred_timestamp",
        "reliability_events",
        ["credential_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_reliability_events_prov_timestamp",
        "reliability_events",
        ["provider", "timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_reliability_events_type_timestamp",
        "reliability_events",
        ["event_type", "timestamp"],
        unique=False,
    )

    # 3. quota_states: composite lookup and observation ordering
    op.create_index(
        "ix_quota_states_lookup",
        "quota_states",
        ["credential_id", "provider", "quota_scope", "resource_type", "model_id"],
        unique=False,
    )
    op.create_index(
        "ix_quota_states_cred_observed",
        "quota_states",
        ["credential_id", "observed_at"],
        unique=False,
    )

    # 4. credential_healths: status and update sorting
    op.create_index(
        "ix_credential_healths_status_updated",
        "credential_healths",
        ["health_status", "updated_at"],
        unique=False,
    )

    # 5. provider_credentials: user active status hot path and creation ordering
    op.create_index(
        "ix_provider_credentials_user_status",
        "provider_credentials",
        ["user_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_provider_credentials_user_created",
        "provider_credentials",
        ["user_id", "created_at"],
        unique=False,
    )

    # 6. virtual_api_keys: creation ordering for key management
    op.create_index(
        "ix_virtual_api_keys_user_created",
        "virtual_api_keys",
        ["user_id", "created_at"],
        unique=False,
    )

    # 7. provider_models: candidate discovery and model catalog covering index
    op.create_index(
        "ix_provider_models_cred_avail_unified",
        "provider_models",
        ["credential_id", "availability_status", "unified_model_id"],
        unique=False,
    )


def downgrade() -> None:
    # Drop all created indexes in exact reverse order
    op.drop_index("ix_provider_models_cred_avail_unified", table_name="provider_models")
    op.drop_index("ix_virtual_api_keys_user_created", table_name="virtual_api_keys")
    op.drop_index("ix_provider_credentials_user_created", table_name="provider_credentials")
    op.drop_index("ix_provider_credentials_user_status", table_name="provider_credentials")
    op.drop_index("ix_credential_healths_status_updated", table_name="credential_healths")
    op.drop_index("ix_quota_states_cred_observed", table_name="quota_states")
    op.drop_index("ix_quota_states_lookup", table_name="quota_states")
    op.drop_index("ix_reliability_events_type_timestamp", table_name="reliability_events")
    op.drop_index("ix_reliability_events_prov_timestamp", table_name="reliability_events")
    op.drop_index("ix_reliability_events_cred_timestamp", table_name="reliability_events")
    op.drop_index("ix_gateway_logs_user_cred_created", table_name="gateway_request_logs")
    op.drop_index("ix_gateway_logs_user_status_created", table_name="gateway_request_logs")
    op.drop_index("ix_gateway_logs_user_provider_created", table_name="gateway_request_logs")
