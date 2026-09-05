"""Dashboard aggregates: sim account / positions / trades / strategies."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.services import strategy, trading


def get_stats(user_id: str) -> dict:
    account = trading.get_account(user_id)
    all_strategies = strategy.list_strategies(user_id, page=1, page_size=1)
    active = strategy.list_strategies(user_id, page=1, page_size=1, status="active")
    total_assets = float(account.get("totalAssets") or 0)
    initial = float(account.get("initialCash") or 0) or 1.0
    pnl = float(account.get("pnl") or 0)
    pnl_pct = float(account.get("pnlPct") or 0)
    # 无日切权益快照时，今日收益与累计收益同口径（相对初始资金）
    return {
        "totalAssets": total_assets,
        "todayReturn": pnl,
        "todayReturnPercent": pnl_pct,
        "cumulativeReturn": pnl,
        "cumulativeReturnPercent": pnl_pct,
        "runningStrategies": int(active.get("total") or 0),
        "totalStrategies": int(all_strategies.get("total") or 0),
        "cash": float(account.get("cash") or 0),
        "frozenCash": float(account.get("frozenCash") or 0),
        "marketValue": float(account.get("marketValue") or 0),
        "initialCash": initial,
    }


def position_distribution(user_id: str) -> list[dict]:
    positions = trading.get_positions(user_id)
    total_mv = sum(float(p.get("marketValue") or 0) for p in positions) or 1.0
    out: list[dict] = []
    for p in positions:
        mv = float(p.get("marketValue") or 0)
        cost = float(p.get("avgCost") or 0) * int(p.get("qty") or 0)
        pnl = float(p.get("pnl") or 0)
        out.append(
            {
                "symbol": p.get("code"),
                "name": p.get("name") or p.get("code"),
                "value": mv,
                "percent": round(mv / total_mv * 100, 2),
                "cost": round(cost, 2),
                "currentPrice": float(p.get("price") or 0),
                "return": pnl,
                "returnPercent": float(p.get("pnlPct") or 0),
            }
        )
    return out


def recent_trades(user_id: str, limit: int = 10) -> list[dict]:
    limit = max(1, min(int(limit or 10), 50))
    rows = trading.list_trades(user_id, limit=limit)
    return [
        {
            "id": t["id"],
            "symbol": t["code"],
            "name": t.get("name") or t["code"],
            "side": t["side"],
            "quantity": t["qty"],
            "price": t["price"],
            "timestamp": t.get("tradedAt") or "",
        }
        for t in rows
    ]


def _trade_day(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        raw = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).date()
    except ValueError:
        return None


def return_curve(user_id: str, days: int = 30) -> list[dict]:
    """用成交现金流近似权益曲线，终点对齐当前 totalAssets。

    无历史盯市快照时这是诚实近似：按交易日累计买入/卖出现金流，
    最后一点强制为账户当前总资产。
    """
    days = max(1, min(int(days or 30), 365))
    account = trading.get_account(user_id)
    initial = float(account.get("initialCash") or 0)
    total_assets = float(account.get("totalAssets") or initial)
    trades = list(reversed(trading.list_trades(user_id, limit=1000)))
    cutoff = date.today() - timedelta(days=days)

    cash = initial
    by_day: dict[date, float] = {}
    for t in trades:
        day = _trade_day(t.get("tradedAt"))
        if day is None or day < cutoff:
            if day is not None and day < cutoff:
                # 窗口前成交仍影响起始现金
                amount = float(t.get("amount") or 0)
                fee = float(t.get("fee") or 0)
                tax = float(t.get("tax") or 0)
                if t.get("side") == "buy":
                    cash -= amount + fee
                else:
                    cash += amount - fee - tax
            continue
        amount = float(t.get("amount") or 0)
        fee = float(t.get("fee") or 0)
        tax = float(t.get("tax") or 0)
        if t.get("side") == "buy":
            cash -= amount + fee
        else:
            cash += amount - fee - tax
        by_day[day] = round(cash, 2)

    points = [
        {"date": day.isoformat(), "value": value}
        for day, value in sorted(by_day.items())
    ]
    today = date.today().isoformat()
    if not points:
        points = [{"date": today, "value": round(total_assets, 2)}]
    elif points[-1]["date"] != today:
        points.append({"date": today, "value": round(total_assets, 2)})
    else:
        points[-1]["value"] = round(total_assets, 2)
    return points
