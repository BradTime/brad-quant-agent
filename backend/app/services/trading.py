"""模拟交易撮合服务（Phase 3，play-money）。

规则：
- 初始资金 100 万；100 股整手；佣金万 2.5（最低 5 元），卖出按成交日适用历史印花税。
- 市价单仅按新鲜、开市且可执行的快照即时成交；限价单可成交则即时成交，否则挂单，
  由行情刷新调度 ``try_match_pending`` 尝试撮合。取不到价的市价单拒单（不杜撰价）。
- 即时与挂单撮合均用完整价格快照按昨收校验当日涨跌停；行情可执行门禁优先。
- T+1：当日买入计入 ``qty`` 但不计入 ``available_qty``；跨日 ``_settle`` 解冻（available=qty），
  并自动撤销上一交易日未成交挂单（A 股日内有效）。
- 挂买单冻结现金、挂卖单冻结可用股；撤单/日终自动释放。
- 成交/拒单经 WS 私有通道推送（``trade.fill``），不走行情广播。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from threading import RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.session import SessionLocal
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.services import market
from app.services.trading_rules import INITIAL_CASH, LOT, price_limit_ratio, stamp_tax
from app.services.trading_rules import commission as _commission
from app.services.trading_rules import round_money as _r

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

# SQLite 不支持行级 ``FOR UPDATE``，固定分片锁保证单进程测试/开发环境同用户串行。
# PostgreSQL 正确性仍由下方数据库行锁保证，不能依赖此进程内锁跨 worker 生效。
_USER_LOCKS = tuple(RLock() for _ in range(256))


def _user_lock(user_id: str) -> RLock:
    return _USER_LOCKS[hash(user_id) % len(_USER_LOCKS)]


def _canon(code: str) -> str:
    from app.providers import symbols

    return code if "." in code else symbols.to_canonical(symbols.to_six(code))


def _execution_snapshot(code: str) -> dict | None:
    """Return a complete executable quote; stale/closed snapshots are rejected first."""
    q = market.get_cached_or_last_quote(code)
    if not q or q.get("executable") is not True:
        return None
    px = q.get("price")
    if px is None or float(px) <= 0:
        return None
    snapshot = dict(q)
    snapshot["price"] = float(px)
    return snapshot


def _price(code: str) -> float | None:
    """Compatibility helper for callers that only need an executable price."""
    snapshot = _execution_snapshot(code)
    return snapshot["price"] if snapshot is not None else None


def market_today() -> date:
    """Return the current A-share market date in Asia/Shanghai."""
    return datetime.now(_SHANGHAI).date()


def _price_limit_reason(
    snapshot: dict,
    *,
    code: str,
    name: str,
    side: str,
    trade_date: date,
    list_date: date | None,
) -> str | None:
    ratio = price_limit_ratio(
        code,
        name=name,
        trade_date=trade_date,
        list_date=list_date,
    )
    if ratio is None or ratio <= 0:
        return None
    previous = snapshot.get("yesterdayClose")
    if previous is None or float(previous) <= 0:
        return "缺少有效昨收，无法校验涨跌停，订单不可成交"
    px = float(snapshot["price"])
    previous_px = float(previous)
    if side == "buy" and px >= round(previous_px * (1 + ratio), 2):
        return "当前价格已达涨停，买单不可成交"
    if side == "sell" and px <= round(previous_px * (1 - ratio), 2):
        return "当前价格已达跌停，卖单不可成交"
    return None


def _valuation_price(code: str) -> float | None:
    """Return any positive display price, including a non-executable last close."""
    executable = _price(code)
    if executable is not None:
        return executable
    q = market.get_cached_or_last_quote(code)
    if not q:
        return None
    px = q.get("price")
    return float(px) if px is not None and float(px) > 0 else None


# ---------- 内部状态读写 ----------


def _get_or_create_account(session, user_id: str, *, for_update: bool = False) -> SimAccount:
    """原子创建账户后读取；写事务通过 ``for_update`` 锁定账户行。"""
    values = {
        "user_id": user_id,
        "cash": INITIAL_CASH,
        "frozen_cash": 0.0,
        "initial_cash": INITIAL_CASH,
        "last_settle_date": None,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        insert_stmt = postgresql_insert(SimAccount).values(**values)
    elif dialect == "sqlite":
        insert_stmt = sqlite_insert(SimAccount).values(**values)
    else:
        raise RuntimeError(f"模拟交易暂不支持数据库方言: {dialect}")
    session.execute(insert_stmt.on_conflict_do_nothing(index_elements=[SimAccount.user_id]))

    account_stmt = select(SimAccount).where(SimAccount.user_id == user_id)
    if for_update:
        account_stmt = account_stmt.with_for_update()
    return session.execute(account_stmt).scalar_one()


def _get_position(
    session,
    user_id: str,
    code: str,
    *,
    for_update: bool = False,
) -> SimPosition | None:
    position_stmt = select(SimPosition).where(
        SimPosition.user_id == user_id,
        SimPosition.code == code,
    )
    if for_update:
        position_stmt = position_stmt.with_for_update()
    return session.execute(position_stmt).scalar_one_or_none()


def _is_stale_day_order(order: SimOrder, today: date) -> bool:
    """DAY 单：无 trade_date 或 trade_date < 今日 → 隔夜失效。"""
    tif = (order.tif or "DAY").upper()
    if tif != "DAY":
        return False
    return order.trade_date is None or order.trade_date < today


def _settle(session, acct: SimAccount) -> None:
    """跨交易日结算：撤销上一日未成交 DAY 挂单（释放冻结）+ 解冻 T+1（available=qty）。"""
    today = market_today()
    if acct.last_settle_date == today:
        return
    pending = list(
        session.execute(
            select(SimOrder)
            .where(SimOrder.user_id == acct.user_id, SimOrder.status == "pending")
            .with_for_update()
        ).scalars()
    )
    for o in pending:
        if not _is_stale_day_order(o, today):
            continue
        if o.side == "buy" and o.frozen:
            acct.cash = _r(acct.cash + o.frozen)
            acct.frozen_cash = _r(acct.frozen_cash - o.frozen)
            o.frozen = 0.0
        o.status = "cancelled"
        o.reason = "日终未成交，自动撤销"
    for pos in session.execute(
        select(SimPosition)
        .where(SimPosition.user_id == acct.user_id)
        .with_for_update()
    ).scalars():
        pos.available_qty = pos.qty
    acct.last_settle_date = today


def settle_all_accounts() -> int:
    """日终任务：对所有模拟账户执行 settle，撤销隔夜 DAY 挂单。返回处理账户数。"""
    with SessionLocal() as session:
        user_ids = list(session.execute(select(SimAccount.user_id)).scalars())
    settled = 0
    for user_id in user_ids:
        with _user_lock(user_id), SessionLocal() as session:
            acct = _get_or_create_account(session, user_id, for_update=True)
            _settle(session, acct)
            session.commit()
            settled += 1
    return settled


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
    pos = _get_position(session, order.user_id, order.code, for_update=True)
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
        tax = stamp_tax(amount, "sell", market_today())
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
    order.reason = ""
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
        pos = _get_position(session, order.user_id, order.code, for_update=True)
        if pos is None or pos.available_qty < qty:
            return "可用持仓不足（T+1：当日买入次日可卖）"
        pos.available_qty -= qty
    return None


# ---------- 对外：下单 / 撤单 / 撮合 ----------
# 统一锁顺序：进程内用户分片锁 → 账户行 → 订单行 → 持仓行。
# PostgreSQL 的数据库行锁承担跨进程正确性；保持顺序可避免撤单、结算和撮合互相死锁。


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

    with _user_lock(user_id), SessionLocal() as session:
        acct = _get_or_create_account(session, user_id, for_update=True)
        _settle(session, acct)
        name = market.get_instrument_name(code) or code
        order = SimOrder(
            id=uuid4().hex,
            user_id=user_id,
            code=code,
            name=name,
            side=side,
            order_type=order_type,
            price=price,
            qty=qty,
            status="pending",
            trade_date=market_today(),
            tif="DAY",
        )
        session.add(order)

        snapshot = _execution_snapshot(code)
        px = snapshot["price"] if snapshot is not None else None
        fill_px: float | None = None
        if order_type == "market" and snapshot is None:
            order.status = "rejected"
            order.reason = "无可执行行情价格，已拒单（行情陈旧、休市或不可用）"
            session.commit()
            _notify(order)
            return _order_dict(order)

        limit_reason = None
        if snapshot is not None:
            limit_reason = _price_limit_reason(
                snapshot,
                code=code,
                name=name,
                side=side,
                trade_date=market_today(),
                list_date=market.get_instrument_list_date(code),
            )

        if order_type == "market":
            if limit_reason is not None:
                order.status = "rejected"
                order.reason = limit_reason
                session.commit()
                _notify(order)
                return _order_dict(order)
            fill_px = px
        elif snapshot is not None and limit_reason is None and (
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
            elif limit_reason is not None:
                order.reason = limit_reason
        session.commit()
        _notify(order)
        return _order_dict(order)


def cancel_order(user_id: str, order_id: str) -> dict | None:
    with _user_lock(user_id), SessionLocal() as session:
        exists = session.execute(
            select(SimOrder.id).where(SimOrder.id == order_id, SimOrder.user_id == user_id)
        ).scalar_one_or_none()
        if exists is None:
            return None

        acct = _get_or_create_account(session, user_id, for_update=True)
        order = session.execute(
            select(SimOrder)
            .where(SimOrder.id == order_id, SimOrder.user_id == user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if order is None:
            return None
        if order.status != "pending":
            raise ValueError("仅可撤销挂单")

        if order.side == "buy":
            if order.frozen:
                acct.cash = _r(acct.cash + order.frozen)
                acct.frozen_cash = _r(acct.frozen_cash - order.frozen)
                order.frozen = 0.0
        else:
            pos = _get_position(session, user_id, order.code, for_update=True)
            if pos is not None:
                pos.available_qty += order.qty
        order.status = "cancelled"
        order.reason = "用户撤单"
        session.commit()
        return _order_dict(order)


def _try_match_pending_order(order_id: str, user_id: str) -> bool:
    """锁定并用锁后最新可执行价尝试成交；返回本次是否完成一笔成交。"""
    with _user_lock(user_id), SessionLocal() as session:
        acct = _get_or_create_account(session, user_id, for_update=True)
        _settle(session, acct)
        session.flush()
        order_stmt = select(SimOrder).where(
            SimOrder.id == order_id,
            SimOrder.user_id == user_id,
            SimOrder.status == "pending",
        )
        if session.get_bind().dialect.name == "postgresql":
            order_stmt = order_stmt.with_for_update(skip_locked=True)
        else:
            order_stmt = order_stmt.with_for_update()
        order = session.execute(order_stmt).scalar_one_or_none()
        if order is None or order.price is None:
            session.commit()
            return False

        # 外层价格仅用于无锁预筛。等待用户/账户/订单锁期间快照可能过期或休市，
        # 因此必须在锁内重新读取 executable 行情，绝不能信任锁前 px。
        snapshot = _execution_snapshot(order.code)
        if snapshot is None:
            return False
        px = snapshot["price"]
        limit_reason = _price_limit_reason(
            snapshot,
            code=order.code,
            name=order.name,
            side=order.side,
            trade_date=market_today(),
            list_date=market.get_instrument_list_date(order.code),
        )
        if limit_reason is not None:
            order.reason = limit_reason
            session.commit()
            return False

        limit = order.price
        if order.side == "buy":
            if px > limit:
                return False
            if order.frozen:
                acct.cash = _r(acct.cash + order.frozen)
                acct.frozen_cash = _r(acct.frozen_cash - order.frozen)
                order.frozen = 0.0
            reason = _fill(session, acct, order, min(px, limit))
        else:
            if px < limit:
                return False
            reason = _fill(session, acct, order, max(px, limit), from_pending=True)

        if reason:
            order.status = "rejected"
            order.reason = reason
        session.commit()
        _notify(order)
        return reason is None


def try_match_pending() -> int:
    """调度器入口：用最新快照价尝试撮合所有挂单。返回成交单数。"""
    with SessionLocal() as session:
        candidates = list(
            session.execute(
                select(
                    SimOrder.id,
                    SimOrder.user_id,
                ).where(SimOrder.status == "pending")
            )
        )

    filled = 0
    for order_id, user_id in candidates:
        if _try_match_pending_order(order_id, user_id):
            filled += 1
    return filled


# ---------- WS 私有回报 ----------


def _notify(order: SimOrder) -> None:
    try:
        from app.ws.notify import TRADE_FILL, notify_user_threadsafe

        notify_user_threadsafe(order.user_id, TRADE_FILL, _order_dict(order))
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
        "tradeDate": o.trade_date.isoformat() if o.trade_date else None,
        "tif": o.tif or "DAY",
        "createdAt": o.created_at.isoformat() if o.created_at else None,
    }


def get_account(user_id: str) -> dict:
    with SessionLocal() as session:
        acct = _get_or_create_account(session, user_id, for_update=True)
        _settle(session, acct)
        positions = list(
            session.execute(
                select(SimPosition).where(SimPosition.user_id == user_id, SimPosition.qty > 0)
            ).scalars()
        )
        market_value = 0.0
        for p in positions:
            px = _valuation_price(p.code) or p.avg_cost
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
        acct = _get_or_create_account(session, user_id, for_update=True)
        _settle(session, acct)
        rows = list(
            session.execute(
                select(SimPosition).where(SimPosition.user_id == user_id, SimPosition.qty > 0)
            ).scalars()
        )
        out = []
        for p in rows:
            px = _valuation_price(p.code)
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
