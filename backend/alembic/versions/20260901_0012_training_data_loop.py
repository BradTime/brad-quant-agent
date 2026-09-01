"""Add consent-bound AI training data loop.

Revision ID: 20260901_0012
Revises: 20260831_0011
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260901_0012"
down_revision: str | Sequence[str] | None = "20260831_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
PORTABLE_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "training_consents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "session_id", name="uq_training_consent_user_session"
        ),
    )
    op.create_index("ix_training_consents_user_id", "training_consents", ["user_id"])
    op.create_index(
        "ix_training_consents_session_id", "training_consents", ["session_id"]
    )
    op.create_index(
        "ix_training_consents_user_enabled",
        "training_consents",
        ["user_id", "enabled"],
    )

    op.create_table(
        "ai_generation_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("user_message_id", sa.String(36)),
        sa.Column("assistant_message_id", sa.String(36)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=False),
        sa.Column("tool_trace_json", PORTABLE_JSON),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("generation_params_json", PORTABLE_JSON),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("tool_schema_version", sa.String(64), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("estimated_cost", sa.Numeric(14, 6)),
        sa.Column("as_of", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(128)),
        sa.Column("consent_policy_version", sa.String(32), nullable=False),
        sa.Column("redaction_policy_version", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('complete','failed','interrupted')",
            name="ck_ai_generation_traces_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "assistant_message_id", name="uq_ai_generation_trace_assistant_message"
        ),
    )
    for column in (
        "user_id",
        "session_id",
        "user_message_id",
        "assistant_message_id",
        "expires_at",
    ):
        op.create_index(
            f"ix_ai_generation_traces_{column}", "ai_generation_traces", [column]
        )
    op.create_index(
        "ix_ai_generation_traces_user_created",
        "ai_generation_traces",
        ["user_id", "created_at"],
    )

    op.create_table(
        "ai_training_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("assistant_message_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("issue_labels_json", PORTABLE_JSON),
        sa.Column("comment", sa.String(1000)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "rating IN ('up','down')", name="ck_ai_training_feedback_rating"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"], ["ai_generation_traces.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id",
            "assistant_message_id",
            name="uq_ai_training_feedback_user_message",
        ),
    )
    for column in ("user_id", "assistant_message_id", "trace_id"):
        op.create_index(
            f"ix_ai_training_feedback_{column}", "ai_training_feedback", [column]
        )

    op.create_table(
        "training_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("feedback_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("ideal_answer", sa.Text()),
        sa.Column("quality_labels_json", PORTABLE_JSON),
        sa.Column("review_note", sa.String(1000)),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','deprecated')",
            name="ck_training_candidates_status",
        ),
        sa.ForeignKeyConstraint(
            ["trace_id"], ["ai_generation_traces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"], ["ai_training_feedback.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("trace_id", name="uq_training_candidate_trace"),
    )
    op.create_index(
        "ix_training_candidates_trace_id", "training_candidates", ["trace_id"]
    )
    op.create_index(
        "ix_training_candidates_reviewed_by", "training_candidates", ["reviewed_by"]
    )
    op.create_index(
        "ix_training_candidates_status_created",
        "training_candidates",
        ["status", "created_at"],
    )

    op.create_table(
        "training_datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("manifest_json", PORTABLE_JSON),
        sa.Column("checksum_sha256", sa.String(64)),
        sa.Column("artifact_path", sa.String(512)),
        sa.Column("train_count", sa.Integer(), nullable=False),
        sa.Column("validation_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36)),
        sa.Column("frozen_at", sa.DateTime(timezone=True)),
        sa.Column("deprecated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('draft','frozen','deprecated')",
            name="ck_training_datasets_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )

    op.create_table(
        "training_dataset_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=True),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "split IN ('train','validation')",
            name="ck_training_dataset_items_split",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["training_datasets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["training_candidates.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "candidate_id",
            name="uq_training_dataset_candidate",
        ),
    )
    op.create_index(
        "ix_training_dataset_items_dataset_id",
        "training_dataset_items",
        ["dataset_id"],
    )
    op.create_index(
        "ix_training_dataset_items_candidate_id",
        "training_dataset_items",
        ["candidate_id"],
    )


def downgrade() -> None:
    op.drop_table("training_dataset_items")
    op.drop_table("training_datasets")
    op.drop_table("training_candidates")
    op.drop_table("ai_training_feedback")
    op.drop_table("ai_generation_traces")
    op.drop_table("training_consents")
