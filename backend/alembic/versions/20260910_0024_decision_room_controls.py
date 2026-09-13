"""Add private decision-room controls, MFA, overrides, and notifications.

Revision ID: 20260910_0024
Revises: 20260910_0023
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0024"
down_revision: str | Sequence[str] | None = "20260910_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "user_totp_factors",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True)),
        sa.Column("last_counter", sa.Integer()),
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
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "step_up_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(48), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_step_up_grants_user_expires",
        "step_up_grants",
        ["user_id", "expires_at"],
    )
    op.create_table(
        "totp_recovery_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_totp_recovery_codes_user",
        "totp_recovery_codes",
        ["user_id"],
    )
    op.create_table(
        "step_up_throttles",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column(
            "failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "decision_room_controls",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column(
            "mode",
            sa.String(24),
            nullable=False,
            server_default="research_only",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "decision_overrides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("weights_json", PORTABLE_JSON, nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["decision_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_decision_overrides_run_created",
        "decision_overrides",
        ["run_id", "created_at"],
    )
    op.create_table(
        "decision_room_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("before_json", PORTABLE_JSON, nullable=False),
        sa.Column("after_json", PORTABLE_JSON, nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_decision_room_audits_user_created",
        "decision_room_audits",
        ["user_id", "created_at"],
    )
    op.create_table(
        "decision_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("ws_status", sa.String(16), nullable=False),
        sa.Column("feishu_status", sa.String(16), nullable=False),
        sa.Column(
            "feishu_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "feishu_next_attempt_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column("delivery_token", sa.String(36)),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "user_id_snapshot",
            "event_type",
            "resource_id",
            name="uq_decision_notification_resource_event",
        ),
    )
    op.create_index(
        "ix_decision_notifications_user_created",
        "decision_notifications",
        ["user_id", "created_at"],
    )
    op.create_table(
        "user_artifact_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("path_ciphertext", sa.Text(), nullable=False),
        sa.Column("path_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("claim_started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_user_artifact_deletions_status_next",
        "user_artifact_deletions",
        ["status", "next_attempt_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_decision_override()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'decision overrides are append-only';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.run_id IS DISTINCT FROM OLD.run_id
                OR NEW.action IS DISTINCT FROM OLD.action
                OR NEW.reason IS DISTINCT FROM OLD.reason
                OR NEW.weights_json IS DISTINCT FROM OLD.weights_json
                OR NEW.evidence_sha256 IS DISTINCT FROM OLD.evidence_sha256
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (
                  NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
                  )
                )
              THEN
                RAISE EXCEPTION 'decision overrides are append-only';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER decision_overrides_append_only
            BEFORE UPDATE OR DELETE ON decision_overrides
            FOR EACH ROW EXECUTE FUNCTION protect_decision_override()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_decision_room_audit()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'decision room audits are append-only';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.action IS DISTINCT FROM OLD.action
                OR NEW.reason IS DISTINCT FROM OLD.reason
                OR NEW.before_json IS DISTINCT FROM OLD.before_json
                OR NEW.after_json IS DISTINCT FROM OLD.after_json
                OR NEW.evidence_sha256 IS DISTINCT FROM OLD.evidence_sha256
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (
                  NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
                  )
                )
              THEN
                RAISE EXCEPTION 'decision room audits are append-only';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER decision_room_audits_append_only
            BEFORE UPDATE OR DELETE ON decision_room_audits
            FOR EACH ROW EXECUTE FUNCTION protect_decision_room_audit()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_decision_notification()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'decision notifications are append-only';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.event_type IS DISTINCT FROM OLD.event_type
                OR NEW.severity IS DISTINCT FROM OLD.severity
                OR NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.payload_json IS DISTINCT FROM OLD.payload_json
                OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (
                  NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                    OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
                  )
                )
              THEN
                RAISE EXCEPTION 'decision notifications are append-only';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER decision_notifications_append_only
            BEFORE UPDATE OR DELETE ON decision_notifications
            FOR EACH ROW EXECUTE FUNCTION protect_decision_notification()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER decision_notifications_append_only "
            "ON decision_notifications"
        )
        op.execute("DROP FUNCTION protect_decision_notification()")
        op.execute(
            "DROP TRIGGER decision_overrides_append_only "
            "ON decision_overrides"
        )
        op.execute(
            "DROP TRIGGER decision_room_audits_append_only "
            "ON decision_room_audits"
        )
        op.execute("DROP FUNCTION protect_decision_room_audit()")
        op.execute("DROP FUNCTION protect_decision_override()")
    op.drop_table("decision_notifications")
    op.drop_table("user_artifact_deletions")
    op.drop_table("decision_overrides")
    op.drop_table("decision_room_audits")
    op.drop_table("decision_room_controls")
    op.drop_table("step_up_throttles")
    op.drop_table("totp_recovery_codes")
    op.drop_table("step_up_grants")
    op.drop_table("user_totp_factors")
