"""Phase 0 data-ingestion CLI.

Examples:
    python -m app.cli migrate
    python -m app.cli init-db  # development compatibility only
    python -m app.cli ingest-instruments
    python -m app.cli ingest-daily --code 600000.SH --start 2024-01-01 --end 2024-12-31
    python -m app.cli ingest-minute --code 600000.SH --period 5 --start 2024-12-01 --end 2024-12-31
    python -m app.cli ingest-adjust --code 600000.SH --start 2020-01-01 --end 2024-12-31
    python -m app.cli quotes --codes 600000.SH,000001.SZ
"""

from __future__ import annotations

import argparse
from pathlib import Path

import alembic.command
from alembic.config import Config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant-agent-backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("migrate", help="运行 Alembic 迁移到 head（推荐）")
    sub.add_parser("init-db", help="仅开发兼容：用 create_all 创建当前表")

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

    p_status = sub.add_parser(
        "ingest-status-history",
        help="拉取单标的历史简称/ST 生效区间（PIT 回测）",
    )
    p_status.add_argument("--code", required=True)
    p_status.add_argument("--provider", default=None)

    p_status_batch = sub.add_parser(
        "backfill-status-history",
        help="批量回填历史 ST 状态；缺省处理所有自选股",
    )
    p_status_batch.add_argument(
        "--codes",
        default=None,
        help="逗号分隔，如 600848.SH,000001.SZ；缺省=所有自选股",
    )
    p_status_batch.add_argument("--provider", default=None)

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

    p_training = sub.add_parser("training", help="训练数据审计、构建与就绪检查")
    training_sub = p_training.add_subparsers(dest="training_cmd", required=True)
    training_sub.add_parser("audit", help="审计已批准训练候选")
    training_sub.add_parser("readiness", help="检查是否达到进入微调的规模门槛")
    p_training_build = training_sub.add_parser("build", help="构建并冻结数据集")
    p_training_build.add_argument("--version", required=True)
    p_training_export = training_sub.add_parser("export", help="验证并显示数据集位置")
    p_training_export.add_argument("--version", required=True)

    p_admin = sub.add_parser("admin", help="管理员引导与审计")
    admin_sub = p_admin.add_subparsers(dest="admin_cmd", required=True)
    admin_sub.add_parser("list", help="列出当前管理员（邮箱默认脱敏）")
    p_admin_inspect = admin_sub.add_parser("inspect", help="只读检查目标账户")
    p_admin_inspect.add_argument("--email", required=True)
    p_admin_promote = admin_sub.add_parser(
        "promote-existing",
        help="提升已验证既有账户；默认 dry-run，必须绑定 UUID 与环境",
    )
    p_admin_promote.add_argument("--email", required=True)
    p_admin_promote.add_argument("--expected-user-id", required=True)
    p_admin_promote.add_argument("--expect-environment", required=True)
    p_admin_promote.add_argument(
        "--apply", action="store_true", help="实际提交；缺省仅预演"
    )

    p_bf = sub.add_parser(
        "backfill",
        help="批量回填一组标的的 日K+复权+资金流+财务+新闻(+可选分钟K/龙虎榜)",
    )
    p_bf.add_argument("--codes", default=None, help="逗号分隔；缺省=所有自选股代码")
    p_bf.add_argument("--start", default=None, help="日K/复权起始日；缺省近 2 年")
    p_bf.add_argument("--end", default=None, help="日K/复权结束日；缺省今天")
    p_bf.add_argument("--minute", default=None, help="逗号分隔分钟周期(5,15,30,60)；缺省=不回填分钟（数据量大）")
    p_bf.add_argument("--minute-start", default=None, help="分钟K起始日；缺省最近 120 天（窗口更短防限流）")
    p_bf.add_argument(
        "--dragon-tiger",
        dest="dragon_tiger",
        action="store_true",
        default=True,
        help="批量结束后回填全市场龙虎榜（默认开启）",
    )
    p_bf.add_argument(
        "--no-dragon-tiger",
        dest="dragon_tiger",
        action="store_false",
        help="跳过龙虎榜回填",
    )
    p_bf.add_argument("--provider", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "migrate":
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        alembic.command.upgrade(config, "head")
        print("✅ Alembic 数据库迁移已升级到 head")
        return 0

    if args.cmd == "backfill-status-history":
        from app.services import ingest

        codes = (
            [code.strip() for code in args.codes.split(",") if code.strip()]
            if args.codes
            else ingest.watchlist_codes()
        )
        if not codes:
            print("没有可回填的标的（自选股为空，且未提供 --codes）")
            return 1
        rows = 0
        errors = 0
        for code in codes:
            try:
                count = ingest.ingest_status_history(code, args.provider)
                rows += count
                print(f"- {code}: {count} 个状态区间")
            except Exception as exc:  # noqa: BLE001
                errors += 1
                print(f"- {code}: 失败（{exc}）")
        prefix = "✅" if not errors else "❌"
        print(f"{prefix} 历史 ST 回填：{rows} 个区间；失败 {errors}")
        return 1 if errors else 0

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
            codes,
            start,
            end,
            args.provider,
            minute_periods=minute_periods,
            minute_start=minute_start,
            include_dragon_tiger=bool(args.dragon_tiger),
        )
        runs = s.get("runs") or []
        for run in runs:
            failed = run.get("failedDatasets") or []
            suffix = f"；失败数据集 {', '.join(failed)}" if failed else ""
            print(f"- {run.get('code')}: {run.get('status')}{suffix}")

        has_bad_run = any(run.get("status") in {"partial", "failed", "running"} for run in runs)
        has_errors = bool(s.get("errors"))
        prefix = "❌ 回填未完整完成" if (has_errors or has_bad_run) else "✅ 回填完成"
        msg = (
            f"{prefix}：日K {s['daily']}、复权 {s['adjust']}、资金流 {s['capital_flow']}、"
            f"财务 {s['financials']}、新闻 {s['news']}"
        )
        if args.dragon_tiger:
            msg += f"、龙虎榜 {s.get('dragon_tiger', 0)}"
        if minute_periods:
            msg += f"、分钟K {s['minute']}（周期 {','.join(minute_periods)} 自 {minute_start}）"
        msg += f"；失败 {s['errors']}"
        print(msg)
        return 1 if (has_errors or has_bad_run) else 0

    if args.cmd == "init-db":
        from app.db.init_db import init_db

        print("⚠️ init-db 仅用于开发兼容；部署和持久库请使用 `python -m app.cli migrate`")
        init_db()
        print("✅ 数据库表已创建")
        return 0

    if args.cmd == "rag-backfill":
        from app.services import rag

        stats = rag.backfill_all()
        print(f"✅ RAG 回填完成：新闻 {stats['news']} 块、历史早报 {stats['briefs']} 块")
        return 0

    if args.cmd == "training":
        import json

        from app.services import training_dataset

        if args.training_cmd == "audit":
            result = training_dataset.audit_candidates()
        elif args.training_cmd == "readiness":
            result = training_dataset.readiness()
        elif args.training_cmd == "build":
            result = training_dataset.build_dataset(args.version)
        else:
            result = training_dataset.dataset_info(args.version)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", result.get("checksumOk", True)) else 1

    if args.cmd == "admin":
        import json

        from app.services import admin_bootstrap

        try:
            if args.admin_cmd == "list":
                result = admin_bootstrap.list_admins()
            elif args.admin_cmd == "inspect":
                result = admin_bootstrap.inspect_account(args.email)
            else:
                result = admin_bootstrap.promote_existing(
                    email=args.email,
                    expected_user_id=args.expected_user_id,
                    expected_environment=args.expect_environment,
                    apply=bool(args.apply),
                )
        except admin_bootstrap.AdminBootstrapError as exc:
            print(
                json.dumps(
                    {"ok": False, "code": exc.code, "message": str(exc)},
                    ensure_ascii=False,
                )
            )
            return 1
        except Exception:  # noqa: BLE001
            print(
                json.dumps(
                    {
                        "ok": False,
                        "code": "ADMIN_OPERATION_FAILED",
                        "message": "管理员操作失败；请检查数据库与 migration",
                    },
                    ensure_ascii=False,
                )
            )
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
    elif args.cmd == "ingest-status-history":
        n = ingest.ingest_status_history(args.code, args.provider)
        print(f"✅ {args.code} 历史简称/ST 状态区间落库 {n} 条")
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
