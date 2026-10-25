from datetime import UTC, date, datetime
from decimal import Decimal

import httpx

from scripts.bootstrap_prediction_market import (
    _adjust_values,
    _content_sha256,
    _daily_values,
    _request,
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


def test_tushare_request_retries_transient_timeout(monkeypatch):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary", request=request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "fields": ["ts_code"],
                    "items": [["600000.SH"]],
                },
            },
        )

    monkeypatch.setattr("scripts.bootstrap_prediction_market.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = _request(client, "daily", {}, ("ts_code",))
    assert attempts == 2
    assert rows == [{"ts_code": "600000.SH"}]
