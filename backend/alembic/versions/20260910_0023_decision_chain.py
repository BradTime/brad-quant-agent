"""Add immutable four-layer decision chain.

Revision ID: 20260910_0023
Revises: 20260910_0022
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0023"
down_revision: str | Sequence[str] | None = "20260910_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "decision_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("allocation_decision_id", sa.String(36)),
        sa.Column("protocol_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column(
            "severe_disagreement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "event_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("terminal_event_sha256", sa.String(64)),
        sa.Column("error_code", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
            ["allocation_decision_id"],
            ["portfolio_allocation_decisions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id_snapshot",
            "as_of",
            "request_sha256",
            name="uq_decision_run_user_date_request",
        ),
    )
    op.create_index(
        "ix_decision_runs_user_created",
        "decision_runs",
        ["user_id", "created_at"],
    )
    op.create_table(
        "decision_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64)),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["decision_runs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "run_id",
            "sequence",
            name="uq_decision_event_run_sequence",
        ),
        sa.UniqueConstraint(
            "event_sha256",
            name="uq_decision_event_sha256",
        ),
    )
    op.create_index(
        "ix_decision_events_run_id",
        "decision_events",
        ["run_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_portfolio_allocation_decision()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'portfolio allocation decisions are append-only';
              END IF;
              IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
              ) THEN
                RAISE EXCEPTION 'allocation audit ownership is immutable';
              END IF;
              IF
                NEW.id IS DISTINCT FROM OLD.id OR
                NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot OR
                NEW.regime_snapshot_id IS DISTINCT FROM OLD.regime_snapshot_id OR
                NEW.model_run_id IS DISTINCT FROM OLD.model_run_id OR
                NEW.as_of IS DISTINCT FROM OLD.as_of OR
                NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256 OR
                NEW.output_sha256 IS DISTINCT FROM OLD.output_sha256 OR
                NEW.risk_state IS DISTINCT FROM OLD.risk_state OR
                NEW.payload_json IS DISTINCT FROM OLD.payload_json OR
                NEW.created_at IS DISTINCT FROM OLD.created_at
              THEN
                RAISE EXCEPTION 'portfolio allocation decisions are immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER portfolio_allocation_decisions_immutable
            BEFORE UPDATE OR DELETE ON portfolio_allocation_decisions
            FOR EACH ROW EXECUTE FUNCTION protect_portfolio_allocation_decision()
            """
        )
        op.execute(
            """
            CREATE FUNCTION reject_decision_event_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'decision_events are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER decision_events_append_only
            BEFORE UPDATE OR DELETE ON decision_events
            FOR EACH ROW EXECUTE FUNCTION reject_decision_event_mutation()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_completed_decision_run()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'decision_runs are append-only';
              END IF;
              IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
              ) THEN
                RAISE EXCEPTION 'decision audit ownership is immutable';
              END IF;
              IF OLD.completed_at IS NOT NULL AND (
                NEW.id IS DISTINCT FROM OLD.id OR
                NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot OR
                NEW.as_of IS DISTINCT FROM OLD.as_of OR
                NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256 OR
                NEW.allocation_decision_id IS DISTINCT FROM OLD.allocation_decision_id OR
                NEW.protocol_version IS DISTINCT FROM OLD.protocol_version OR
                NEW.status IS DISTINCT FROM OLD.status OR
                NEW.current_stage IS DISTINCT FROM OLD.current_stage OR
                NEW.severe_disagreement IS DISTINCT FROM OLD.severe_disagreement OR
                NEW.event_count IS DISTINCT FROM OLD.event_count OR
                NEW.terminal_event_sha256 IS DISTINCT FROM OLD.terminal_event_sha256 OR
                NEW.error_code IS DISTINCT FROM OLD.error_code OR
                NEW.created_at IS DISTINCT FROM OLD.created_at OR
                NEW.completed_at IS DISTINCT FROM OLD.completed_at
              ) THEN
                RAISE EXCEPTION 'completed decision_runs are immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER decision_runs_immutable
            BEFORE UPDATE OR DELETE ON decision_runs
            FOR EACH ROW EXECUTE FUNCTION protect_completed_decision_run()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER decision_runs_immutable ON decision_runs"
        )
        op.execute("DROP FUNCTION protect_completed_decision_run()")
        op.execute(
            "DROP TRIGGER decision_events_append_only ON decision_events"
        )
        op.execute("DROP FUNCTION reject_decision_event_mutation()")
        op.execute(
            "DROP TRIGGER portfolio_allocation_decisions_immutable "
            "ON portfolio_allocation_decisions"
        )
        op.execute(
            "DROP FUNCTION protect_portfolio_allocation_decision()"
        )
    op.drop_table("decision_events")
    op.drop_table("decision_runs")
