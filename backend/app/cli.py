"""Phase 0 data-ingestion CLI.

Examples:
    python -m app.cli init-db
    python -m app.cli ingest-instruments
    python -m app.cli ingest-daily --code 600000.SH --start 2024-01-01 --end 2024-12-31
    python -m app.cli ingest-minute --code 600000.SH --period 5 --start 2024-12-01 --end 2024-12-31
    python -m app.cli ingest-adjust --code 600000.SH --start 2020-01-01 --end 2024-12-31
    python -m app.cli quotes --codes 600000.SH,000001.SZ
"""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-agent-backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="创建数据库表")

    p_inst = sub.add_parser("ingest-instruments", help="拉取并落库标的列表")
    p_inst.add_argument("--provider", default=None)

    p_daily = sub.add_parser("ingest-daily", help="拉取并落库日K线（不复权）")
    p_daily.add_argument("--code", required=True)
    p_daily.add_argument("--start", required=True)
    p_daily.add_argument("--end", required=True)
    p_daily.add_argument("--adjust", default="none", choices=["none", "qfq", "hfq"])
    p_daily.add_argument("--provider", default=None)

    p_min = sub.add_parser("ingest-minute", help="拉取并落库分钟K线")
    p_min.add_argument("--code", required=True)
    p_min.add_argument("--period", required=True, choices=["5", "15", "30", "60"])
    p_min.add_argument("--start", required=True)
    p_min.add_argument("--end", required=True)
    p_min.add_argument("--provider", default=None)

    p_adj = sub.add_parser("ingest-adjust", help="拉取并落库复权因子")
    p_adj.add_argument("--code", required=True)
    p_adj.add_argument("--start", required=True)
    p_adj.add_argument("--end", required=True)
    p_adj.add_argument("--provider", default=None)

    p_q = sub.add_parser("quotes", help="拉取实时快照（不落库，用于连通性验证）")
    p_q.add_argument("--codes", required=True, help="逗号分隔，如 600000.SH,000001.SZ")
    p_q.add_argument("--provider", default=None)

    p_cf = sub.add_parser("ingest-capital-flow", help="拉取并落库个股资金流")
    p_cf.add_argument("--code", required=True)
    p_cf.add_argument("--provider", default=None)

    p_fin = sub.add_parser("ingest-financials", help="拉取并落库财务摘要")
    p_fin.add_argument("--code", required=True)
    p_fin.add_argument("--provider", default=None)

    p_lhb = sub.add_parser("ingest-dragon-tiger", help="拉取并落库龙虎榜")
    p_lhb.add_argument("--start", required=True)
    p_lhb.add_argument("--end", required=True)
    p_lhb.add_argument("--provider", default=None)

    p_news = sub.add_parser("ingest-news", help="拉取并落库个股新闻/公告")
    p_news.add_argument("--code", required=True)
    p_news.add_argument("--limit", type=int, default=30)
    p_news.add_argument("--provider", default=None)

    sub.add_parser("rag-backfill", help="把已落库新闻/历史早报向量化灌入 RAG 检索库")

    p_bf = sub.add_parser("backfill", help="批量回填一组标的的 日K+复权+资金流+财务+新闻(+可选分钟K)")
    p_bf.add_argument("--codes", default=None, help="逗号分隔；缺省=所有自选股代码")
    p_bf.add_argument("--start", default=None, help="日K/复权起始日；缺省近 2 年")
    p_bf.add_argument("--end", default=None, help="日K/复权结束日；缺省今天")
    p_bf.add_argument("--minute", default=None, help="逗号分隔分钟周期(5,15,30,60)；缺省=不回填分钟（数据量大）")
    p_bf.add_argument("--minute-start", default=None, help="分钟K起始日；缺省最近 120 天（窗口更短防限流）")
    p_bf.add_argument("--provider", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "backfill":
        from datetime import date, timedelta

        from app.services import ingest

        codes = (
            [c.strip() for c in args.codes.split(",") if c.strip()]
            if args.codes
            else ingest.watchlist_codes()
        )
        if not codes:
            print("没有可回填的标的（自选股为空，且未提供 --codes）")
            return 1
        end = args.end or date.today().isoformat()
        start = args.start or (date.today() - timedelta(days=730)).isoformat()

        minute_periods = None
        minute_start = args.minute_start
        if args.minute:
            valid = {"5", "15", "30", "60"}
            minute_periods = [p.strip() for p in args.minute.split(",") if p.strip()]
            bad = [p for p in minute_periods if p not in valid]
            if bad:
                print(f"非法分钟周期 {bad}，仅支持 5/15/30/60")
                return 1
            if not minute_start:
                minute_start = (date.today() - timedelta(days=120)).isoformat()

        print(f"开始回填 {len(codes)} 个标的（{start} ~ {end}）…")
        s = ingest.backfill_codes(
            codes, start, end, args.provider,
            minute_periods=minute_periods, minute_start=minute_start,
        )
        msg = (
            f"✅ 回填完成：日K {s['daily']}、复权 {s['adjust']}、资金流 {s['capital_flow']}、"
            f"财务 {s['financials']}、新闻 {s['news']}"
        )
        if minute_periods:
            msg += f"、分钟K {s['minute']}（周期 {','.join(minute_periods)} 自 {minute_start}）"
        msg += f"；失败 {s['errors']}"
        print(msg)
        return 0

    if args.cmd == "init-db":
        from app.db.init_db import init_db

        init_db()
        print("✅ 数据库表已创建")
        return 0

    if args.cmd == "rag-backfill":
        from app.services import rag

        stats = rag.backfill_all()
        print(f"✅ RAG 回填完成：新闻 {stats['news']} 块、历史早报 {stats['briefs']} 块")
        return 0

    from app.services import ingest

    if args.cmd == "ingest-instruments":
        n = ingest.ingest_instruments(args.provider)
        print(f"✅ 标的落库 {n} 条")
    elif args.cmd == "ingest-daily":
        n = ingest.ingest_daily(args.code, args.start, args.end, args.adjust, args.provider)
        print(f"✅ {args.code} 日K落库 {n} 条")
    elif args.cmd == "ingest-minute":
        n = ingest.ingest_minute(args.code, args.period, args.start, args.end, args.provider)
        print(f"✅ {args.code} {args.period}分钟K落库 {n} 条")
    elif args.cmd == "ingest-adjust":
        n = ingest.ingest_adjust(args.code, args.start, args.end, args.provider)
        print(f"✅ {args.code} 复权因子落库 {n} 条")
    elif args.cmd == "quotes":
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
        quotes = ingest.fetch_quotes(codes, args.provider)
        for q in quotes:
            print(f"{q.code} {q.name} 价:{q.price} 涨跌幅:{q.change_percent}%")
        print(f"（共 {len(quotes)} 条）")
    elif args.cmd == "ingest-capital-flow":
        n = ingest.ingest_capital_flow(args.code, args.provider)
        print(f"✅ {args.code} 资金流落库 {n} 条")
    elif args.cmd == "ingest-financials":
        n = ingest.ingest_financials(args.code, args.provider)
        print(f"✅ {args.code} 财务摘要落库 {n} 条")
    elif args.cmd == "ingest-dragon-tiger":
        n = ingest.ingest_dragon_tiger(args.start, args.end, args.provider)
        print(f"✅ 龙虎榜落库 {n} 条")
    elif args.cmd == "ingest-news":
        n = ingest.ingest_news(args.code, args.limit, args.provider)
        print(f"✅ {args.code} 新闻落库 {n} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
