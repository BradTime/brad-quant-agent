"""模拟交易撮合服务（Phase 3，play-money）。

规则（MVP）：
- 初始资金 100 万；100 股整手；佣金万 2.5（最低 5 元），卖出加印花税千 1（过户费略）。
- 市价单按最新**快照/最近收盘价**即时成交；限价单可成交则即时成交，否则挂单，
  由行情刷新调度 ``try_match_pending`` 尝试撮合。取不到价的市价单拒单（不杜撰价）。
- T+1：当日买入计入 ``qty`` 但不计入 ``available_qty``；跨日 ``_settle`` 解冻（available=qty），
  并自动撤销上一交易日未成交挂单（A 股日内有效）。
- 挂买单冻结现金、挂卖单冻结可用股；撤单/日终自动释放。
- 成交/拒单经 WS 私有通道推送（``trade.fill``），不走行情广播。
"""

from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.services import market

logger = logging.getLogger(__name__)

INITIAL_CASH = 1_000_000.0
LOT = 100
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_TAX_RATE = 0.001  # 卖出印花税


def _canon(code: str) -> str:
    from app.providers import symbols

    return code if "." in code else symbols.to_canonical(symbols.to_six(code))


def _price(code: str) -> float | None:
    q = market.get_cached_or_last_quote(code)
    if not q:
        return None
    px = q.get("price")
    return float(px) if px else None


def _commission(amount: float) -> float:
    return round(max(amount * COMMISSION_RATE, COMMISSION_MIN), 2)


def _r(x: float) -> float:
    return round(float(x), 2)


# ---------- 内部状态读写 ----------


def _get_or_create_account(session, user_id: str) -> SimAccount:
    acct = session.get(SimAccount, user_id)
    if acct is None:
        acct = SimAccount(
            user_id=user_id, cash=INITIAL_CASH, frozen_cash=0.0, initial_cash=INITIAL_CASH
        )
        session.add(acct)
        session.flush()
    return acct


def _get_position(session, user_id: str, code: str) -> SimPosition | None:
    return session.get(SimPosition, (user_id, code))


def _settle(session, acct: SimAccount) -> None:
    """跨交易日结算：撤销上一日未成交挂单（释放冻结）+ 解冻 T+1（available=qty）。"""
    today = date.today()
    if acct.last_settle_date == today:
        return
    stale = list(
        session.execute(
            select(SimOrder).where(SimOrder.user_id == acct.user_id, SimOrder.status == "pending")
        ).scalars()
    )
    for o in stale:
        if o.side == "buy" and o.frozen:
            acct.cash = _r(acct.cash + o.frozen)
            acct.frozen_cash = _r(acct.frozen_cash - o.frozen)
            o.frozen = 0.0
        o.status = "cancelled"
        o.reason = "日终未成交，自动撤销"
    for pos in session.execute(
        select(SimPosition).where(SimPosition.user_id == acct.user_id)
    ).scalars():
        pos.available_qty = pos.qty
    acct.last_settle_date = today


def _record_trade(session, order: SimOrder, price: float, amount: float, fee: float, tax: float):
    session.add(
        SimTrade(
            id=uuid4().hex,
            user_id=order.user_id,
            order_id=order.id,
            code=order.code,
            name=order.name,
            side=order.side,
            price=price,
            qty=order.qty,
            amount=amount,
            fee=fee,
            tax=tax,
        )
    )


def _fill(session, acct: SimAccount, order: SimOrder, fill_px: float, from_pending: bool = False):
    """执行成交。成功返回 None；业务拒绝返回中文原因。"""
    qty = order.qty
    amount = _r(fill_px * qty)
    fee = _commission(amount)
    pos = _get_position(session, order.user_id, order.code)
    tax = 0.0
    if order.side == "buy":
        total = _r(amount + fee)
        if acct.cash < total:
            return "资金不足"
        acct.cash = _r(acct.cash - total)
        if pos is None:
            pos = SimPosition(
                user_id=order.user_id, code=order.code, name=order.name,
                qty=0, available_qty=0, avg_cost=0.0,
            )
            session.add(pos)
        old_cost = pos.avg_cost * pos.qty
        pos.qty += qty
        pos.avg_cost = round((old_cost + total) / pos.qty, 4)
        # available_qty 不增 → 当日买入 T+1 冻结
    else:  # sell
        if not from_pending and (pos is None or pos.available_qty < qty):
            return "可用持仓不足（T+1：当日买入次日可卖）"
        if pos is None:
            return "无持仓"
        tax = _r(amount * STAMP_TAX_RATE)
        proceeds = _r(amount - fee - tax)
        acct.cash = _r(acct.cash + proceeds)
        pos.qty -= qty
        if not from_pending:
            pos.available_qty -= qty
        if pos.qty <= 0:
            pos.qty = 0
            pos.available_qty = max(pos.available_qty, 0)
            pos.avg_cost = 0.0
    order.status = "filled"
    order.filled_qty = qty
    order.avg_fill_price = fill_px
    _record_trade(session, order, fill_px, amount, fee, tax)
    return None


