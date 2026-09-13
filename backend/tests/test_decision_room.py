from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import security
from app.core.json_payload import dump_envelope
from app.models.decision import DecisionEvent, DecisionRun
from app.models.prediction import (
    PortfolioAllocationDecision,
    PortfolioRiskProfile,
    PredictionModelRun,
    RegimeSnapshot,
)
from app.models.room import (
    DecisionNotification,
    DecisionOverride,
    DecisionRoomAudit,
    DecisionRoomControl,
    StepUpGrant,
    StepUpThrottle,
    TotpRecoveryCode,
    UserArtifactDeletion,
    UserTotpFactor,
)
from app.models.user import User
from app.services import (
    artifact_deletion,
    decision_notifications,
    decision_room,
    step_up,
)


@pytest.fixture
def room_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = (
        User.__table__,
        PredictionModelRun.__table__,
        RegimeSnapshot.__table__,
        PortfolioAllocationDecision.__table__,
        DecisionRun.__table__,
        DecisionEvent.__table__,
        PortfolioRiskProfile.__table__,
        UserTotpFactor.__table__,
        StepUpGrant.__table__,
        StepUpThrottle.__table__,
        TotpRecoveryCode.__table__,
        DecisionRoomControl.__table__,
        DecisionRoomAudit.__table__,
        DecisionOverride.__table__,
        DecisionNotification.__table__,
        UserArtifactDeletion.__table__,
    )
    for table in tables:
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    for module in (
        step_up,
        decision_room,
        decision_notifications,
        artifact_deletion,
    ):
        monkeypatch.setattr(module, "SessionLocal", sessions)
    user = User(
        id="user-a",
        email="a@example.com",
        name="A",
        password_hash=security.hash_password("strong-password"),
        token_version=0,
    )
    with sessions.begin() as session:
        session.add(user)
    yield sessions, user
    engine.dispose()


def test_totp_step_up_is_purpose_bound_single_use_and_replay_safe(
    room_db, monkeypatch
):
    sessions, user = room_db
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(step_up, "_now", lambda: now)
    enrolled = step_up.enroll("user-a", "strong-password")
    counter = int(now.timestamp()) // 30
    code = step_up._code(enrolled["secret"], counter)
    assert step_up.confirm("user-a", code)["enabled"] is True

    now += timedelta(seconds=30)
    grant_code = step_up._code(
        enrolled["secret"], int(now.timestamp()) // 30
    )
    grant = step_up.create_grant(
        "user-a",
        password="strong-password",
        code=grant_code,
        purpose="release_kill_switch",
    )
    with sessions.begin() as session:
        locked_user = session.get(User, "user-a")
        step_up.consume(
            session,
            user=locked_user,
            token=grant["token"],
            purpose="release_kill_switch",
        )
    with sessions.begin() as session:
        with pytest.raises(ValueError, match="已使用或过期"):
            step_up.consume(
                session,
                user=session.get(User, "user-a"),
                token=grant["token"],
                purpose="release_kill_switch",
            )
    with pytest.raises(ValueError, match="密码或动态验证码错误"):
        step_up.create_grant(
            "user-a",
            password="wrong-password",
            code=grant_code,
            purpose="change_decision_mode",
        )
    recovery_grant = step_up.create_grant(
        "user-a",
        password="strong-password",
        code=None,
        recovery_code=enrolled["recoveryCodes"][0],
        purpose="reset_totp",
    )
    assert step_up.reset_factor(
        user, token=recovery_grant["token"]
    ) == {
        "enabled": False,
        "reset": True,
        "tokensRevoked": True,
    }


