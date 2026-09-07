"""Consent, privacy, review, and immutable dataset lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.training import (
    AIGenerationTrace,
    AITrainingFeedback,
    TrainingCandidate,
    TrainingConsent,
    TrainingDataset,
    TrainingDatasetItem,
)
from app.models.user import User
from app.services import training_data, training_dataset
from app.services.training_redaction import (
    RedactionError,
    assert_redacted,
    redact_payload,
)


@pytest.fixture
def training_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        ChatSession.__table__,
        ChatMessage.__table__,
        TrainingConsent.__table__,
        AIGenerationTrace.__table__,
        AITrainingFeedback.__table__,
        TrainingCandidate.__table__,
        TrainingDataset.__table__,
        TrainingDatasetItem.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(training_data, "SessionLocal", sessions)
    monkeypatch.setattr(training_dataset, "SessionLocal", sessions)
    monkeypatch.setattr(
        training_data.settings, "training_artifact_dir", str(tmp_path / "training")
    )
    monkeypatch.setattr(
        training_dataset.settings, "training_artifact_dir", str(tmp_path / "training")
    )
    now = datetime.now(UTC)
    with sessions.begin() as db:
        db.add(
            User(
                id="user-a",
                email="owner@example.com",
                name="Owner",
                password_hash="unused",
                role="user",
                email_verified_at=now,
            )
        )
        db.add(
            User(
                id="admin-a",
                email="admin@example.com",
                name="Admin",
                password_hash="unused",
                role="admin",
                email_verified_at=now,
            )
        )
        db.add(ChatSession(id="session-a", user_id="user-a", title="训练测试"))
        db.add_all(
            [
                ChatMessage(
                    id="message-user",
                    session_id="session-a",
                    user_id="user-a",
                    role="user",
                    content="联系 owner@example.com 查询 600000",
                ),
                ChatMessage(
                    id="message-assistant",
                    session_id="session-a",
                    user_id="user-a",
                    role="assistant",
                    content="回答",
                ),
            ]
        )
    yield sessions, tmp_path
    engine.dispose()


def test_redaction_is_recursive_and_blocks_raw_pii():
    redacted = redact_payload(
        {
            "email": "owner@example.com",
            "text": (
                "电话 13800138000，国际电话 +1 (415) 555-2671，"
                "身份证 11010519491231002X，银行卡 6222 0200 0000 0000，"
                "姓名：张三，北京市朝阳区建国路88号，股票 600000"
            ),
        }
    )
    assert redacted["email"] == "[REDACTED]"
    assert "[PHONE]" in redacted["text"]
    assert "[NATIONAL_ID]" in redacted["text"]
    assert "[PAYMENT_CARD]" in redacted["text"]
    assert "[NAME]" in redacted["text"]
    assert "[ADDRESS]" in redacted["text"]
    assert "600000" in redacted["text"]
    assert_redacted(redacted)
    with pytest.raises(RedactionError):
        assert_redacted("owner@example.com")


def test_consent_feedback_review_dataset_and_revocation(training_db):
    sessions, tmp_path = training_db
    initial = training_data.get_consent("user-a", "session-a")
    assert initial["enabled"] is False
    granted = training_data.set_consent("user-a", "session-a", True)
    assert granted["enabled"] is True

    trace_id = training_data.record_completed_turn(
        user_id="user-a",
        session_id="session-a",
        user_message_id="message-user",
        assistant_message_id="message-assistant",
        input_text="联系 owner@example.com 查询 600000",
        output_text="结果发送到 13800138000",
        tool_trace=[
            {
                "name": "get_quotes",
                "args": {"codes": ["600000.SH"]},
                "result": {"source": "ci_fixture"},
            }
        ],
        model="test-model",
        prompt_version="v1",
        prompt_hash="a" * 64,
        tool_schema_version="b" * 64,
        latency_ms=12,
        consent_requested=True,
        consent_revision=granted["revision"],
    )
    assert trace_id
    with sessions() as db:
        trace = db.get(AIGenerationTrace, trace_id)
        assert "[EMAIL]" in trace.input_text
        assert "[PHONE]" in trace.output_text

    feedback = training_data.submit_feedback(
        "user-a",
        "message-assistant",
        "down",
        ["incorrect"],
        "正确值不是 owner@example.com",
    )
    with pytest.raises(training_data.TrainingDataError, match="理想答案"):
        training_data.review_candidate(
            feedback["candidateId"],
            "admin-a",
            status="approved",
            task_type="grounded-response",
            ideal_answer=None,
            quality_labels=[],
            review_note=None,
        )
    training_data.review_candidate(
        feedback["candidateId"],
        "admin-a",
        status="approved",
        task_type="grounded-response",
        ideal_answer="应仅基于工具结果作答。",
        quality_labels=["human-corrected"],
        review_note="人工修订",
    )

    built = training_dataset.build_dataset("test-v1", "admin-a")
    assert built["trainCount"] + built["validationCount"] == 1
    assert Path(built["artifactDir"], "manifest.json").exists()
    assert training_dataset.dataset_info("test-v1")["checksumOk"] is True
    with pytest.raises(training_data.TrainingDataError, match="不可覆盖"):
        training_dataset.build_dataset("test-v1", "admin-a")
    assert Path(built["artifactDir"], "manifest.json").exists()
    with pytest.raises(training_data.TrainingDataError, match="冻结数据集"):
        training_data.review_candidate(
            feedback["candidateId"],
            "admin-a",
            status="rejected",
            task_type="grounded-response",
            ideal_answer=None,
            quality_labels=[],
            review_note=None,
        )

    training_data.set_consent("user-a", "session-a", False)
    assert not Path(built["artifactDir"]).exists()
    with sessions() as db:
        assert db.get(AIGenerationTrace, trace_id).input_text == ""
        dataset = db.execute(
            select(TrainingDataset).where(TrainingDataset.version == "test-v1")
        ).scalar_one()
        assert dataset.status == "deprecated"
        feedback_row = db.execute(select(AITrainingFeedback)).scalar_one()
        candidate_row = db.execute(select(TrainingCandidate)).scalar_one()
        assert feedback_row.comment is None
        assert feedback_row.issue_labels_json == []
        assert candidate_row.ideal_answer is None
        assert candidate_row.review_note is None
        assert candidate_row.quality_labels_json == []
    removed = training_data.erase_user_data("user-a")
    assert removed["traces"] == 1
    with sessions() as db:
        assert db.get(AIGenerationTrace, trace_id) is None


def test_unowned_session_and_unconsented_feedback_are_rejected(training_db):
    with pytest.raises(training_data.TrainingDataError, match="会话不存在"):
        training_data.get_consent("admin-a", "session-a")
    with pytest.raises(training_data.TrainingDataError, match="未授权"):
        training_data.submit_feedback(
            "user-a", "message-assistant", "up", [], None
        )


def test_consented_failure_keeps_metadata_but_not_partial_output(training_db):
    sessions, _tmp_path = training_db
    trace_id = training_data.record_failed_turn(
        user_id="user-a",
        session_id=None,
        input_text="联系 owner@example.com",
        model="test-model",
        prompt_version="v1",
        prompt_hash="a" * 64,
        tool_schema_version="b" * 64,
        latency_ms=10,
        error_type="TimeoutError",
        consent_requested=True,
        consent_revision=0,
    )
    with sessions() as db:
        trace = db.get(AIGenerationTrace, trace_id)
        assert trace.status == "failed"
        assert trace.output_text == ""
        assert trace.tool_trace_json is None
        assert "[EMAIL]" in trace.input_text


def test_stale_consent_revision_cannot_restore_revoked_capture(training_db):
    granted = training_data.set_consent("user-a", "session-a", True)
    training_data.set_consent("user-a", "session-a", False)
    trace_id = training_data.record_completed_turn(
        user_id="user-a",
        session_id="session-a",
        user_message_id="message-user",
        assistant_message_id="message-assistant",
        input_text="问题",
        output_text="回答",
        tool_trace=[],
        model="test-model",
        prompt_version="v1",
        prompt_hash="a" * 64,
        tool_schema_version="b" * 64,
        latency_ms=1,
        consent_requested=True,
        consent_revision=granted["revision"],
    )
    assert trace_id is None
    assert training_data.get_consent("user-a", "session-a")["enabled"] is False


def test_policy_change_requires_explicit_reconsent(
    training_db, monkeypatch: pytest.MonkeyPatch
):
    granted = training_data.set_consent("user-a", "session-a", True)
    monkeypatch.setattr(
        training_data.settings, "training_consent_policy_version", "next-policy"
    )
    assert (
        training_data.capture_consent_revision(
            "user-a", "session-a", requested=True, is_new=False
        )
        is None
    )
    renewed = training_data.set_consent("user-a", "session-a", True)
    assert renewed["revision"] > granted["revision"]
    assert renewed["policyVersion"] == "next-policy"


def test_interrupted_trace_records_metadata_without_partial_output(monkeypatch):
    from app.api.v1 import ai as ai_api
    from app.services.chat_memory import PreparedChatTurn

    captured = {}
    monkeypatch.setattr(
        ai_api.training_data,
        "record_failed_turn",
        lambda **kwargs: captured.update(kwargs),
    )
    ai_api._record_incomplete_training_trace(
        PreparedChatTurn(
            user_id="user-a",
            session_id="session-a",
            user_content="问题",
            title="问题",
            is_new=False,
        ),
        consent_requested=True,
        consent_revision=3,
        generation_started=0,
        status="interrupted",
        error_type="GeneratorExit",
    )
    assert captured["status"] == "interrupted"
    assert captured["error_type"] == "GeneratorExit"
    assert "output_text" not in captured


def test_same_session_never_crosses_dataset_splits():
    common = {
        "user_id": "user-a",
        "session_id": "session-a",
        "status": "complete",
        "source_type": "chat",
        "input_text": "placeholder",
        "output_text": "answer",
        "model": "model",
        "provider": "deepseek",
        "prompt_version": "v1",
        "prompt_hash": "a" * 64,
        "tool_schema_version": "b" * 64,
        "consent_policy_version": "policy",
    }
    first = AIGenerationTrace(id="trace-a", **common)
    second = AIGenerationTrace(
        id="trace-b",
        **{**common, "input_text": "完全不同的问题 600000"},
    )
    assert training_dataset._stable_split(first) == training_dataset._stable_split(
        second
    )


def test_golden_holdout_question_is_never_exported():
    trace = AIGenerationTrace(
        id="trace-holdout",
        user_id="user-a",
        session_id="session-a",
        status="complete",
        source_type="chat",
        input_text="上证指数现在多少点？涨跌幅多少？",
        output_text="回答",
        tool_trace_json=[],
        model="model",
        provider="deepseek",
        prompt_version="v1",
        prompt_hash="a" * 64,
        tool_schema_version="b" * 64,
        consent_policy_version="policy",
    )
    candidate = TrainingCandidate(
        id="candidate-holdout",
        trace_id=trace.id,
        feedback_id="feedback-holdout",
        status="approved",
        task_type="grounded-response",
        source_type="chat",
        reviewed_by="admin-a",
    )
    feedback = AITrainingFeedback(
        id="feedback-holdout",
        user_id="user-a",
        assistant_message_id="message-a",
        trace_id=trace.id,
        rating="up",
    )
    with pytest.raises(training_data.TrainingDataError, match="holdout"):
        training_dataset._example(candidate, trace, feedback)


def test_dataset_rejects_invalid_or_unlicensed_tool_trace():
    with pytest.raises(training_data.TrainingDataError, match="参数无效"):
        training_dataset._validate_tool_trace(
            [
                {
                    "name": "get_quotes",
                    "args": {"codes": ["600000.SH"], "unexpected": True},
                    "result": {"source": "ci_fixture"},
                }
            ]
        )
    with pytest.raises(training_data.TrainingDataError, match="未批准来源"):
        training_dataset._source_provenance(
            [{"name": "get_quotes", "args": {}, "result": {"source": "unknown"}}]
        )
