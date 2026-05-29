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

    args = parser.parse_args(argv)

    if args.cmd == "init-db":
        from app.db.init_db import init_db

        init_db()
        print("✅ 数据库表已创建")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