def _freeze_pending(session, acct: SimAccount, order: SimOrder, limit: float):
    """挂单冻结：买冻结现金、卖冻结可用股。成功 None，否则拒绝原因。"""
    qty = order.qty
    if order.side == "buy":
        est = _r(limit * qty)
        frozen = _r(est + _commission(est))
        if acct.cash < frozen:
            return "资金不足"
        acct.cash = _r(acct.cash - frozen)
        acct.frozen_cash = _r(acct.frozen_cash + frozen)
        order.frozen = frozen
    else:
        pos = _get_position(session, order.user_id, order.code)
        if pos is None or pos.available_qty < qty:
            return "可用持仓不足（T+1：当日买入次日可卖）"
        pos.available_qty -= qty
    return None


# ---------- 对外：下单 / 撤单 / 撮合 ----------


def place_order(
    user_id: str, code: str, side: str, order_type: str, price: float | None = None, qty: int = 0
) -> dict:
    side = (side or "").lower()
    order_type = (order_type or "").lower()
    if side not in ("buy", "sell"):
        raise ValueError("side 必须为 buy/sell")
    if order_type not in ("limit", "market"):
        raise ValueError("order_type 必须为 limit/market")
    if not isinstance(qty, int) or qty <= 0 or qty % LOT != 0:
        raise ValueError("数量必须为 100 的正整数倍")
    if order_type == "limit" and (price is None or price <= 0):
        raise ValueError("限价单需提供正的价格")
    code = _canon(code)

    with SessionLocal() as session:
        acct = _get_or_create_account(session, user_id)
        _settle(session, acct)
        name = market.get_instrument_name(code) or code
        order = SimOrder(
            id=uuid4().hex, user_id=user_id, code=code, name=name,
            side=side, order_type=order_type, price=price, qty=qty, status="pending",
        )
        session.add(order)

        px = _price(code)
        fill_px: float | None = None
        if order_type == "market":
            if px is None:
                order.status = "rejected"
                order.reason = "无法获取行情价格，已拒单（不编造价格）"
                session.commit()
                _notify(order)
                return _order_dict(order)
            fill_px = px
        elif px is not None and (
            (side == "buy" and px <= price) or (side == "sell" and px >= price)
        ):
            fill_px = min(px, price) if side == "buy" else max(px, price)

        if fill_px is not None:
            reason = _fill(session, acct, order, fill_px)
            if reason:
                order.status = "rejected"
                order.reason = reason
        else:
            reason = _freeze_pending(session, acct, order, price)
            if reason:
                order.status = "rejected"
                order.reason = reason
        session.commit()
        _notify(order)
        return _order_dict(order)


def cancel_order(user_id: str, order_id: str) -> dict | None:
    with SessionLocal() as session:
        order = session.get(SimOrder, order_id)
        if order is None or order.user_id != user_id:
            return None
        if order.status != "pending":
            raise ValueError("仅可撤销挂单")
        acct = _get_or_create_account(session, user_id)
        if order.side == "buy" and order.frozen:
            acct.cash = _r(acct.cash + order.frozen)
            acct.frozen_cash = _r(acct.frozen_cash - order.frozen)
            order.frozen = 0.0
        else:
            pos = _get_position(session, user_id, order.code)
            if pos is not None:
                pos.available_qty += order.qty
        order.status = "cancelled"
        order.reason = "用户撤单"
        session.commit()
        return _order_dict(order)


def try_match_pending() -> int:
    """调度器入口：用最新快照价尝试撮合所有挂单。返回成交单数。"""
    filled = 0
    with SessionLocal() as session:
        pendings = list(
            session.execute(select(SimOrder).where(SimOrder.status == "pending")).scalars()
        )
        notify_orders: list[SimOrder] = []
        for order in pendings:
            px = _price(order.code)
            if px is None or order.price is None:
                continue
            limit = order.price
            if order.side == "buy" and px <= limit:
                acct = _get_or_create_account(session, order.user_id)
                # 先把冻结现金释放回可用，再由 _fill 正常扣款（limit>=fill_px 故必足额）
                if order.frozen:
                    acct.cash = _r(acct.cash + order.frozen)
                    acct.frozen_cash = _r(acct.frozen_cash - order.frozen)
                    order.frozen = 0.0
                if _fill(session, acct, order, min(px, limit)) is None:
                    filled += 1
                notify_orders.append(order)
            elif order.side == "sell" and px >= limit:
                acct = _get_or_create_account(session, order.user_id)
                if _fill(session, acct, order, max(px, limit), from_pending=True) is None:
                    filled += 1
                notify_orders.append(order)
        session.commit()
        for o in notify_orders:
            _notify(o)
    return filled


# ---------- WS 私有回报 ----------


