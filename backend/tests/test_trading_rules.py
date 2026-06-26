"""trading_rules 共享规则层单测（纯函数，无 DB）——模拟交易与回测共用口径。"""

from app.services import trading_rules as r


def test_commission_minimum():
    assert r.commission(1000) == 5.0  # 1000×0.00025=0.25 < 5 → 取最低 5


def test_commission_rate():
    assert r.commission(1_000_000) == 250.0  # 万 2.5


def test_stamp_tax_sell_only():
    assert r.stamp_tax(10_000, "sell") == 10.0  # 卖出印花税千 1
    assert r.stamp_tax(10_000, "buy") == 0.0


def test_round_lot():
    assert r.round_lot(150) == 100
    assert r.round_lot(99) == 0
    assert r.round_lot(300) == 300
    assert r.round_lot(-50) == 0


def test_buy_total_includes_fee():
    # 100 股 @ 10 = 1000，佣金 max(0.25,5)=5 → 1005
    assert r.buy_total(10.0, 100) == 1005.0


def test_sell_proceeds_deducts_fee_and_tax():
    # 1000 - 佣金5 - 印花税1 = 994
    assert r.sell_proceeds(10.0, 100) == 994.0


def test_price_limit_ratio():
    assert r.price_limit_ratio("600000.SH") == 0.10  # 主板
    assert r.price_limit_ratio("300750.SZ") == 0.20  # 创业板
    assert r.price_limit_ratio("688981.SH") == 0.20  # 科创板
    assert r.price_limit_ratio("600000.SH", "ST浦发") == 0.05  # ST
