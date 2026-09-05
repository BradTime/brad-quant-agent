"""行情新鲜度、交易时段与 API/WS 透传门禁测试。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.api.v1 import market as market_api
from app.providers.base import QuoteDTO
from app.services import market
from app.services.quote_cache import QuoteCache
from app.ws import broadcaster

SHANGHAI = ZoneInfo("Asia/Shanghai")
OPEN_NOW = datetime(2026, 7, 17, 10, 0, tzinfo=SHANGHAI)  # Friday
CLOSED_NOW = datetime(2026, 7, 17, 16, 0, tzinfo=SHANGHAI)


def _quote(*, ts: datetime, price: float = 10.0) -> QuoteDTO:
    return QuoteDTO(
        code="600000.SH",
        name="浦发银行",
        price=price,
        change=0.1,
        change_percent=1.0,
        ts=ts,
        event_time_reliable=True,
    )


def _snapshot(
    *,
    now: datetime = OPEN_NOW,
    quote_age: int = 10,
    cache_age: int = 5,
    price: float = 10.0,
) -> dict:
    quote = _quote(ts=now - timedelta(seconds=quote_age), price=price)
    return market._quote_to_stock(
        quote,
        cache_refreshed_at=(now - timedelta(seconds=cache_age)).timestamp(),
        now=now,
    )


def test_fresh_quote_during_open_session_is_executable(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)

    snapshot = _snapshot()

    assert snapshot["asOf"] == int((OPEN_NOW - timedelta(seconds=10)).timestamp() * 1000)
    assert snapshot["ageMs"] == 10_000
    assert snapshot["maxAgeMs"] == 60_000
    assert snapshot["stale"] is False
    assert snapshot["staleReason"] is None
    assert snapshot["executable"] is True


def test_quote_timestamp_expiry_blocks_execution(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)

    snapshot = _snapshot(quote_age=61)

    assert snapshot["ageMs"] == 61_000
    assert snapshot["stale"] is True
    assert snapshot["staleReason"] == "quote_expired"
    assert snapshot["executable"] is False


def test_cache_refresh_expiry_also_blocks_execution(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)

    snapshot = _snapshot(quote_age=1, cache_age=61)

    assert snapshot["ageMs"] == 61_000
    assert snapshot["stale"] is True
    assert snapshot["staleReason"] == "cache_expired"
    assert snapshot["executable"] is False


def test_market_closed_blocks_otherwise_fresh_quote(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)

    snapshot = _snapshot(now=CLOSED_NOW, quote_age=1, cache_age=1)

    assert snapshot["stale"] is False
    assert snapshot["staleReason"] == "market_closed"
    assert snapshot["executable"] is False


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 7, 17, 9, 30, tzinfo=SHANGHAI), True),
        (datetime(2026, 7, 17, 11, 31, tzinfo=SHANGHAI), False),
        (datetime(2026, 7, 17, 13, 0, tzinfo=SHANGHAI), True),
        (datetime(2026, 7, 18, 10, 0, tzinfo=SHANGHAI), False),
    ],
)
def test_a_share_trading_session_uses_shanghai_weekday_hours(now, expected):
    assert market.is_a_share_trading_session(now) is expected


def test_a_share_trading_session_rejects_exchange_holiday():
    national_day = datetime(2026, 10, 1, 10, 0, tzinfo=SHANGHAI)

    assert market.is_a_share_trading_session(national_day) is False


def test_unreliable_exchange_event_time_is_never_executable(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)
    quote = _quote(ts=OPEN_NOW - timedelta(seconds=1))
    quote.event_time_reliable = False

    snapshot = market._quote_to_stock(
        quote,
        cache_refreshed_at=(OPEN_NOW - timedelta(seconds=1)).timestamp(),
        now=OPEN_NOW,
    )

    assert snapshot["staleReason"] == "unverified_event_time"
    assert snapshot["executable"] is False


def test_non_positive_price_is_not_executable(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)

    snapshot = _snapshot(price=0)

    assert snapshot["staleReason"] == "invalid_price"
    assert snapshot["executable"] is False


class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def all(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class _LastCloseSession:
    def __init__(self, rows, name: str):
        self.rows = rows
        self.name = name
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, _stmt):
        self.calls += 1
        return _Result(self.rows if self.calls == 1 else self.name)


def test_database_last_close_is_display_only_and_never_executable(monkeypatch):
    last = SimpleNamespace(
        trade_date=date(2026, 7, 16),
        open=9.8,
        high=10.2,
        low=9.7,
        close=10.0,
        volume=1000,
        amount=10_000,
    )
    previous = SimpleNamespace(close=9.5)
    fake_session = _LastCloseSession([last, previous], "浦发银行")
    monkeypatch.setattr(market, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(market, "_now", lambda: OPEN_NOW, raising=False)

    snapshot = market._last_close_quote("600000.SH")

    expected_as_of = datetime.combine(last.trade_date, time(15, 0), tzinfo=SHANGHAI)
    assert snapshot["asOf"] == int(expected_as_of.timestamp() * 1000)
    assert snapshot["stale"] is True
    assert snapshot["staleReason"] == "last_close"
    assert snapshot["executable"] is False


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def test_http_and_ws_payloads_include_quote_state_without_reusing_send_time(monkeypatch):
    monkeypatch.setattr(market.settings, "quote_trade_max_age_seconds", 60)
    monkeypatch.setattr(market, "_now", lambda: OPEN_NOW, raising=False)
    cache = QuoteCache()
    data_as_of = OPEN_NOW - timedelta(seconds=10)
    cache.set_stocks([_quote(ts=data_as_of)], refreshed_at=OPEN_NOW.timestamp())
    monkeypatch.setattr(market.quote_cache, "cache", cache)

    response = market_api.quote("600000.SH", _user=object())
    http_payload = response["data"]
    ws_payload = broadcaster._payload_for("market.quote.600000.SH", {})
    required = {"asOf", "ageMs", "maxAgeMs", "stale", "staleReason", "executable"}
    assert required <= http_payload.keys()
    assert required <= ws_payload.keys()

    ws = _FakeWS()
    send_time = int(OPEN_NOW.timestamp() * 1000) + 30_000
    asyncio.run(broadcaster._send(ws, "market.quote.600000.SH", ws_payload, send_time))
    assert ws.sent[0]["timestamp"] == send_time
    assert ws.sent[0]["payload"]["asOf"] == int(data_as_of.timestamp() * 1000)
    assert ws.sent[0]["payload"]["asOf"] != ws.sent[0]["timestamp"]


def test_realtime_fetch_switch_prevents_provider_call(monkeypatch):
    called = False

    def provider_call():
        nonlocal called
        called = True
        return ["unexpected"]

    monkeypatch.setattr(market.settings, "enable_realtime_fetch", False)

    assert market._fetch_with_timeout("quotes:test", provider_call, 1, "test") is None
    assert called is False
