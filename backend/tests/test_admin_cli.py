"""Secure, idempotent administrator bootstrap CLI."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import cli
from app.db.base import Base
from app.models.admin import AdminPrivilegeAudit
from app.models.user import User
from app.services import admin_bootstrap


@pytest.fixture
def admin_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[User.__table__, AdminPrivilegeAudit.__table__]
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(admin_bootstrap, "SessionLocal", sessions)
    monkeypatch.setattr(admin_bootstrap.settings, "app_env", "dev")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES ('20260902_0013')")
        )
    with sessions.begin() as db:
        db.add_all(
            [
                User(
                    id="verified-user",
                    email="verified@example.com",
                    name="Verified",
                    password_hash="unused",
                    role="user",
                    email_verified_at=datetime.now(UTC),
                    token_version=2,
                ),
                User(
                    id="pending-user",
                    email="pending@example.com",
                    name="Pending",
                    password_hash="unused",
                    role="user",
                    email_verified_at=None,
                ),
            ]
        )
    yield sessions
    engine.dispose()


def test_promote_requires_exact_confirmation_and_verified_account(admin_db):
    with pytest.raises(
        admin_bootstrap.AdminBootstrapError, match="UUID"
    ):
        admin_bootstrap.promote_existing(
            email="verified@example.com",
            expected_user_id="wrong-user",
            expected_environment="dev",
            apply=True,
        )
    with pytest.raises(admin_bootstrap.AdminBootstrapError, match="尚未"):
        admin_bootstrap.promote_existing(
            email="pending@example.com",
            expected_user_id="pending-user",
            expected_environment="dev",
            apply=True,
        )


def test_promote_is_idempotent_and_revokes_existing_sessions(admin_db):
    preview = admin_bootstrap.promote_existing(
        email=" VERIFIED@example.com ",
        expected_user_id="verified-user",
        expected_environment="dev",
        apply=False,
    )
    assert preview["applied"] is False and preview["wouldChange"] is True
    assert preview["currentRole"] == "user"
    assert preview["proposedRole"] == "admin"
    with admin_db() as db:
        assert db.get(User, "verified-user").role == "user"
        assert db.execute(
            select(func.count()).select_from(AdminPrivilegeAudit)
        ).scalar_one() == 0

    first = admin_bootstrap.promote_existing(
        email="verified@example.com",
        expected_user_id="verified-user",
        expected_environment="dev",
        apply=True,
    )
    assert first["changed"] is True
    with admin_db() as db:
        user = db.get(User, "verified-user")
        assert user.role == "admin"
        assert user.token_version == 3

    second = admin_bootstrap.promote_existing(
        email="verified@example.com",
        expected_user_id="verified-user",
        expected_environment="dev",
        apply=True,
    )
    assert second["changed"] is False
    with admin_db() as db:
        assert db.get(User, "verified-user").token_version == 3
        audits = db.execute(select(AdminPrivilegeAudit)).scalars().all()
        assert [audit.changed for audit in audits] == [True, False]
        assert all(audit.target_user_id_snapshot == "verified-user" for audit in audits)


def test_admin_cli_promote_and_list(admin_db, capsys):
    assert (
        cli.main(["admin", "inspect", "--email", "verified@example.com"]) == 0
    )
    inspected = capsys.readouterr().out
    assert "verified-user" in inspected
    assert "verified@example.com" not in inspected

    assert (
        cli.main(
            [
                "admin",
                "promote-existing",
                "--email",
                "verified@example.com",
                "--expected-user-id",
                "verified-user",
                "--expect-environment",
                "dev",
                "--apply",
            ]
        )
        == 0
    )
    applied = capsys.readouterr().out
    assert '"applied": true' in applied
    assert '"currentRole": "user"' in applied
    assert '"proposedRole": "admin"' in applied
    assert cli.main(["admin", "list"]) == 0
    listed = capsys.readouterr().out
    assert "verified@example.com" not in listed
    assert "v*******@example.com" in listed
