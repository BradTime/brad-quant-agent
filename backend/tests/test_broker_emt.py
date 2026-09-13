from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.broker.base import BrokerOrderRequest
from app.broker.emt import OfficialEmtAdapter, to_emt_symbol
from app.core import security
from app.models.broker import (
    BrokerBinding,
    BrokerEvent,
    BrokerFilingProfile,
    BrokerOrder,
    BrokerRateWindow,
    BrokerReconciliation,
    BrokerRehearsalRun,
)
from app.models.prediction import PortfolioRiskProfile
from app.models.user import User
from app.services import broker_gateway


class FakeSdk:
    __version__ = "3.0.999"
    OrderSide_Buy = 1
    OrderSide_Sell = 2
    OrderType_Limit = 1
    OrderType_Market = 2
    PositionEffect_Open = 1
    PositionEffect_Close = 2
    OrderStatus_New = 1
    OrderStatus_PartiallyFilled = 2
    OrderStatus_Filled = 3
    OrderStatus_Canceled = 5
    OrderStatus_Rejected = 8

    def __init__(self):
        self.submissions = []

    def order_volume(self, **kwargs):
        self.submissions.append(kwargs)
        return [
            {
                "account_id": kwargs["account"],
                "cl_ord_id": "emt-order-1",
                "status": self.OrderStatus_New,
                "symbol": kwargs["symbol"],
                "volume": kwargs["volume"],
            }
        ]

    def order_cancel(self, **kwargs):
        return kwargs["wait_cancel_orders"]

    def get_cash(self, account_id=None):
        return {"account_id": account_id, "nav": 200_000, "available": 180_000}

    def get_position(self, account_id=None):
        return []

    def get_orders(self):
        if not self.submissions:
            return []
        return [
            {
                "account_id": "sim-account",
                "cl_ord_id": "emt-order-1",
                "status": self.OrderStatus_Filled,
                "filled_volume": 100,
                "updated_at": "2026-09-11T10:00:00+08:00",
            }
        ]

    def get_execution_reports(self):
        if not self.submissions:
            return []
        return [
            {
                "account_id": "sim-account",
                "cl_ord_id": "emt-order-1",
                "exec_id": "execution-1",
                "volume": 100,
            }
        ]

    def timer(self, **kwargs):
        return {"timer_status": 0, "timer_id": 1}

    def run(self, **kwargs):
        return kwargs

    def set_token(self, token):
        return token


def test_official_emt_adapter_uses_documented_sdk_contract():
    sdk = FakeSdk()
    adapter = OfficialEmtAdapter(sdk)
    result = adapter.submit_order(
        BrokerOrderRequest(
            client_order_id="local-1",
            symbol="600000.SH",
            side="buy",
            order_type="limit",
            qty=100,
            price=10.0,
            account_id="sim-account",
        )
    )
    assert to_emt_symbol("600000.SH") == "SHSE.600000"
    assert result["cl_ord_id"] == "emt-order-1"
    assert result["_normalizedStatus"] == "acked"
    assert sdk.submissions[0]["position_effect"] == sdk.PositionEffect_Open


@pytest.fixture
def broker_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        User.__table__,
        BrokerFilingProfile.__table__,
        BrokerBinding.__table__,
        BrokerRateWindow.__table__,
        BrokerOrder.__table__,
        BrokerEvent.__table__,
        BrokerReconciliation.__table__,
        BrokerRehearsalRun.__table__,
        PortfolioRiskProfile.__table__,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(broker_gateway, "SessionLocal", sessions)
    monkeypatch.setattr(broker_gateway.settings, "emt_enabled", True)
    monkeypatch.setattr(
        broker_gateway.settings, "emt_account_id", "sim-account"
    )
    monkeypatch.setattr(
        broker_gateway.settings, "emt_strategy_id", "emt-strategy"
    )
    monkeypatch.setattr(
        broker_gateway.settings,
        "emt_simulation_confirmation",
        "I_HAVE_SELECTED_EASTMONEY_SIMULATION_ACCOUNT",
    )
    monkeypatch.setattr(
        broker_gateway.step_up, "consume", lambda *args, **kwargs: None
    )
    user = User(
        id="user-a",
        email="a@example.com",
        name="A",
        password_hash=security.hash_password("strong-password"),
        role="user",
    )
    admin = User(
        id="admin-a",
        email="admin@example.com",
        name="Admin",
        password_hash=security.hash_password("strong-password"),
        role="admin",
    )
    with sessions.begin() as session:
        session.add_all([user, admin])
        session.add(
            PortfolioRiskProfile(
                user_id="user-a",
                capital_limit=200_000,
                leverage_limit=200_000,
                high_water_mark=200_000,
                kill_switch_active=False,
            )
        )
    yield sessions, user
    engine.dispose()


