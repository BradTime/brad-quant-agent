"""Add Champion-Challenger simulation and behavior attribution.

Revision ID: 20260910_0025
Revises: 20260910_0024
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260910_0025"
down_revision: str | Sequence[str] | None = "20260910_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "evolution_programs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_run_id", sa.String(36), nullable=False),
        sa.Column("model_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("model_data_sha256", sa.String(64), nullable=False),
        sa.Column("attestation_key_id", sa.String(32), nullable=False),
        sa.Column("created_by_user_id", sa.String(36)),
        sa.Column(
            "created_by_user_id_snapshot", sa.String(36), nullable=False
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("codes_json", PORTABLE_JSON, nullable=False),
        sa.Column("started_on", sa.Date(), nullable=False),
        sa.Column("stage_started_on", sa.Date(), nullable=False),
        sa.Column("simulation_sessions", sa.Integer(), nullable=False),
        sa.Column("shadow_sessions", sa.Integer(), nullable=False),
        sa.Column("initial_equity", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("peak_equity", sa.Float(), nullable=False),
        sa.Column("holdings_json", PORTABLE_JSON, nullable=False),
        sa.Column("champion_cash", sa.Float(), nullable=False),
        sa.Column("champion_equity", sa.Float(), nullable=False),
        sa.Column("champion_holdings_json", PORTABLE_JSON, nullable=False),
        sa.Column("metrics_json", PORTABLE_JSON, nullable=False),
        sa.Column("claim_token", sa.String(36)),
        sa.Column("claim_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_signal_date", sa.Date()),
        sa.Column("failure_reason", sa.String(128)),
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
            ["model_run_id"],
            ["prediction_model_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "stage IN ('simulation','shadow','eligible_for_small_capital',"
            "'degraded','failed','paused')",
            name="ck_evolution_program_stage",
        ),
        sa.UniqueConstraint(
            "model_run_id",
            name="uq_evolution_program_model_run",
        ),
    )
    op.create_index(
        "ix_evolution_programs_stage_updated",
        "evolution_programs",
        ["stage", "updated_at"],
    )
    op.create_table(
        "evolution_signal_commitments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("program_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("label_date", sa.Date(), nullable=False),
        sa.Column(
            "model_artifact_sha256", sa.String(64), nullable=False
        ),
        sa.Column(
            "universe_membership_sha256", sa.String(64), nullable=False
        ),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "attestation_sha256", sa.String(64), nullable=False
        ),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["program_id"], ["evolution_programs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "program_id",
            "signal_date",
            name="uq_evolution_commitment_program_signal",
        ),
    )
    op.create_index(
        "ix_evolution_signal_commitments_program_id",
        "evolution_signal_commitments",
        ["program_id"],
    )
    op.create_table(
        "evolution_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("commitment_id", sa.String(36), nullable=False, unique=True),
        sa.Column("program_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("label_date", sa.Date(), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=False),
        sa.Column("equity", sa.Float(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "attestation_sha256", sa.String(64), nullable=False
        ),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["program_id"], ["evolution_programs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["commitment_id"],
            ["evolution_signal_commitments.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "program_id",
            "signal_date",
            name="uq_evolution_observation_program_signal",
        ),
    )
    op.create_index(
        "ix_evolution_observations_program_id",
        "evolution_observations",
        ["program_id"],
    )
    op.create_table(
        "evolution_transitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("program_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("from_stage", sa.String(32), nullable=False),
        sa.Column("to_stage", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("metrics_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("previous_transition_sha256", sa.String(64)),
        sa.Column(
            "attestation_sha256", sa.String(64), nullable=False
        ),
        sa.Column("payload_json", PORTABLE_JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["program_id"], ["evolution_programs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "program_id",
            "sequence",
            name="uq_evolution_transition_program_sequence",
        ),
    )
    op.create_index(
        "ix_evolution_transitions_program_id",
        "evolution_transitions",
        ["program_id"],
    )
    op.create_table(
        "behavior_attributions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("override_id", sa.String(36), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36)),
        sa.Column("user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("label_date", sa.Date(), nullable=False),
        sa.Column("strategy_return", sa.Float(), nullable=False),
        sa.Column("human_return", sa.Float(), nullable=False),
        sa.Column("return_delta", sa.Float(), nullable=False),
        sa.Column("behavior_json", PORTABLE_JSON, nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["override_id"], ["decision_overrides.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_table(
        "behavior_attribution_attempts",
        sa.Column("override_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["override_id"], ["decision_overrides.id"], ondelete="RESTRICT"
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_evolution_evidence_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'evolution evidence is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in (
            "evolution_signal_commitments",
            "evolution_observations",
            "evolution_transitions",
        ):
            op.execute(
                f"""
                CREATE TRIGGER {table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_evolution_evidence_mutation()
                """
            )
        op.execute(
            """
            CREATE FUNCTION protect_behavior_attribution()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'behavior attribution is append-only';
              END IF;
              IF NEW.user_id IS DISTINCT FROM OLD.user_id AND NOT (
                OLD.user_id IS NOT NULL AND NEW.user_id IS NULL
              ) THEN
                RAISE EXCEPTION 'behavior attribution ownership is immutable';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.override_id IS DISTINCT FROM OLD.override_id
                OR NEW.user_id_snapshot IS DISTINCT FROM OLD.user_id_snapshot
                OR NEW.signal_date IS DISTINCT FROM OLD.signal_date
                OR NEW.label_date IS DISTINCT FROM OLD.label_date
                OR NEW.strategy_return IS DISTINCT FROM OLD.strategy_return
                OR NEW.human_return IS DISTINCT FROM OLD.human_return
                OR NEW.return_delta IS DISTINCT FROM OLD.return_delta
                OR NEW.behavior_json IS DISTINCT FROM OLD.behavior_json
                OR NEW.evidence_sha256 IS DISTINCT FROM OLD.evidence_sha256
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
              THEN
                RAISE EXCEPTION 'behavior attribution is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER behavior_attributions_append_only
            BEFORE UPDATE OR DELETE ON behavior_attributions
            FOR EACH ROW EXECUTE FUNCTION protect_behavior_attribution()
            """
        )
        op.execute(
            """
            CREATE FUNCTION protect_evolution_program_identity()
            RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'evolution programs are append-only';
              END IF;
              IF NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
                AND NOT (
                  OLD.created_by_user_id IS NOT NULL
                  AND NEW.created_by_user_id IS NULL
                )
              THEN
                RAISE EXCEPTION 'evolution program ownership is immutable';
              END IF;
              IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.model_run_id IS DISTINCT FROM OLD.model_run_id
                OR NEW.model_artifact_sha256 IS DISTINCT FROM OLD.model_artifact_sha256
                OR NEW.model_data_sha256 IS DISTINCT FROM OLD.model_data_sha256
                OR NEW.attestation_key_id IS DISTINCT FROM OLD.attestation_key_id
                OR NEW.created_by_user_id_snapshot IS DISTINCT FROM OLD.created_by_user_id_snapshot
                OR NEW.codes_json IS DISTINCT FROM OLD.codes_json
                OR NEW.started_on IS DISTINCT FROM OLD.started_on
                OR NEW.initial_equity IS DISTINCT FROM OLD.initial_equity
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
              THEN
                RAISE EXCEPTION 'evolution program identity is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER evolution_programs_identity
            BEFORE UPDATE OR DELETE ON evolution_programs
            FOR EACH ROW EXECUTE FUNCTION protect_evolution_program_identity()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER evolution_programs_identity "
            "ON evolution_programs"
        )
        op.execute("DROP FUNCTION protect_evolution_program_identity()")
        op.execute(
            "DROP TRIGGER behavior_attributions_append_only "
            "ON behavior_attributions"
        )
        op.execute("DROP FUNCTION protect_behavior_attribution()")
        for table in (
            "evolution_transitions",
            "evolution_observations",
            "evolution_signal_commitments",
        ):
            op.execute(
                f"DROP TRIGGER {table}_append_only ON {table}"
            )
        op.execute("DROP FUNCTION reject_evolution_evidence_mutation()")
    op.drop_table("behavior_attributions")
    op.drop_table("behavior_attribution_attempts")
    op.drop_table("evolution_transitions")
    op.drop_table("evolution_observations")
    op.drop_table("evolution_signal_commitments")
    op.drop_table("evolution_programs")
