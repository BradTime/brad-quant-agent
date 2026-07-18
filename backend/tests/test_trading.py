"""模拟交易撮合服务测试（价源 monkeypatch 固定为 10.0，确定性）。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.session import SessionLocal
from app.models.trading import SimAccount, SimOrder
from app.services import trading


@pytest.fixture
def uid(monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 10.0,
            "yesterdayClose": 10.0,
            "executable": True,
        },
    )
    monkeypatch.setattr(trading.market, "get_instrument_name", lambda code: code)
    monkeypatch.setattr(
        trading.market,
        "get_instrument_list_date",
        lambda code: date(1999, 1, 1),
        raising=False,
    )
    return uuid.uuid4().hex


def test_market_buy_updates_position_and_cash(uid):
    o = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    assert o["status"] == "filled"
    acct = trading.get_account(uid)
    # 成本 10*100=1000 + 佣金 max(0.25,5)=5 → 现金 1_000_000 - 1005
    assert acct["cash"] == 998995.0
    pos = trading.get_positions(uid)
    assert pos[0]["qty"] == 100
    assert pos[0]["availableQty"] == 0  # T+1：当日买入不可用


def test_t1_blocks_same_day_sell(uid):
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    o = trading.place_order(uid, "600000.SH", "sell", "market", None, 100)
    assert o["status"] == "rejected"
    assert "持仓" in o["reason"]


def test_limit_pending_then_cancel_releases_freeze(uid):
    o = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)  # 现价 10 > 9 → 挂单
    assert o["status"] == "pending"
    assert trading.get_account(uid)["frozenCash"] > 0
    c = trading.cancel_order(uid, o["id"])
    assert c["status"] == "cancelled"
    acct = trading.get_account(uid)
    assert acct["frozenCash"] == 0.0
    assert acct["cash"] == 1_000_000.0


def test_sell_after_settle_applies_fee_and_tax(uid):
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    # 模拟次日：把结算日改早，触发 _settle 解冻 available
    with SessionLocal() as s:
        acct = s.get(SimAccount, uid)
        acct.last_settle_date = date(2000, 1, 1)
        s.commit()
    pos = trading.get_positions(uid)  # 触发 _settle
    assert pos[0]["availableQty"] == 100
    o = trading.place_order(uid, "600000.SH", "sell", "market", None, 100)
    assert o["status"] == "filled"
    # 当前税率：卖出 1000 - 佣金5 - 印花税0.5 = 994.5
    assert trading.get_account(uid)["cash"] == 999989.5
    assert trading.get_positions(uid) == []  # 清仓后不列出


def test_lot_size_validation(uid):
    with pytest.raises(ValueError):
        trading.place_order(uid, "600000.SH", "buy", "market", None, 150)


def test_market_buy_rejected_when_no_price(uid, monkeypatch):
    monkeypatch.setattr(trading.market, "get_cached_or_last_quote", lambda code: None)
    o = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    assert o["status"] == "rejected"
    assert "价格" in o["reason"]


def _use_non_executable_quote(monkeypatch, reason: str = "quote_expired") -> None:
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "price": 10.0,
            "stale": True,
            "staleReason": reason,
            "executable": False,
        },
    )
    monkeypatch.setattr(trading.market, "get_instrument_name", lambda code: code)


def test_price_returns_only_executable_snapshot(monkeypatch):
    _use_non_executable_quote(monkeypatch)
    assert trading._price("600000.SH") is None

    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {"price": 10.0, "executable": True},
    )
    assert trading._price("600000.SH") == 10.0


def test_last_close_can_value_positions_but_cannot_execute(monkeypatch):
    _use_non_executable_quote(monkeypatch, reason="last_close")

    assert trading._price("600000.SH") is None
    assert trading._valuation_price("600000.SH") == 10.0


def test_stale_limit_order_only_freezes_and_stays_pending(uid, monkeypatch):
    _use_non_executable_quote(monkeypatch)

    order = trading.place_order(uid, "600000.SH", "buy", "limit", 10.0, 100)

    assert order["status"] == "pending"
    assert trading.get_account(uid)["frozenCash"] == 1005.0


def test_stale_market_order_is_explicitly_rejected(uid, monkeypatch):
    _use_non_executable_quote(monkeypatch)

    order = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)

    assert order["status"] == "rejected"
    assert "可执行行情" in order["reason"]


def test_non_executable_gate_runs_before_price_limit_metadata(uid, monkeypatch):
    _use_non_executable_quote(monkeypatch)

    def fail_if_called(_code: str):
        raise AssertionError("不可执行行情不应进入涨跌停元数据查询")

    monkeypatch.setattr(trading.market, "get_instrument_list_date", fail_if_called)

    order = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)

    assert order["status"] == "rejected"
    assert "可执行行情" in order["reason"]


def test_matcher_does_not_fill_pending_order_with_stale_quote(uid, monkeypatch):
    _use_non_executable_quote(monkeypatch)
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 10.0, 100)
    assert order["status"] == "pending"

    assert trading.try_match_pending() >= 0
    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "pending"


def test_market_buy_at_limit_up_is_rejected(uid, monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 11.0,
            "yesterdayClose": 10.0,
            "executable": True,
        },
    )

    order = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)

    assert order["status"] == "rejected"
    assert "涨停" in order["reason"]


def test_market_order_rejected_when_limited_board_lacks_previous_close(uid, monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 10.0,
            "executable": True,
        },
    )

    order = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)

    assert order["status"] == "rejected"
    assert "昨收" in order["reason"]


def test_limit_buy_at_limit_up_stays_pending_and_matcher_skips(uid, monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 11.0,
            "yesterdayClose": 10.0,
            "executable": True,
        },
    )

    order = trading.place_order(uid, "600000.SH", "buy", "limit", 11.0, 100)

    assert order["status"] == "pending"
    assert "涨停" in order["reason"]
    assert trading.try_match_pending() == 0
    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "pending"


def test_pending_order_without_previous_close_never_matches(uid, monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 10.0,
            "executable": True,
        },
    )

    order = trading.place_order(uid, "600000.SH", "buy", "limit", 10.0, 100)

    assert order["status"] == "pending"
    assert "昨收" in order["reason"]
    assert trading.try_match_pending() == 0
    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "pending"


def test_first_five_session_market_order_can_fill_without_previous_close(uid, monkeypatch):
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "688001.SH",
            "price": 12.0,
            "executable": True,
        },
    )
    monkeypatch.setattr(
        trading.market,
        "get_instrument_list_date",
        lambda _code: date(2024, 1, 2),
    )
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 8), raising=False)

    order = trading.place_order(uid, "688001.SH", "buy", "market", None, 100)

    assert order["status"] == "filled"


def test_matcher_settles_and_rechecks_pending_before_fill(uid, monkeypatch):
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["status"] == "pending"
    assert order["tif"] == "DAY"
    assert order["tradeDate"] is not None
    with SessionLocal() as session:
        account = session.get(SimAccount, uid)
        account.last_settle_date = date(2024, 1, 2)
        row = session.get(SimOrder, order["id"])
        row.trade_date = date(2024, 1, 2)
        session.commit()
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3), raising=False)
    monkeypatch.setattr(
        trading,
        "_execution_snapshot",
        lambda _code: {
            "price": 8.0,
            "yesterdayClose": 8.0,
            "executable": True,
        },
    )

    assert trading.try_match_pending() == 0

    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "cancelled"
    assert trading.get_account(uid)["frozenCash"] == 0.0


def test_eod_settle_cancels_stale_day_orders_without_user_visit(uid, monkeypatch):
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["status"] == "pending"
    with SessionLocal() as session:
        account = session.get(SimAccount, uid)
        account.last_settle_date = date(2024, 1, 2)
        row = session.get(SimOrder, order["id"])
        row.trade_date = date(2024, 1, 2)
        session.commit()
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3), raising=False)

    assert trading.settle_all_accounts() >= 1

    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "cancelled"
    assert saved["reason"] == "日终未成交，自动撤销"
    assert trading.get_account(uid)["frozenCash"] == 0.0


def test_same_day_pending_survives_settle(uid, monkeypatch):
    monkeypatch.setattr(trading, "market_today", lambda: date(2024, 1, 3), raising=False)
    order = trading.place_order(uid, "600000.SH", "buy", "limit", 9.0, 100)
    assert order["status"] == "pending"
    assert order["tradeDate"] == "2024-01-03"

    trading.settle_all_accounts()

    saved = next(item for item in trading.list_orders(uid) if item["id"] == order["id"])
    assert saved["status"] == "pending"


def test_settle_uses_shanghai_market_today(uid, monkeypatch):
    expected = date(2030, 1, 2)
    monkeypatch.setattr(trading, "market_today", lambda: expected, raising=False)

    trading.get_account(uid)

    with SessionLocal() as session:
        assert session.get(SimAccount, uid).last_settle_date == expected


def test_market_sell_at_limit_down_is_rejected(uid, monkeypatch):
    trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    with SessionLocal() as session:
        account = session.get(SimAccount, uid)
        account.last_settle_date = date(2000, 1, 1)
        session.commit()
    trading.get_positions(uid)
    monkeypatch.setattr(
        trading.market,
        "get_cached_or_last_quote",
        lambda _code: {
            "code": "600000.SH",
            "price": 9.0,
            "yesterdayClose": 10.0,
            "executable": True,
        },
    )

    order = trading.place_order(uid, "600000.SH", "sell", "market", None, 100)

    assert order["status"] == "rejected"
    assert "跌停" in order["reason"]
