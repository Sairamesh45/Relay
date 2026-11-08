"""create_phase6_reliability_tables

Revision ID: b7a8ff66e01a
Revises: 4f17b2d73118
Create Date: 2026-11-07 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7a8ff66e01a"
down_revision: str | None = "4f17b2d73118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. credential_healths
    op.create_table(
        "credential_healths",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=False),
        sa.Column(
            "health_status",
            sa.String(length=50),
            server_default="healthy",
            nullable=False,
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_error_category",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            "error_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "credential_id",
            name="uq_credential_health_credential_id",
        ),
    )
    op.create_index(
        op.f("ix_credential_healths_credential_id"),
        "credential_healths",
        ["credential_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_credential_healths_health_status"),
        "credential_healths",
        ["health_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_credential_healths_cooldown_until"),
        "credential_healths",
        ["cooldown_until"],
        unique=False,
    )

    # 2. quota_states
    op.create_table(
        "quota_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("quota_scope", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("limit", sa.BigInteger(), nullable=True),
        sa.Column("remaining", sa.BigInteger(), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.Integer(), nullable=True),
        sa.Column(
            "confidence",
            sa.String(length=50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=100),
            server_default="header",
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_quota_states_credential_id"),
        "quota_states",
        ["credential_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quota_states_provider"),
        "quota_states",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quota_states_quota_scope"),
        "quota_states",
        ["quota_scope"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quota_states_model_id"),
        "quota_states",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quota_states_resource_type"),
        "quota_states",
        ["resource_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quota_states_observed_at"),
        "quota_states",
        ["observed_at"],
        unique=False,
    )

    # 3. circuit_breaker_states
    op.create_table(
        "circuit_breaker_states",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column(
            "state",
            sa.String(length=20),
            server_default="closed",
            nullable=False,
        ),
        sa.Column(
            "failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "success_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_state_change",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "probe_requests_in_flight",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            name="uq_circuit_breaker_scope",
        ),
    )
    op.create_index(
        op.f("ix_circuit_breaker_states_scope_type"),
        "circuit_breaker_states",
        ["scope_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_circuit_breaker_states_scope_id"),
        "circuit_breaker_states",
        ["scope_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_circuit_breaker_states_state"),
        "circuit_breaker_states",
        ["state"],
        unique=False,
    )

    # 4. reliability_events
    op.create_table(
        "reliability_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_reliability_events_timestamp"),
        "reliability_events",
        ["timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reliability_events_event_type"),
        "reliability_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reliability_events_provider"),
        "reliability_events",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reliability_events_credential_id"),
        "reliability_events",
        ["credential_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_reliability_events_model_id"),
        "reliability_events",
        ["model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("reliability_events")
    op.drop_table("circuit_breaker_states")
    op.drop_table("quota_states")
    op.drop_table("credential_healths")
