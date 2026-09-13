"""Add official EMT simulation bridge and audit stores.

Revision ID: 20260911_0026
Revises: 20260910_0025
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_0026"
down_revision: str | Sequence[str] | None = "20260910_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "broker_filing_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column(
            "professional_eligibility_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "broker_simulation_permission_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "filing_reference_ciphertext", sa.Text(), nullable=False
        ),
        sa.Column(
            "evidence_document_sha256", sa.String(64), nullable=False
        ),
        sa.Column("implementation_sha256", sa.String(64), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36)),
        sa.Column(
            "reviewed_by_user_id_snapshot", sa.String(36), nullable=False
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_broker_filing_profiles_user_id",
        "broker_filing_profiles",
        ["user_id"],
    )
    op.create_table(
        "broker_bindings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("filing_profile_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("account_id_ciphertext", sa.Text(), nullable=False),
        sa.Column("account_id_sha256", sa.String(64), nullable=False),
        sa.Column("strategy_id_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("sdk_version", sa.String(32)),
        sa.Column("bridge_instance_id", sa.String(64)),
        sa.Column(
            "bridge_lease_expires_at", sa.DateTime(timezone=True)
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["filing_profile_id"],
            ["broker_filing_profiles.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "uq_broker_binding_active_user",
        "broker_bindings",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("invalidated_at IS NULL"),
        sqlite_where=sa.text("invalidated_at IS NULL"),
    )
    op.create_index(
        "uq_broker_binding_active_account",
        "broker_bindings",
        ["provider", "account_id_sha256"],
        unique=True,
        postgresql_where=sa.text("invalidated_at IS NULL"),
        sqlite_where=sa.text("invalidated_at IS NULL"),
    )
    op.create_table(
        "broker_rate_windows",
        sa.Column("binding_id", sa.String(36), primary_key=True),
        sa.Column(
            "window_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["broker_bindings.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "broker_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("decision_override_id", sa.String(36)),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("order_type", sa.String(8), nullable=False),
        sa.Column("price", sa.Float()),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("broker_cl_ord_id", sa.String(128)),
        sa.Column("response_ciphertext", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("claim_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_send_started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["broker_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decision_override_id"],
            ["decision_overrides.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id_snapshot",
            "idempotency_key",
            name="uq_broker_order_user_idempotency",
        ),
    )
    op.create_index(
        "ix_broker_orders_status_next",
        "broker_orders",
        ["status", "next_attempt_at"],
    )
    op.create_table(
        "broker_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("broker_order_id", sa.String(36)),
        sa.Column("source_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("payload_ciphertext", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64)),
        sa.Column("event_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["broker_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["broker_order_id"], ["broker_orders.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "binding_id",
            "source_event_id",
            name="uq_broker_event_binding_source",
        ),
    )
    op.create_index(
        "ix_broker_events_binding_id",
        "broker_events",
        ["binding_id"],
    )
    op.create_table(
        "broker_reconciliations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("snapshot_ciphertext", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("mismatch_count", sa.Integer(), nullable=False),
        sa.Column("evidence_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["broker_bindings.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_broker_reconciliations_binding_id",
        "broker_reconciliations",
        ["binding_id"],
    )
    op.create_table(
        "broker_rehearsal_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("sdk_version", sa.String(32), nullable=False),
        sa.Column("implementation_sha256", sa.String(64), nullable=False),
        sa.Column("checks_json", PORTABLE_JSON, nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["broker_bindings.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_broker_rehearsal_runs_binding_id",
        "broker_rehearsal_runs",
        ["binding_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_broker_filing()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'broker filings are append-only';
              END IF;
              IF (NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL))
                OR (NEW.reviewed_by_user_id IS DISTINCT FROM OLD.reviewed_by_user_id AND NOT (
                    OLD.reviewed_by_user_id IS NOT NULL AND NEW.reviewed_by_user_id IS NULL))
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.provider IS DISTINCT FROM OLD.provider
                OR NEW.environment IS DISTINCT FROM OLD.environment
                OR NEW.professional_eligibility_confirmed IS DISTINCT FROM OLD.professional_eligibility_confirmed
                OR NEW.broker_simulation_permission_confirmed IS DISTINCT FROM OLD.broker_simulation_permission_confirmed
                OR NEW.filing_reference_ciphertext IS DISTINCT FROM OLD.filing_reference_ciphertext
                OR NEW.evidence_document_sha256 IS DISTINCT FROM OLD.evidence_document_sha256
                OR NEW.implementation_sha256 IS DISTINCT FROM OLD.implementation_sha256
                OR NEW.reviewed_by_user_id_snapshot IS DISTINCT FROM OLD.reviewed_by_user_id_snapshot
                OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (OLD.invalidated_at IS NOT NULL AND NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at)
              THEN
                RAISE EXCEPTION 'broker filing evidence is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER broker_filing_profiles_immutable
            BEFORE UPDATE OR DELETE ON broker_filing_profiles
            FOR EACH ROW EXECUTE FUNCTION protect_broker_filing()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_broker_binding_identity()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'broker bindings are append-only';
              END IF;
              IF (NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL))
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.filing_profile_id IS DISTINCT FROM OLD.filing_profile_id
                OR NEW.provider IS DISTINCT FROM OLD.provider
                OR NEW.environment IS DISTINCT FROM OLD.environment
                OR NEW.account_id_ciphertext IS DISTINCT FROM OLD.account_id_ciphertext
                OR NEW.account_id_sha256 IS DISTINCT FROM OLD.account_id_sha256
                OR NEW.strategy_id_ciphertext IS DISTINCT FROM OLD.strategy_id_ciphertext
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (OLD.invalidated_at IS NOT NULL AND NEW.invalidated_at IS DISTINCT FROM OLD.invalidated_at)
              THEN
                RAISE EXCEPTION 'broker binding identity is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER broker_bindings_identity
            BEFORE UPDATE OR DELETE ON broker_bindings
            FOR EACH ROW EXECUTE FUNCTION protect_broker_binding_identity()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_broker_order_intent()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'broker orders are append-only';
              END IF;
              IF (NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL))
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
                OR NEW.decision_override_id IS DISTINCT FROM OLD.decision_override_id
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.code IS DISTINCT FROM OLD.code
                OR NEW.side IS DISTINCT FROM OLD.side
                OR NEW.order_type IS DISTINCT FROM OLD.order_type
                OR NEW.price IS DISTINCT FROM OLD.price
                OR NEW.qty IS DISTINCT FROM OLD.qty
                OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
              THEN
                RAISE EXCEPTION 'broker order intent is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER broker_orders_intent
            BEFORE UPDATE OR DELETE ON broker_orders
            FOR EACH ROW EXECUTE FUNCTION protect_broker_order_intent()
            """
        )
        op.execute(
            """
            CREATE FUNCTION reject_broker_audit_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'broker audit evidence is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in (
            "broker_events",
            "broker_reconciliations",
            "broker_rehearsal_runs",
        ):
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_broker_audit_mutation()
                """
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER broker_orders_intent ON broker_orders")
        op.execute("DROP FUNCTION protect_broker_order_intent()")
        op.execute(
            "DROP TRIGGER broker_bindings_identity ON broker_bindings"
        )
        op.execute("DROP FUNCTION protect_broker_binding_identity()")
        op.execute(
            "DROP TRIGGER broker_filing_profiles_immutable "
            "ON broker_filing_profiles"
        )
        op.execute("DROP FUNCTION protect_broker_filing()")
        for table in (
            "broker_rehearsal_runs",
            "broker_reconciliations",
            "broker_events",
        ):
            op.execute(
                f"DROP TRIGGER {table}_append_only ON {table}"
            )
        op.execute("DROP FUNCTION reject_broker_audit_mutation()")
    op.drop_table("broker_rehearsal_runs")
    op.drop_table("broker_reconciliations")
    op.drop_table("broker_events")
    op.drop_table("broker_orders")
    op.drop_table("broker_rate_windows")
    op.drop_table("broker_bindings")
    op.drop_table("broker_filing_profiles")
