from datetime import UTC, date, datetime
from decimal import Decimal

from scripts.bootstrap_prediction_market import (
    _adjust_values,
    _content_sha256,
    _daily_values,
)


def test_tushare_units_and_persisted_precision_hash_are_canonical():
    fetched_at = datetime(2026, 9, 11, tzinfo=UTC)
    daily = _daily_values(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260911",
                "open": 10.1,
                "high": 10.5,
                "low": 10.0,
                "close": 10.4,
                "vol": 123.45,
                "amount": 678.9,
            }
        ],
        fetched_at,
    )
    assert daily[0]["volume"] == 12_345
    assert daily[0]["amount"] == Decimal("678900.0")
    persisted = [
        {
            **daily[0],
            "open": Decimal("10.1000"),
            "high": Decimal("10.5000"),
            "low": Decimal("10.0000"),
            "close": Decimal("10.4000"),
            "amount": Decimal("678900.0000"),
            "fetched_at": fetched_at,
        }
    ]
    assert _content_sha256(daily) == _content_sha256(persisted)


def test_tushare_adjustment_factor_maps_to_hfq_multiplier():
    values = _adjust_values(
        [
            {
                "ts_code": "600000.SH",
                "trade_date": "20260911",
                "adj_factor": 2.345678,
            }
        ],
        datetime(2026, 9, 11, tzinfo=UTC),
    )
    assert values == [
        {
            "code": "600000.SH",
            "ex_date": date(2026, 9, 11),
            "adjust_factor": Decimal("2.345678"),
            "fore_adjust_factor": None,
            "back_adjust_factor": Decimal("2.345678"),
            "source": "tushare",
            "fetched_at": datetime(2026, 9, 11, tzinfo=UTC),
        }
    ]
