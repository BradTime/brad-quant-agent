"""模拟交易账户、订单与持仓的并发一致性测试。"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import date
from threading import Barrier, Condition, Event, Lock, RLock

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.session import engine as app_engine
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.services import trading
from app.services.trading_rules import INITIAL_CASH

_TABLES = (SimAccount.__table__, SimPosition.__table__, SimOrder.__table__, SimTrade.__table__)


def _snapshot(price: float) -> dict:
    return {
        "price": price,
        "yesterdayClose": price,
        "executable": True,
    }


@pytest.fixture(params=("sqlite", "postgresql"), ids=("sqlite", "postgresql"))
def trading_db(request, tmp_path, monkeypatch):
    """每个用例使用隔离数据库；PostgreSQL 不可用时仅跳过对应参数。"""
    schema: str | None = None
    root_engine = None

    if request.param == "sqlite":
        db_engine = create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'trading.db'}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        with db_engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    else:
        if app_engine.dialect.name != "postgresql":
            pytest.skip("DATABASE_URL 未配置为 PostgreSQL")
        root_engine = create_engine(app_engine.url, pool_pre_ping=True)
        try:
            with root_engine.connect():
                pass
        except SQLAlchemyError as exc:
            root_engine.dispose()
            pytest.skip(f"PostgreSQL 不可用: {exc}")
        schema = f"test_trading_{uuid.uuid4().hex}"
        with root_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        db_engine = root_engine.execution_options(schema_translate_map={None: schema})

    for table in _TABLES:
        table.create(bind=db_engine)

    test_session = sessionmaker(
        bind=db_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(trading, "SessionLocal", test_session)
    monkeypatch.setattr(trading, "_execution_snapshot", lambda _code: _snapshot(10.0))
    monkeypatch.setattr(trading.market, "get_instrument_name", lambda code: code)
    monkeypatch.setattr(trading.market, "get_instrument_list_date", lambda code: date(1999, 1, 1))
    monkeypatch.setattr(trading, "_notify", lambda _order: None)
    if request.param == "postgresql":
        # PostgreSQL 参数禁用进程内锁，确保测试真正覆盖跨 worker 的数据库行锁。
        monkeypatch.setattr(trading, "_user_lock", lambda _user_id: nullcontext())

    try:
        yield test_session, db_engine
    finally:
        if root_engine is None:
            db_engine.dispose()
        else:
            with root_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            root_engine.dispose()


def _new_user_id() -> str:
    return uuid.uuid4().hex


def _create_account(session_factory, user_id: str) -> None:
    with session_factory.begin() as session:
        session.add(
            SimAccount(
                user_id=user_id,
                cash=INITIAL_CASH,
                frozen_cash=0.0,
                initial_cash=INITIAL_CASH,
                last_settle_date=date.today(),
            )
        )


def _place_pending_buy(user_id: str) -> dict:
    return trading.place_order(user_id, "600000.SH", "buy", "limit", 9.0, 100)


def test_concurrent_first_access_creates_one_account(trading_db):
    session_factory, db_engine = trading_db
    user_id = _new_user_id()
    inserts_ready = Barrier(2)

    def synchronize_account_inserts(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        normalized = statement.lower()
        if "insert into" in normalized and "sim_accounts" in normalized:
            inserts_ready.wait(timeout=5)

    event.listen(db_engine, "before_cursor_execute", synchronize_account_inserts)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            account_future = pool.submit(trading.get_account, user_id)
            positions_future = pool.submit(trading.get_positions, user_id)
            account = account_future.result(timeout=10)
            positions = positions_future.result(timeout=10)
    finally:
        event.remove(db_engine, "before_cursor_execute", synchronize_account_inserts)

    assert account["cash"] == INITIAL_CASH
    assert positions == []
    with session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(SimAccount).where(SimAccount.user_id == user_id)
        ) == 1


def test_concurrent_buys_cannot_spend_the_same_cash_twice(trading_db, monkeypatch):
    session_factory, _ = trading_db
    user_id = _new_user_id()
    _create_account(session_factory, user_id)
    price_calls = 0
    calls_changed = Condition()

    def synchronized_price(_code: str) -> dict:
        nonlocal price_calls
        with calls_changed:
            price_calls += 1
            if price_calls == 1:
                calls_changed.wait_for(lambda: price_calls >= 2, timeout=0.5)
            else:
                calls_changed.notify_all()
        return _snapshot(6000.0)

    monkeypatch.setattr(trading, "_execution_snapshot", synchronized_price)
    start = Barrier(3)

    def place(code: str) -> dict:
        start.wait(timeout=5)
        return trading.place_order(user_id, code, "buy", "market", None, 100)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(place, "600000.SH"),
            pool.submit(place, "000001.SZ"),
        ]
        start.wait(timeout=5)
        orders = [future.result(timeout=10) for future in futures]

    assert sorted(order["status"] for order in orders) == ["filled", "rejected"]
    with session_factory() as session:
        account = session.get(SimAccount, user_id)
        trade_count = session.scalar(
            select(func.count()).select_from(SimTrade).where(SimTrade.user_id == user_id)
        )
        total_qty = session.scalar(
            select(func.coalesce(func.sum(SimPosition.qty), 0)).where(
                SimPosition.user_id == user_id
            )
        )
    assert account.cash == pytest.approx(399_850.0)
    assert account.frozen_cash == 0.0
    assert trade_count == 1
    assert total_qty == 100


def test_match_holding_user_lock_finishes_before_cancel(trading_db, monkeypatch):
    session_factory, _ = trading_db
    user_id = _new_user_id()
    order = _place_pending_buy(user_id)
    assert order["status"] == "pending"

    price_requested = Event()
    release_price = Event()

    def delayed_match_price(_code: str) -> dict:
        price_requested.set()
        assert release_price.wait(timeout=5)
        return _snapshot(8.0)

    monkeypatch.setattr(trading, "_execution_snapshot", delayed_match_price)
    with ThreadPoolExecutor(max_workers=1) as pool:
        match_future = pool.submit(trading.try_match_pending)
        assert price_requested.wait(timeout=5)
        release_price.set()
        matched = match_future.result(timeout=10)
    with pytest.raises(ValueError, match="仅可撤销挂单"):
        trading.cancel_order(user_id, order["id"])

    assert matched == 1
    with session_factory() as session:
        saved_order = session.get(SimOrder, order["id"])
        account = session.get(SimAccount, user_id)
        trade_count = session.scalar(
            select(func.count()).select_from(SimTrade).where(SimTrade.order_id == order["id"])
        )
        position_qty = session.scalar(
            select(func.coalesce(func.sum(SimPosition.qty), 0)).where(
                SimPosition.user_id == user_id
            )
        )
    assert saved_order.status == "filled"
    assert saved_order.frozen == 0.0
    assert account.cash == pytest.approx(INITIAL_CASH - 805.0)
    assert account.frozen_cash == 0.0
    assert trade_count == 1
    assert position_qty == 100


def test_match_reads_snapshot_after_waiting_for_user_lock(trading_db, monkeypatch):
    session_factory, _ = trading_db
    user_id = _new_user_id()
    user_lock = RLock()
    monkeypatch.setattr(trading, "_user_lock", lambda _user_id: user_lock)
    order = _place_pending_buy(user_id)
    assert order["status"] == "pending"

    price_calls = 0

    def stale_after_lock(_code: str) -> None:
        nonlocal price_calls
        price_calls += 1
        return None

    monkeypatch.setattr(trading, "_execution_snapshot", stale_after_lock)
    lock_released = False
    user_lock.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            match_future = pool.submit(trading.try_match_pending)
            user_lock.release()
            lock_released = True
            matched = match_future.result(timeout=10)
    finally:
        if not lock_released:
            user_lock.release()

    assert price_calls == 1
    assert matched == 0
    with session_factory() as session:
        saved_order = session.get(SimOrder, order["id"])
        account = session.get(SimAccount, user_id)
        trade_count = session.scalar(
            select(func.count()).select_from(SimTrade).where(SimTrade.order_id == order["id"])
        )
    assert saved_order.status == "pending"
    assert saved_order.frozen == 905.0
    assert account.frozen_cash == 905.0
    assert trade_count == 0


def test_two_matchers_cannot_fill_one_order_twice(trading_db, monkeypatch):
    session_factory, _ = trading_db
    user_id = _new_user_id()
    order = _place_pending_buy(user_id)
    assert order["status"] == "pending"
    with session_factory.begin() as session:
        session.add(
            SimPosition(
                user_id=user_id,
                code=order["code"],
                name=order["name"],
                qty=0,
                available_qty=0,
                avg_cost=0.0,
            )
        )

    price_calls = 0
    price_calls_lock = Lock()

    def synchronized_match_price(_code: str) -> dict:
        nonlocal price_calls
        with price_calls_lock:
            price_calls += 1
        return _snapshot(8.0)

    monkeypatch.setattr(trading, "_execution_snapshot", synchronized_match_price)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: trading.try_match_pending(), range(2)))

    assert sum(results) == 1
    with session_factory() as session:
        saved_order = session.get(SimOrder, order["id"])
        trade_count = session.scalar(
            select(func.count()).select_from(SimTrade).where(SimTrade.order_id == order["id"])
        )
        position = session.get(SimPosition, (user_id, order["code"]))
        account = session.get(SimAccount, user_id)
    assert saved_order.status == "filled"
    assert saved_order.filled_qty == 100
    assert trade_count == 1
    assert position.qty == 100
    assert account.cash == 999_195.0
    assert account.frozen_cash == 0.0
