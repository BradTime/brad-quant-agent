"""Add recoverable prediction training and inference jobs.

Revision ID: 20260911_0027
Revises: 20260911_0026
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260911_0027"
down_revision: str | Sequence[str] | None = "20260911_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "prediction_ops_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requested_by_user_id", sa.String(36)),
        sa.Column(
            "requested_by_user_id_snapshot", sa.String(36), nullable=False
        ),
        sa.Column("job_type", sa.String(24), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column("result_json", PORTABLE_JSON),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_prediction_ops_job_idempotency",
        ),
    )
    op.create_index(
        "ix_prediction_ops_jobs_status_next",
        "prediction_ops_jobs",
        ["status", "next_attempt_at"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_prediction_ops_job()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'prediction ops jobs are append-only';
              END IF;
              IF NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
                AND NOT (
                  OLD.requested_by_user_id IS NOT NULL
                  AND NEW.requested_by_user_id IS NULL
                )
              THEN
                RAISE EXCEPTION 'prediction ops ownership is immutable';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.requested_by_user_id_snapshot IS DISTINCT FROM OLD.requested_by_user_id_snapshot
                OR NEW.job_type IS DISTINCT FROM OLD.job_type
                OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.payload_json IS DISTINCT FROM OLD.payload_json
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
              THEN
                RAISE EXCEPTION 'prediction ops intent is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER prediction_ops_jobs_intent
            BEFORE UPDATE OR DELETE ON prediction_ops_jobs
            FOR EACH ROW EXECUTE FUNCTION protect_prediction_ops_job()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER prediction_ops_jobs_intent "
            "ON prediction_ops_jobs"
        )
        op.execute("DROP FUNCTION protect_prediction_ops_job()")
    op.drop_table("prediction_ops_jobs")
