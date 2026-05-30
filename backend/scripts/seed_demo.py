"""为本地体验批量落库一批代表性个股，并给指定用户预置分组自选股。

用法（backend 目录、已激活 venv）：
    python scripts/seed_demo.py                 # 默认用户 me@test.com
    python scripts/seed_demo.py --email you@x.com
    python scripts/seed_demo.py --no-watchlist  # 只落数据，不动自选股

说明：
- 每只股票落库 日K(约400天) + 资金流 + 财务摘要 + 新闻（资金流/新闻走东方财富，限流时可能为 0，可稍后重试）。
- 自选股按 user_id 隔离，重复执行幂等（已存在则跳过）。
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 分组 -> 代码列表（A 股代表性个股，跨行业）
GROUPS: dict[str, list[str]] = {
    "银行金融": ["600000.SH", "600036.SH", "000001.SZ", "601318.SH"],
    "白酒消费": ["600519.SH", "000858.SZ", "600887.SH"],
    "新能源": ["300750.SZ", "002594.SZ", "601012.SH"],
    "科技电子": ["002415.SZ", "300059.SZ", "002475.SZ"],
    "医药": ["600276.SH"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="me@test.com")
    parser.add_argument("--no-watchlist", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.user import User
    from app.services import market, watchlist

    all_codes = [c for codes in GROUPS.values() for c in codes]
    print(f"开始落库 {len(all_codes)} 只个股（日K/资金流/财务/新闻）…\n")
    for code in all_codes:
        try:
            r = market.refresh_stock(code)
            print(f"  {code}: 日K={r.get('daily')} 资金流={r.get('capitalFlow')} 财务={r.get('financials')} 新闻={r.get('news')}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {code}: ⚠️ 落库失败 {exc}")

    if args.no_watchlist:
        print("\n（跳过自选股预置）")
        return 0

    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.email == args.email.strip().lower())
        ).scalar_one_or_none()

    if user is None:
        print(f"\n⚠️ 未找到用户 {args.email}（请先在前端注册该邮箱），已跳过自选股预置。")
        return 0

    print(f"\n为用户 {args.email} 预置自选股…")
    added = 0
    for group, codes in GROUPS.items():
        for code in codes:
            res = watchlist.add_item(str(user.id), code, group=group)
            if res.get("added"):
                added += 1
    print(f"✅ 自选股预置完成（新增 {added} 只，已存在的跳过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
