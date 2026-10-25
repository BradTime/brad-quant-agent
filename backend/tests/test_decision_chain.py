from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.json_payload import dump_envelope
from app.decision import protocol
from app.models.decision import DecisionEvent, DecisionRun
from app.models.prediction import (
    PortfolioAllocationDecision,
    PredictionModelRun,
    RegimeSnapshot,
)
from app.models.user import User
from app.services import decision_chain


def _inputs(code: str = "600000.SH") -> dict:
    return {
        "account": {"totalAssets": 200_000},
        "positions": [],
        "industries": {code: "银行"},
        "riskProfile": {
            "capitalLimit": 200_000,
            "leverageLimit": 200_000,
            "highWaterMark": 200_000,
            "killSwitchActive": False,
        },
        "regime": {
            "regime": "bull",
            "universeMembershipSha256": "u" * 64,
        },
        "predictions": [
            {
                "code": code,
                "signalDate": "2026-09-09",
                "probabilityUp": 0.72,
                "returnInterval80": {
                    "low": -0.01,
                    "median": 0.03,
                    "high": 0.06,
                },
                "featureSha256": "f" * 64,
                "model": {
                    "runId": "model-1",
                    "artifactSha256": "a" * 64,
                },
            }
        ],
    }


def _allocation(code: str = "600000.SH") -> dict:
    return {
        "weights": {code: 0.2},
        "amounts": {code: 40_000},
        "grossExposure": 0.2,
        "predictedDailyLoss": 0.002,
        "riskState": "normal",
        "reasons": [],
        "limits": {
            "grossExposure": 2.0,
            "singleName": 0.2,
            "industry": 0.3,
            "strategyRisk": 0.25,
            "predictedDailyLoss": 0.02,
        },
        "authoritative": True,
        "executionApproved": False,
    }


def test_protocol_enforces_blind_review_two_rounds_and_risk_veto():
    research = protocol.researcher(_inputs(), _allocation())
    contrarian = protocol.contrarian_blind(_inputs())
    assert contrarian["blindReview"] is True
    assert contrarian["receivedResearcherClaim"] is False
    first = protocol.cross_examine(
        research, contrarian, round_number=1
    )
    second = protocol.cross_examine(
        research, contrarian, round_number=2
    )
    with pytest.raises(ValueError, match="完整两轮"):
        protocol.investment_committee(
            research, contrarian, [first]
        )
    committee = protocol.investment_committee(
        research, contrarian, [first, second]
    )
    risk = protocol.risk_officer(
        committee,
        {**_allocation(), "riskState": "force_reduce"},
    )
    assert risk["veto"] is True
    assert risk["executionApproved"] is False
    invalid = _inputs()
    invalid["predictions"][0]["probabilityUp"] = 1.2
    with pytest.raises(ValueError, match="概率越界"):
        protocol.researcher(invalid, _allocation())


@pytest.fixture
def decision_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        PredictionModelRun.__table__,
        RegimeSnapshot.__table__,
        PortfolioAllocationDecision.__table__,
        DecisionRun.__table__,
        DecisionEvent.__table__,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(decision_chain, "SessionLocal", sessions)
    with sessions.begin() as session:
        session.add(
            User(
                id="user-a",
                email="a@example.com",
                name="A",
                password_hash="x",
            )
        )
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
    calls = {"count": 0}

    def fake_allocation(user_id, *, requested_codes, as_of):
        calls["count"] += 1
        decision_id = f"allocation-{calls['count']}"
        code = requested_codes[0]
        inputs = _inputs(code)
        allocation = _allocation(code)
        with sessions.begin() as session:
            session.add(
                PortfolioAllocationDecision(
                    id=decision_id,
                    user_id=user_id,
                    user_id_snapshot=user_id,
                    regime_snapshot_id="regime-1",
                    model_run_id="model-1",
                    as_of=as_of,
                    input_sha256=decision_chain._hash(inputs),
                    output_sha256=decision_chain._hash(allocation),
                    risk_state="normal",
                    payload_json=dump_envelope(
                        {
                            "input": inputs,
                            "output": allocation,
                        }
                    ),
                )
            )
        return {"decisionId": decision_id}

    monkeypatch.setattr(
        decision_chain.authoritative_allocation,
        "preview",
        fake_allocation,
    )
    yield sessions, calls
    engine.dispose()


def test_decision_chain_is_idempotent_tenant_scoped_and_hash_linked(
    decision_db,
):
    sessions, calls = decision_db
    result = decision_chain.run(
        "user-a",
        codes=["600000.SH"],
        as_of=date(2026, 9, 9),
    )
    repeated = decision_chain.run(
        "user-a",
        codes=["600000.SH"],
        as_of=date(2026, 9, 9),
    )

    assert repeated["id"] == result["id"]
    assert calls["count"] == 1
    assert len(result["events"]) == 6
    assert result["events"][1]["output"]["blindReview"] is True
    assert result["events"][-1]["output"]["executionApproved"] is False
    previous = None
    for event in result["events"]:
        assert event["previousEventSha256"] == previous
        previous = event["eventSha256"]
    with pytest.raises(ValueError, match="不存在"):
        decision_chain.get("user-b", result["id"])

    with sessions.begin() as session:
        event = session.execute(
            select(DecisionEvent).where(
                DecisionEvent.run_id == result["id"],
                DecisionEvent.sequence == 1,
            )
        ).scalar_one()
        event.payload_json = dump_envelope(
            {"input": {}, "output": {"tampered": True}}
        )
    with pytest.raises(RuntimeError, match="Hash 校验失败"):
        decision_chain.get("user-a", result["id"])


def test_failed_chain_can_retry_without_parallel_run(
    decision_db, monkeypatch
):
    sessions, calls = decision_db
    original = decision_chain.authoritative_allocation.preview
    failures = {"remaining": 1}

    def flaky(*args, **kwargs):
        if failures["remaining"]:
            failures["remaining"] -= 1
            raise ValueError("evidence unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        decision_chain.authoritative_allocation, "preview", flaky
    )
    with pytest.raises(ValueError, match="evidence unavailable"):
        decision_chain.run(
            "user-a",
            codes=["600001.SH"],
            as_of=date(2026, 9, 9),
        )
    result = decision_chain.run(
        "user-a",
        codes=["600001.SH"],
        as_of=date(2026, 9, 9),
    )
    assert result["status"] in {"approved_candidate", "vetoed"}
    with sessions() as session:
        assert (
            session.scalar(select(DecisionRun).where(
                DecisionRun.request_sha256
                == decision_chain._request_hash(["600001.SH"])
            ))
            is not None
        )
    assert calls["count"] == 1


def test_deleted_audit_tail_is_detected(decision_db):
    sessions, _ = decision_db
    result = decision_chain.run(
        "user-a",
        codes=["600000.SH"],
        as_of=date(2026, 9, 9),
    )
    with sessions.begin() as session:
        tail = session.execute(
            select(DecisionEvent).where(
                DecisionEvent.run_id == result["id"],
                DecisionEvent.sequence == 6,
            )
        ).scalar_one()
        session.delete(tail)
    with pytest.raises(RuntimeError, match="数量"):
        decision_chain.get("user-a", result["id"])
