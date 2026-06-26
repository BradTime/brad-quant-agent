"""A 股交易规则与费用（模拟交易 / 回测共用，保证口径一致）。

纯计算、无 IO/DB 依赖。规则（MVP）：
- 100 股整手；佣金万 2.5（最低 5 元）；卖出印花税千 1（过户费略）。
- 涨跌停：主板 ±10%、创业板(300)/科创板(688) ±20%、ST ±5%（回测撮合用）。

模拟交易（``trading.py``）与回测引擎（``app/backtest``）都从这里取常量与函数，
避免两套口径漂移。
"""

from __future__ import annotations

# 资金 / 整手
INITIAL_CASH = 1_000_000.0
LOT = 100

# 费用
COMMISSION_RATE = 0.00025
COMMISSION_MIN = 5.0
STAMP_TAX_RATE = 0.001  # 卖出印花税

# 涨跌停幅度（回测撮合用；模拟交易暂未启用）
PRICE_LIMIT_DEFAULT = 0.10  # 主板
PRICE_LIMIT_STAR_GEM = 0.20  # 科创板(688) / 创业板(300)
PRICE_LIMIT_ST = 0.05


def round_money(x: float) -> float:
    """金额统一两位小数。"""
    return round(float(x), 2)


def commission(amount: float) -> float:
    """佣金：成交额 × 费率，最低 5 元。"""
    return round(max(abs(amount) * COMMISSION_RATE, COMMISSION_MIN), 2)


def stamp_tax(amount: float, side: str) -> float:
    """印花税：仅卖出收取。"""
    return round(abs(amount) * STAMP_TAX_RATE, 2) if side == "sell" else 0.0


def round_lot(qty: int) -> int:
    """向下取整到整手（100 股）。负数归零。"""
    return max((int(qty) // LOT) * LOT, 0)


def buy_total(price: float, qty: int) -> float:
    """买入总成本（含佣金）。"""
    amount = price * qty
    return round_money(amount + commission(amount))


def sell_proceeds(price: float, qty: int) -> float:
    """卖出净得（扣佣金 + 印花税）。"""
    amount = price * qty
    return round_money(amount - commission(amount) - stamp_tax(amount, "sell"))


def price_limit_ratio(code: str, name: str = "") -> float:
    """涨跌停幅度：ST 5%、科创/创业板 20%、其余主板 10%。"""
    if "ST" in (name or "").upper():
        return PRICE_LIMIT_ST
    six = code.split(".")[0]
    if six.startswith(("688", "300")):
        return PRICE_LIMIT_STAR_GEM
    return PRICE_LIMIT_DEFAULT
