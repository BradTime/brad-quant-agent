"""Add administrator privilege audit and role constraint.

Revision ID: 20260902_0013
Revises: 20260901_0012
Create Date: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260902_0013"
down_revision: str | Sequence[str] | None = "20260901_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not op.get_context().as_sql:
        connection = op.get_bind()
        invalid = connection.execute(
            sa.text(
                "SELECT role FROM users "
                "WHERE role NOT IN ('user','vip','admin') LIMIT 1"
            )
        ).scalar_one_or_none()
        if invalid is not None:
            raise RuntimeError("users.role contains a value outside user/vip/admin")

    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint(
            "ck_users_role_allowed",
            "role IN ('user','vip','admin')",
        )

    op.create_table(
        "admin_privilege_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("target_user_id", sa.String(36)),
        sa.Column("target_user_id_snapshot", sa.String(36), nullable=False),
        sa.Column("prior_role", sa.String(16), nullable=False),
        sa.Column("new_role", sa.String(16), nullable=False),
        sa.Column("changed", sa.Boolean(), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_admin_privilege_audits_target_user_id",
        "admin_privilege_audits",
        ["target_user_id"],
    )
    op.create_index(
        "ix_admin_privilege_audits_target_created",
        "admin_privilege_audits",
        ["target_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("admin_privilege_audits")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role_allowed", type_="check")