def test_gateway_is_idempotent_at_most_once_and_reconciles(
    broker_db,
):
    sessions, user = broker_db
    filing = broker_gateway.register_filing(
        user_id=user.id,
        reviewed_by_user_id="admin-a",
        filing_reference="simulation-filing-2026",
        evidence_document_sha256="a" * 64,
        professional_eligibility_confirmed=True,
        broker_simulation_permission_confirmed=True,
    )
    binding = broker_gateway.bind_simulation(
        user_id=user.id,
        filing_profile_id=filing["id"],
        account_id="sim-account",
        strategy_id="emt-strategy",
    )
    adapter = OfficialEmtAdapter(FakeSdk())
    broker_gateway.claim_bridge(
        binding["id"],
        instance_id="bridge-1",
        sdk_version=adapter.sdk_version,
    )
    first = broker_gateway.enqueue_rehearsal_order(
        user=user,
        binding_id=binding["id"],
        idempotency_key="rehearsal-order-1",
        code="600000.SH",
        side="buy",
        qty=100,
        limit_price=10,
        step_up_token="step-up-token",
    )
    repeated = broker_gateway.enqueue_rehearsal_order(
        user=user,
        binding_id=binding["id"],
        idempotency_key="rehearsal-order-1",
        code="600000.SH",
        side="buy",
        qty=100,
        limit_price=10,
        step_up_token="step-up-token",
    )
    assert repeated["id"] == first["id"]

    assert first["status"] == "blocked_account_type"
    with pytest.raises(ValueError, match="仿真账户类型"):
        broker_gateway.process_one(
            binding["id"],
            instance_id="bridge-1",
            adapter=adapter,
        )
    assert len(adapter.api.submissions) == 0
    reconciled = broker_gateway.reconcile(
        binding["id"],
        instance_id="bridge-1",
        adapter=adapter,
    )
    assert reconciled["status"] == "clean"
    with pytest.raises(RuntimeError, match="官方 gm.api"):
        broker_gateway.record_rehearsal(
            binding["id"],
            instance_id="bridge-1",
            adapter=adapter,
        )
    with sessions() as session:
        assert (
            session.scalar(select(BrokerOrder)).status
            == "blocked_account_type"
        )
        assert session.scalar(select(BrokerReconciliation)) is not None


def test_submit_exception_becomes_uncertain_and_is_never_retried(
    broker_db, monkeypatch
):
    _, user = broker_db
    monkeypatch.setattr(
        broker_gateway.settings, "emt_account_id", "sim-account-2"
    )
    monkeypatch.setattr(
        broker_gateway.settings, "emt_strategy_id", "emt-strategy-2"
    )
    filing = broker_gateway.register_filing(
        user_id=user.id,
        reviewed_by_user_id="admin-a",
        filing_reference="simulation-filing-2026",
        evidence_document_sha256="b" * 64,
        professional_eligibility_confirmed=True,
        broker_simulation_permission_confirmed=True,
    )
    binding = broker_gateway.bind_simulation(
        user_id=user.id,
        filing_profile_id=filing["id"],
        account_id="sim-account-2",
        strategy_id="emt-strategy-2",
    )
    broker_gateway.claim_bridge(
        binding["id"],
        instance_id="bridge-2",
        sdk_version="3.0.999",
    )
    order = broker_gateway.enqueue_rehearsal_order(
        user=user,
        binding_id=binding["id"],
        idempotency_key="rehearsal-order-2",
        code="000001.SZ",
        side="buy",
        qty=100,
        limit_price=10,
        step_up_token="step-up-token",
    )
    with broker_gateway.SessionLocal.begin() as session:
        row = session.get(BrokerOrder, order["id"])
        row.status = "queued"
    failing = SimpleNamespace(
        simulation_account_verified=True,
        submit_order=lambda request: (_ for _ in ()).throw(
            ConnectionError("lost after send")
        )
    )
    result = broker_gateway.process_one(
        binding["id"],
        instance_id="bridge-2",
        adapter=failing,
    )
    assert result["status"] == "uncertain"
    assert (
        broker_gateway._claim_next_order(
            binding["id"], instance_id="bridge-2"
        )
        is None
    )