def _notify(order: SimOrder) -> None:
    try:
        from app.ws.notify import notify_user_threadsafe

        notify_user_threadsafe(order.user_id, "trade.fill", _order_dict(order))
    except Exception as exc:  # noqa: BLE001
        logger.debug("交易回报推送失败（忽略）：%s", exc)


# ---------- 读取（账户 / 持仓 / 委托 / 成交） ----------


def _order_dict(o: SimOrder) -> dict:
    return {
        "id": o.id,
        "code": o.code,
        "name": o.name,
        "side": o.side,
        "type": o.order_type,
        "price": o.price,
        "qty": o.qty,
        "filledQty": o.filled_qty,
        "avgFillPrice": o.avg_fill_price,
        "status": o.status,
        "reason": o.reason,
        "createdAt": o.created_at.isoformat() if o.created_at else None,
    }


def get_account(user_id: str) -> dict:
    with SessionLocal() as session:
        acct = _get_or_create_account(session, user_id)
        _settle(session, acct)
        positions = list(
            session.execute(
                select(SimPosition).where(SimPosition.user_id == user_id, SimPosition.qty > 0)
            ).scalars()
        )
        market_value = 0.0
        for p in positions:
            px = _price(p.code) or p.avg_cost
            market_value += px * p.qty
        market_value = _r(market_value)
        total = _r(acct.cash + acct.frozen_cash + market_value)
        pnl = _r(total - acct.initial_cash)
        out = {
            "cash": _r(acct.cash),
            "frozenCash": _r(acct.frozen_cash),
            "initialCash": _r(acct.initial_cash),
            "marketValue": market_value,
            "totalAssets": total,
            "pnl": pnl,
            "pnlPct": round(pnl / acct.initial_cash * 100, 2) if acct.initial_cash else 0.0,
        }
        session.commit()
        return out


def get_positions(user_id: str) -> list[dict]:
    with SessionLocal() as session:
        acct = _get_or_create_account(session, user_id)
        _settle(session, acct)
        rows = list(
            session.execute(
                select(SimPosition).where(SimPosition.user_id == user_id, SimPosition.qty > 0)
            ).scalars()
        )
        out = []
        for p in rows:
            px = _price(p.code)
            cur = px if px is not None else p.avg_cost
            mv = _r(cur * p.qty)
            cost = _r(p.avg_cost * p.qty)
            out.append(
                {
                    "code": p.code,
                    "name": p.name,
                    "qty": p.qty,
                    "availableQty": p.available_qty,
                    "avgCost": round(p.avg_cost, 4),
                    "price": cur,
                    "marketValue": mv,
                    "pnl": _r(mv - cost),
                    "pnlPct": round((cur - p.avg_cost) / p.avg_cost * 100, 2) if p.avg_cost else 0.0,
                }
            )
        session.commit()
        return out


def list_orders(user_id: str, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(SimOrder)
                .where(SimOrder.user_id == user_id)
                .order_by(SimOrder.created_at.desc())
                .limit(limit)
            ).scalars()
        )
        return [_order_dict(o) for o in rows]


def list_trades(user_id: str, limit: int = 50) -> list[dict]:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(SimTrade)
                .where(SimTrade.user_id == user_id)
                .order_by(SimTrade.traded_at.desc())
                .limit(limit)
            ).scalars()
        )
        return [
            {
                "id": t.id,
                "code": t.code,
                "name": t.name,
                "side": t.side,
                "price": t.price,
                "qty": t.qty,
                "amount": _r(t.amount),
                "fee": _r(t.fee),
                "tax": _r(t.tax),
                "tradedAt": t.traded_at.isoformat() if t.traded_at else None,
            }
            for t in rows
        ]


def build_review_input(user_id: str) -> str:
    """把账户/持仓/成交汇总成给 LLM 的复盘输入文本（只喂真实数据）。"""
    acct = get_account(user_id)
    positions = get_positions(user_id)
    trades = list_trades(user_id, limit=30)
    lines = ["【模拟账户复盘数据】"]
    lines.append(
        f"总资产 {acct['totalAssets']}，现金 {acct['cash']}（冻结 {acct['frozenCash']}），"
        f"持仓市值 {acct['marketValue']}，浮动盈亏 {acct['pnl']}（{acct['pnlPct']}%）"
    )
    lines.append("\n# 当前持仓")
    if positions:
        for p in positions:
            lines.append(
                f"- {p['name']}({p['code']}) {p['qty']}股 成本{p['avgCost']} 现价{p['price']} "
                f"盈亏{p['pnl']}（{p['pnlPct']}%）"
            )
    else:
        lines.append("- 无持仓")
    lines.append("\n# 近期成交")
    if trades:
        for t in trades[:20]:
            lines.append(
                f"- {t['tradedAt']} {('买' if t['side']=='buy' else '卖')} {t['name']}({t['code']}) "
                f"{t['qty']}股 @ {t['price']} 费{t['fee']}+税{t['tax']}"
            )
    else:
        lines.append("- 无成交")
    lines.append("\n请基于以上真实数据做复盘。")
    return "\n".join(lines)