def _seed_decision(sessions):
    inputs = {
        "riskProfile": {
            "capitalLimit": 200_000,
            "leverageLimit": 200_000,
        },
        "industries": {"600000.SH": "银行"},
        "predictions": [
            {
                "code": "600000.SH",
                "returnInterval80": {"low": -0.02},
            }
        ],
    }
    output = {"weights": {"600000.SH": 0.2}}
    risk_inputs = {}
    risk_output = {
        "veto": False,
        "approvedCandidateWeights": {"600000.SH": 0.2},
        "executionApproved": False,
    }
    with sessions.begin() as session:
        session.add(
            PredictionModelRun(
                id="model-1",
                user_id="user-a",
                version="v1",
                provider="lightgbm",
                status="champion",
                feature_schema_version="daily-pit-v1",
                data_sha256="d" * 64,
                artifact_path="/artifact",
                artifact_sha256="a" * 64,
                metrics_json=dump_envelope({}),
                training_start=date(2023, 1, 1),
                training_end=date(2026, 1, 1),
                is_champion=True,
            )
        )
        session.add(
            RegimeSnapshot(
                id="regime-1",
                user_id="user-a",
                user_id_snapshot="user-a",
                as_of=date(2026, 9, 9),
                regime="bull",
                rules_version="regime-rules-v1",
                input_sha256="r" * 64,
                payload_json=dump_envelope({}),
            )
        )
        session.add(
            PortfolioRiskProfile(
                user_id="user-a",
                capital_limit=200_000,
                leverage_limit=200_000,
                high_water_mark=200_000,
                kill_switch_active=False,
            )
        )
        session.flush()
        allocation = PortfolioAllocationDecision(
            id="allocation-1",
            user_id="user-a",
            user_id_snapshot="user-a",
            regime_snapshot_id="regime-1",
            model_run_id="model-1",
            as_of=date(2026, 9, 9),
            input_sha256=decision_room._hash(inputs),
            output_sha256=decision_room._hash(output),
            risk_state="normal",
            payload_json=dump_envelope(
                {"input": inputs, "output": output}
            ),
        )
        session.add(allocation)
        session.add(
            DecisionRun(
                id="run-1",
                user_id="user-a",
                user_id_snapshot="user-a",
                as_of=date(2026, 9, 9),
                request_sha256="q" * 64,
                allocation_decision_id="allocation-1",
                protocol_version="decision-chain-v1",
                status="approved_candidate",
                current_stage="risk_officer",
                severe_disagreement=False,
                event_count=6,
                terminal_event_sha256="t" * 64,
                completed_at=datetime.now(UTC),
            )
        )
        session.add(
            DecisionEvent(
                id="event-6",
                run_id="run-1",
                sequence=6,
                stage="risk_officer",
                actor="risk_officer",
                input_sha256=decision_room._hash(risk_inputs),
                output_sha256=decision_room._hash(risk_output),
                previous_event_sha256="p" * 64,
                event_sha256="t" * 64,
                payload_json=dump_envelope(
                    {
                        "input": risk_inputs,
                        "output": risk_output,
                    }
                ),
            )
        )


def test_room_controls_require_step_up_and_never_approve_execution(
    room_db, monkeypatch
):
    sessions, user = room_db
    _seed_decision(sessions)
    monkeypatch.setattr(
        decision_room.step_up, "consume", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        decision_notifications,
        "emit",
        lambda *args, **kwargs: {"id": "notification-1"},
    )
    changed = decision_room.change_mode(
        user,
        mode="manual_review",
        reason="进入人工复核模式进行审慎评估",
        step_up_token="token",
    )
    assert changed["executionEnabled"] is False
    override = decision_room.override(
        user,
        run_id="run-1",
        action="modify",
        reason="降低单票仓位以响应反证官的尾部风险",
        weights={"600000.SH": 0.1},
        step_up_token="token",
    )
    assert override["executionApproved"] is False
    killed = decision_room.activate_kill_switch(
        "user-a", reason="发现异常风险需要立即停止新增动作"
    )
    assert killed["killSwitchActive"] is True
    with pytest.raises(ValueError, match="只允许拒绝"):
        decision_room.override(
            user,
            run_id="run-1",
            action="accept",
            reason="尝试在风控暂停后继续接受研究候选",
            weights=None,
            step_up_token="token",
        )
    with sessions() as session:
        assert session.scalar(select(DecisionOverride)) is not None
        assert (
            session.execute(select(DecisionRoomAudit)).scalars().all()
        )


def test_notification_is_redacted_deduplicated_and_hash_verified(
    room_db, monkeypatch
):
    monkeypatch.setattr(
        decision_notifications,
        "notify_user_threadsafe",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        decision_notifications.settings,
        "feishu_webhook_url",
        "",
    )
    first = decision_notifications.emit(
        "user-a",
        event_type="decision.risk_veto",
        resource_id="run-1",
        message="风险官否决，请复核。",
    )
    second = decision_notifications.emit(
        "user-a",
        event_type="decision.risk_veto",
        resource_id="run-1",
        message="不应覆盖第一次通知。",
    )
    assert first["deduplicated"] is False
    assert second["deduplicated"] is True
    items = decision_notifications.list_for_user("user-a")
    assert len(items) == 1
    assert items[0]["eventType"] == "decision.risk_veto"
    assert "600000" not in str(items[0])


def test_artifact_deletion_outbox_survives_commit_boundary(
    room_db, monkeypatch, tmp_path
):
    sessions, _ = room_db
    root = tmp_path / "training"
    dataset = root / "dataset-1"
    dataset.mkdir(parents=True)
    artifact = dataset / "items.jsonl"
    artifact.write_text("sensitive", encoding="utf-8")
    monkeypatch.setattr(
        artifact_deletion.settings,
        "training_artifact_dir",
        str(root),
    )
    with sessions.begin() as session:
        ids = artifact_deletion.enqueue(
            session,
            user_id="user-a",
            paths=[str(artifact)],
        )
    assert artifact.exists()
    assert artifact_deletion.process(ids[0]) is True
    assert not dataset.exists()
    with sessions() as session:
        row = session.get(UserArtifactDeletion, ids[0])
        assert row.status == "completed"
        assert row.path_ciphertext == ""
