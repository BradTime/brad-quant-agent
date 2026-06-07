"""模拟交易撮合服务测试（价源 monkeypatch 固定为 10.0，确定性）。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.session import SessionLocal
from app.models.trading import SimAccount
from app.services import trading


@pytest.fixture
def uid(monkeypatch):
    monkeypatch.setattr(trading, "_price", lambda code: 10.0)
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
    # 卖出 1000 - 佣金5 - 印花税1 = 994；现金 998995 + 994
    assert trading.get_account(uid)["cash"] == 999989.0
    assert trading.get_positions(uid) == []  # 清仓后不列出


def test_lot_size_validation(uid):
    with pytest.raises(ValueError):
        trading.place_order(uid, "600000.SH", "buy", "market", None, 150)


def test_market_buy_rejected_when_no_price(uid, monkeypatch):
    monkeypatch.setattr(trading, "_price", lambda code: None)
    o = trading.place_order(uid, "600000.SH", "buy", "market", None, 100)
    assert o["status"] == "rejected"
    assert "价格" in o["reason"]
