"""盘前早报服务（Phase 2）。

设计取舍：早报基于**已落库的公开免费数据**离线装配成「数据包」，再交由 LLM
单轮合成（不联网、不调用实时工具），从根本上避免：① 实时源限流卡顿；② 模型杜撰。
免费源不覆盖的板块（隔夜外盘 / 宏观政策 / 机构研报）在数据包里显式标注缺口，
提示词要求模型如实说明而非编造。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.ai.compliance import enforce_compliance
from app.ai.orchestrator import run_completion_stream
from app.ai.prompts import MORNING_BRIEF_PROMPT
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.brief import MorningBrief
from app.models.extra import DragonTiger, NewsItem
from app.services import market, watchlist

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
_MISSING = ["隔夜全球市场（美股/港股/汇率/商品）", "国内宏观与政策", "机构研报观点"]


def _today() -> date:
    return datetime.now(_TZ).date()


# ---------- 数据装配（全部读已落库/缓存，绝不触发会阻塞的实时拉取） ----------


def _recent_news(codes: list[str], hours: int = 48, limit: int = 12) -> list[dict]:
    since = datetime.now(_TZ).replace(tzinfo=None) - timedelta(hours=hours)
    with SessionLocal() as session:
        stmt = (
            select(NewsItem)
            .where(NewsItem.published_at.is_not(None), NewsItem.published_at >= since)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        )
        if codes:
            stmt = stmt.where(NewsItem.code.in_(codes))
        rows = list(session.execute(stmt).scalars().all())
        if not rows:  # 落库新闻发布时间可能偏旧；放宽为「最近入库」兜底
            fallback = select(NewsItem).order_by(NewsItem.fetched_at.desc()).limit(limit)
            if codes:
                fallback = fallback.where(NewsItem.code.in_(codes))
            rows = list(
                session.execute(fallback)
                .scalars()
                .all()
            )
    out = []
    for r in rows:
        out.append(
            {
                "title": r.title,
                "source": r.source_name,
                "publishedAt": r.published_at.isoformat() if r.published_at else None,
                "code": r.code,
            }
        )
    return out


def _recent_dragon_tiger(days: int = 5, limit: int = 12) -> list[dict]:
    since = _today() - timedelta(days=days)
    with SessionLocal() as session:
        stmt = (
            select(DragonTiger)
            .where(DragonTiger.trade_date >= since)
            .order_by(DragonTiger.net_buy.desc().nullslast())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())
    return [
        {
            "code": r.code,
            "name": r.name,
            "date": r.trade_date.isoformat(),
            "reason": r.reason,
            "netBuy": float(r.net_buy) if r.net_buy is not None else None,
        }
        for r in rows
    ]


def build_data_pack(user_id: str | None) -> dict:
    # 早报生成必须是 cache/DB-only，不能在请求或定时任务中触发实时源阻塞抓取。
    indices = market.indices_snapshot()

    items = watchlist.list_items(user_id) if user_id else []
    rated = [i for i in items if i.get("changePercent") is not None]
    rated.sort(key=lambda i: i["changePercent"], reverse=True)
    top_gainers = rated[:5]
    top_losers = rated[-5:][::-1] if len(rated) > 5 else rated[::-1]

    capital_flow: list[dict] = []
    for it in items[:12]:
        rows = market.get_capital_flow(it["code"], limit=1)
        if rows:
            r0 = rows[0]
            capital_flow.append(
                {
                    "code": it["code"],
                    "name": it.get("name") or "",
                    "date": r0.get("date"),
                    "mainNet": r0.get("mainNet"),
                    "mainNetRatio": r0.get("mainNetRatio"),
                }
            )
    capital_flow.sort(
        key=lambda c: (c["mainNet"] if c["mainNet"] is not None else 0), reverse=True
    )

    watch_codes = [i["code"] for i in items]
    recent_dragon_tiger = _recent_dragon_tiger()
    recent_news = _recent_news(watch_codes)
    pack = {
        "tradeDate": _today().isoformat(),
        "generatedAt": datetime.now(_TZ).isoformat(),
        "scope": "user" if user_id else "global",
        "indices": indices,
        "watchlist": {
            "count": len(items),
            "topGainers": top_gainers,
            "topLosers": top_losers,
        },
        "capitalFlow": capital_flow,
        "dragonTiger": recent_dragon_tiger,
        "news": recent_news,
        "coverage": {
            "indices": bool(indices),
            "watchlist": bool(items),
            "capitalFlow": bool(capital_flow),
            "dragonTiger": bool(recent_dragon_tiger),
            "missing": _MISSING,
        },
    }
    return pack


def _fmt_pct(v) -> str:
    return f"{v:+.2f}%" if isinstance(v, (int, float)) else "—"


def render_data_pack_text(pack: dict) -> str:
    """把数据包渲染成给模型的可读文本（只含真实数据 + 明确的缺口标注）。"""
    lines: list[str] = []
    lines.append(f"【数据包】交易日 {pack['tradeDate']}，范围：{'自选股个性化' if pack['scope']=='user' else '全局市场'}")
    lines.append("")

    indices = pack.get("indices") or []
    if indices:
        lines.append("# 大盘指数（快照/最近收盘，免费源可能延迟）")
        for idx in indices:
            lines.append(
                f"- {idx.get('name','?')}: {idx.get('value','—')}（{_fmt_pct(idx.get('changePercent'))}）"
            )
    else:
        lines.append("# 大盘指数：暂无数据（实时源不可用且无落库快照）")
    lines.append("")

    wl = pack.get("watchlist") or {}
    if wl.get("count"):
        lines.append(f"# 自选股表现（共 {wl['count']} 只）")
        if wl.get("topGainers"):
            lines.append("涨幅居前：")
            for s in wl["topGainers"]:
                lines.append(f"- {s.get('name','')}({s['code']}): {_fmt_pct(s.get('changePercent'))} 现价 {s.get('price','—')}")
        if wl.get("topLosers"):
            lines.append("跌幅居前：")
            for s in wl["topLosers"]:
                lines.append(f"- {s.get('name','')}({s['code']}): {_fmt_pct(s.get('changePercent'))} 现价 {s.get('price','—')}")
    else:
        lines.append("# 自选股：无（全局早报，或用户未添加自选股）")
    lines.append("")

    cf = pack.get("capitalFlow") or []
    if cf:
        lines.append("# 自选股资金流（最近交易日，主力净额，单位元）")
        for c in cf:
            lines.append(f"- {c.get('name','')}({c['code']}): 主力净额 {c.get('mainNet','—')}（占比 {_fmt_pct(c.get('mainNetRatio'))}）{c.get('date','')}")
    else:
        lines.append("# 资金流：暂无落库数据")
    lines.append("")

    dt = pack.get("dragonTiger") or []
    if dt:
        lines.append("# 近期龙虎榜（净买额居前）")
        for d in dt[:10]:
            lines.append(f"- {d.get('name','')}({d['code']}) {d['date']}：{d.get('reason','')} 净买 {d.get('netBuy','—')}")
    else:
        lines.append("# 龙虎榜：暂无落库数据")
    lines.append("")

    news = pack.get("news") or []
    if news:
        lines.append("# 近期新闻/公告")
        for n in news:
            lines.append(f"- {n.get('publishedAt','')} [{n.get('source','')}] {n.get('title','')}")
    else:
        lines.append("# 新闻：暂无落库数据")
    lines.append("")

    lines.append("# 已知数据缺口（免费源未接入，请勿编造，需如实说明）")
    for m in pack["coverage"]["missing"]:
        lines.append(f"- {m}")

    lines.append("")
    lines.append("请基于以上**真实数据**生成今日盘前早报；数据包没有的内容一律按「暂无数据接入」处理。")
    return "\n".join(lines)


# ---------- 生成 / 落库 / 读取 ----------


def _persist(
    brief_id: str,
    user_id: str | None,
    trade_date: date,
    pack: dict,
    content: str,
    status: str,
    error: str | None = None,
) -> None:
    title = f"A股盘前早报 · {trade_date.isoformat()}"
    note = "数据来源：本平台已落库公开免费数据（指数/自选股/资金流/龙虎榜/新闻）；隔夜外盘与宏观政策暂未接入"
    with SessionLocal() as session:
        row = session.get(MorningBrief, brief_id)
        if row is None:
            row = MorningBrief(id=brief_id)
            session.add(row)
        row.user_id = user_id
        row.trade_date = trade_date
        row.status = status
        row.title = title
        row.content = content
        row.data_pack_json = json.dumps(pack, ensure_ascii=False, default=str)
        row.source_note = note
        row.model = settings.deepseek_model
        row.error = error
        session.commit()


def stream_generate(user_id: str | None):
    """流式生成并在结束时落库。产出文本分片（供 SSE）。"""
    brief_id = uuid.uuid4().hex
    trade_date = _today()
    pack = build_data_pack(user_id)
    content_text = render_data_pack_text(pack)

    acc: list[str] = []
    persisted = False

    def _save(status: str, error: str | None = None) -> None:
        nonlocal persisted
        if persisted:
            return
        persisted = True
        try:
            _persist(brief_id, user_id, trade_date, pack,
                     enforce_compliance("".join(acc)), status, error)
        except Exception as exc:  # noqa: BLE001
            logger.warning("早报落库失败: %s", exc)

    try:
        for piece in run_completion_stream(MORNING_BRIEF_PROMPT, content_text):
            acc.append(piece)
            yield piece
        _save("ready")
    except GeneratorExit:
        # 客户端断开：尽量把已生成的内容落库（标记 ready 以便复盘）
        _save("ready" if acc else "failed")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("早报生成失败: %s", exc)
        _save("failed", str(exc))
        yield f"\n\n⚠️ 早报生成出错：{exc}"


def generate(user_id: str | None = None) -> dict:
    """非流式生成（供调度器/脚本），返回早报记录 dict。"""
    text = "".join(stream_generate(user_id))
    latest = get_latest(user_id)
    return latest or {"content": text}


def _to_dict(row: MorningBrief, with_content: bool = True) -> dict:
    out = {
        "id": row.id,
        "userId": row.user_id,
        "tradeDate": row.trade_date.isoformat() if row.trade_date else None,
        "status": row.status,
        "title": row.title,
        "sourceNote": row.source_note,
        "model": row.model,
        "generatedAt": row.generated_at.isoformat() if row.generated_at else None,
    }
    if with_content:
        out["content"] = row.content
    return out


def get_latest(user_id: str | None) -> dict | None:
    with SessionLocal() as session:
        stmt = (
            select(MorningBrief)
            .where(MorningBrief.user_id == user_id, MorningBrief.status == "ready")
            .order_by(MorningBrief.generated_at.desc())
            .limit(1)
        )
        row = session.execute(stmt).scalar_one_or_none()
        return _to_dict(row) if row else None


def list_briefs(user_id: str | None, limit: int = 20) -> list[dict]:
    with SessionLocal() as session:
        stmt = (
            select(MorningBrief)
            .where(MorningBrief.user_id == user_id)
            .order_by(MorningBrief.generated_at.desc())
            .limit(limit)
        )
        rows = list(session.execute(stmt).scalars().all())
        return [_to_dict(r, with_content=False) for r in rows]


def get_brief(brief_id: str, user_id: str | None) -> dict | None:
    with SessionLocal() as session:
        row = session.get(MorningBrief, brief_id)
        if row is None or row.user_id != user_id:
            return None
        return _to_dict(row)


def generate_daily_global() -> None:
    """调度器入口：每日生成全局早报（user_id=None）。"""
    try:
        generate(None)
        logger.info("每日全局盘前早报已生成")
    except Exception as exc:  # noqa: BLE001
        logger.warning("每日全局早报生成失败: %s", exc)
