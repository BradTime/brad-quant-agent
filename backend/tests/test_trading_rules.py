"""trading_rules 共享规则层单测（纯函数，无 DB）——模拟交易与回测共用口径。"""

from datetime import UTC, date, datetime

from app.services import trading_rules as r


def test_commission_minimum():
    assert r.commission(1000) == 5.0  # 1000×0.00025=0.25 < 5 → 取最低 5


def test_commission_rate():
    assert r.commission(1_000_000) == 250.0  # 万 2.5


def test_stamp_tax_sell_only():
    assert r.stamp_tax(10_000, "sell", date(2023, 8, 27)) == 10.0
    assert r.stamp_tax(10_000, "buy", date(2023, 8, 27)) == 0.0


def test_stamp_tax_rate_changes_on_2023_08_28():
    assert r.stamp_tax(10_000, "sell", date(2023, 8, 27)) == 10.0
    assert r.stamp_tax(10_000, "sell", date(2023, 8, 28)) == 5.0
    assert r.stamp_tax(10_000, "sell", datetime(2023, 8, 28, 9, 30)) == 5.0


def test_stamp_tax_aware_datetime_uses_shanghai_trade_date():
    assert r.stamp_tax(
        10_000,
        "sell",
        datetime(2023, 8, 27, 15, 59, tzinfo=UTC),
    ) == 10.0
    assert r.stamp_tax(
        10_000,
        "sell",
        datetime(2023, 8, 27, 16, 0, tzinfo=UTC),
    ) == 5.0


def test_round_lot():
    assert r.round_lot(150) == 100
    assert r.round_lot(99) == 0
    assert r.round_lot(300) == 300
    assert r.round_lot(-50) == 0


def test_buy_total_includes_fee():
    # 100 股 @ 10 = 1000，佣金 max(0.25,5)=5 → 1005
    assert r.buy_total(10.0, 100) == 1005.0


def test_sell_proceeds_deducts_fee_and_tax():
    # 2023-08-28 后：1000 - 佣金5 - 印花税0.5 = 994.5
    assert r.sell_proceeds(10.0, 100, date(2024, 1, 2)) == 994.5


def test_price_limit_ratio_by_board_and_reform_date():
    assert r.price_limit_ratio("600000.SH") == 0.10  # 主板
    assert r.price_limit_ratio("300750.SZ", trade_date=date(2020, 8, 21)) == 0.10
    assert r.price_limit_ratio("300750.SZ", trade_date=date(2020, 8, 24)) == 0.20
    assert r.price_limit_ratio("688981.SH") == 0.20  # 科创板
    assert r.price_limit_ratio("689009.SH") == 0.20
    assert r.price_limit_ratio("430047.BJ") == 0.30
    assert r.price_limit_ratio("830799.BJ") == 0.30
    assert r.price_limit_ratio("920001.BJ") == 0.30
    assert r.price_limit_ratio("600000.SH", "ST浦发") == 0.05  # ST


def test_gem_reform_boundary_uses_shanghai_date_for_aware_datetime():
    assert r.price_limit_ratio(
        "300750.SZ",
        trade_date=datetime(2020, 8, 23, 15, 59, tzinfo=UTC),
    ) == 0.10
    assert r.price_limit_ratio(
        "300750.SZ",
        trade_date=datetime(2020, 8, 23, 16, 0, tzinfo=UTC),
    ) == 0.20


def test_registration_boards_have_no_limit_for_first_five_trading_days():
    list_date = date(2024, 1, 2)

    assert (
        r.price_limit_ratio(
            "688001.SH",
            trade_date=date(2024, 1, 8),
            list_date=list_date,
        )
        is None
    )
    assert r.price_limit_ratio(
        "688001.SH",
        trade_date=date(2024, 1, 9),
        list_date=list_date,
    ) == 0.20
    assert (
        r.price_limit_ratio(
            "301001.SZ",
            trade_date=date(2024, 1, 8),
            list_date=list_date,
        )
        is None
    )
    assert r.price_limit_ratio(
        "830001.BJ",
        trade_date=date(2024, 1, 8),
        list_date=date(2024, 1, 2),
    ) is None
    assert r.price_limit_ratio(
        "830001.BJ",
        trade_date=date(2024, 1, 9),
        list_date=date(2024, 1, 2),
    ) == 0.30
