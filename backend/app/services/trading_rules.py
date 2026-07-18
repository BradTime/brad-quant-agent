"""A 股交易规则与费用（模拟交易 / 回测共用，保证口径一致）。

纯计算、无 IO/DB 依赖。规则：
- 100 股整手；佣金万 2.5（最低 5 元）；卖出印花税 2023-08-28 起
  由 1‰ 降至 0.5‰（过户费略）。
- 涨跌停按交易日适用历史制度：主板 10%、主板 ST 5%、创业板改革前 10%/
  改革后 20%、科创板(688/689) 20%、北交所 30%；注册制板块上市前五个
  XSHG 中国交易日无涨跌停。

模拟交易（``trading.py``）与回测引擎（``app/backtest``）都从这里取常量与函数，
避免两套口径漂移。
"""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

# 资金 / 整手
INITIAL_CASH = 1_000_000.0
LOT = 100

# 费用
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_TAX_CUTOVER = date(2023, 8, 28)
STAMP_TAX_RATE_BEFORE = 0.001
STAMP_TAX_RATE_CURRENT = 0.0005
# 兼容只读展示；成交计算必须调用 ``stamp_tax`` 并传成交日。
STAMP_TAX_RATE = STAMP_TAX_RATE_CURRENT

# 涨跌停幅度
PRICE_LIMIT_DEFAULT = 0.10  # 主板
PRICE_LIMIT_STAR_GEM = 0.20  # 科创板 / 注册制创业板
PRICE_LIMIT_ST = 0.05
PRICE_LIMIT_BSE = 0.30
GEM_REFORM_DATE = date(2020, 8, 24)
NO_LIMIT_SESSIONS = 5
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def round_money(x: float) -> float:
    """金额统一两位小数。"""
    return round(float(x), 2)


def commission(amount: float) -> float:
    """佣金：成交额 × 费率，最低 5 元。"""
    return round(max(abs(amount) * COMMISSION_RATE, COMMISSION_MIN), 2)


def _as_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            value = value.astimezone(_SHANGHAI)
        return value.date()
    return value


def stamp_tax(amount: float, side: str, trade_date: date | datetime) -> float:
    """印花税：仅卖出，成交日决定 1‰ / 0.5‰ 历史税率。"""
    if side != "sell":
        return 0.0
    day = _as_date(trade_date)
    rate = STAMP_TAX_RATE_CURRENT if day >= STAMP_TAX_CUTOVER else STAMP_TAX_RATE_BEFORE
    return round(abs(amount) * rate, 2)


def round_lot(qty: int) -> int:
    """向下取整到整手（100 股）。负数归零。"""
    return max((int(qty) // LOT) * LOT, 0)


def buy_total(price: float, qty: int) -> float:
    """买入总成本（含佣金）。"""
    amount = price * qty
    return round_money(amount + commission(amount))


def sell_proceeds(price: float, qty: int, trade_date: date | datetime) -> float:
    """卖出净得（扣佣金 + 印花税）。"""
    amount = price * qty
    return round_money(amount - commission(amount) - stamp_tax(amount, "sell", trade_date))


def _is_bse(code: str, six: str) -> bool:
    exchange = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    return exchange == "BJ" or six.startswith(("4", "8", "92"))


@lru_cache(maxsize=1)
def _calendar():
    import exchange_calendars as xcals

    # 北交所免费日历的早期覆盖与沪深市场不一致；A 股首五交易日统一按
    # 中国 XSHG 交易日序列计数，避免把开市日漏掉。
    return xcals.get_calendar("XSHG")


def _within_first_sessions(
    trade_date: date,
    list_date: date,
    count: int = NO_LIMIT_SESSIONS,
) -> bool:
    if trade_date < list_date:
        return False
    try:
        sessions = _calendar().sessions_in_range(list_date.isoformat(), trade_date.isoformat())
    except (ValueError, RuntimeError):
        return False
    return 0 < len(sessions) <= count


def price_limit_ratio(
    code: str,
    name: str = "",
    trade_date: date | datetime | None = None,
    list_date: date | datetime | None = None,
) -> float | None:
    """返回当日涨跌停比例；上市前五个交易日无涨跌停时返回 ``None``。

    ``name`` 只应传入当日可得的 PIT 名称/状态。历史状态缺失时不要传当前名称，
    以免把当前 ST 倒灌到历史。
    """
    six = code.split(".")[0]
    day = _as_date(trade_date)
    listed = _as_date(list_date)
    is_star = six.startswith(("688", "689"))
    is_gem = six.startswith(("300", "301"))
    is_bse = _is_bse(code, six)

    if is_bse:
        ratio = PRICE_LIMIT_BSE
        registration_board = True
    elif is_star:
        ratio = PRICE_LIMIT_STAR_GEM
        registration_board = True
    elif is_gem:
        ratio = (
            PRICE_LIMIT_DEFAULT
            if day is not None and day < GEM_REFORM_DATE
            else PRICE_LIMIT_STAR_GEM
        )
        registration_board = day is None or day >= GEM_REFORM_DATE
    elif "ST" in (name or "").upper():
        ratio = PRICE_LIMIT_ST
        registration_board = False
    else:
        ratio = PRICE_LIMIT_DEFAULT
        registration_board = False

    if (
        registration_board
        and day is not None
        and listed is not None
        and (not is_gem or listed >= GEM_REFORM_DATE)
        and _within_first_sessions(day, listed)
    ):
        return None
    return ratio
