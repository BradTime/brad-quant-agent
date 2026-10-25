from datetime import date

import exchange_calendars as xcals
import pytest

from app.backtest import runner
from app.backtest.base import BacktestConfig, Strategy
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine
from app.backtest.universe import (
    PITUniverseFilters,
    eligible_asof,
    expected_session_dates,
)


class _AlwaysFull(Strategy):
    def initialize(self, ctx) -> None:
        pass

    def handle_bar(self, ctx, bars) -> None:
        for code in bars:
            ctx.order_target_percent(code, 1.0)


class _CaptureUniverse(Strategy):
    def initialize(self, ctx) -> None:
        self.seen = []

    def handle_bar(self, ctx, bars) -> None:
        self.seen.append((ctx.current_date, ctx.universe, tuple(bars)))


def _sessions(end: str, count: int) -> list[date]:
    calendar = xcals.get_calendar("XSHG")
    sessions = calendar.sessions_in_range("2023-01-01", end)
    return [timestamp.date() for timestamp in sessions[-count:]]


def _bars(
    dates: list[date],
    *,
    amount: float = 60_000_000,
    status: str | None = "normal",
) -> list[Bar]:
    return [
        Bar(
            code="600000.SH",
            date=day,
            open=10,
            high=10,
            low=10,
            close=10,
            volume=1_000_000,
            amount=amount,
            status_type=status,
        )
        for day in dates
    ]


def test_pit_universe_accepts_mature_liquid_audited_normal_stock():
    dates = _sessions("2024-12-31", 140)
    result = eligible_asof(
        as_of=dates[-1],
        bars=_bars(dates),
        list_date=dates[-120],
        data_quality="full",
    )
    assert result.eligible
    assert result.reasons == ()
    assert result.listing_sessions == 120
    assert result.average_amount == 60_000_000


def test_pit_universe_rejects_st_low_liquidity_and_missing_coverage():
    dates = _sessions("2024-12-31", 140)
    bars = _bars(dates, amount=49_900_000)
    bars[-1].status_type = "st"
    result = eligible_asof(
        as_of=dates[-1],
        bars=bars,
        list_date=dates[-119],
        data_quality="partial_ingestion",
    )
    assert not result.eligible
    assert set(result.reasons) == {
        "young_listing",
        "bad_data",
        "st",
        "low_liquidity",
    }


def test_future_bars_do_not_change_past_liquidity_or_status_membership():
    dates = _sessions("2025-01-31", 141)
    as_of = dates[-2]
    bars = _bars(dates[:-1], amount=60_000_000)
    before = eligible_asof(
        as_of=as_of,
        bars=bars,
        list_date=dates[-130],
        data_quality="full",
    )
    future = _bars([dates[-1]], amount=1, status="star_st")[0]
    after = eligible_asof(
        as_of=as_of,
        bars=[*bars, future],
        list_date=dates[-130],
        data_quality="full",
    )
    assert before == after
    assert before.eligible


def test_missing_day_bar_is_treated_as_suspended():
    dates = _sessions("2024-12-31", 140)
    result = eligible_asof(
        as_of=dates[-1],
        bars=_bars(dates[:-1]),
        list_date=dates[-130],
        data_quality="full",
    )
    assert not result.eligible
    assert "suspended" in result.reasons


def test_status_coverage_can_only_be_relaxed_explicitly():
    dates = _sessions("2024-12-31", 140)
    strict = eligible_asof(
        as_of=dates[-1],
        bars=_bars(dates, status=None),
        list_date=dates[-130],
        data_quality="full",
    )
    relaxed = eligible_asof(
        as_of=dates[-1],
        bars=_bars(dates, status=None),
        list_date=dates[-130],
        data_quality="full",
        filters=PITUniverseFilters(require_status_coverage=False),
    )
    assert "pit_status_missing" in strict.reasons
    assert relaxed.eligible


def test_delisting_status_is_excluded_without_using_current_snapshot():
    dates = _sessions("2024-12-31", 140)
    bars = _bars(dates)
    bars[-1].status_type = "delisting"
    result = eligible_asof(
        as_of=dates[-1],
        bars=bars,
        list_date=dates[-130],
        data_quality="full",
    )
    assert result.reasons == ("delisting",)


def test_engine_uses_daily_membership_and_exits_after_ineligibility():
    days = [date(2024, 1, day) for day in range(1, 5)]
    bars = _bars(days)
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["600000.SH"],
        start=days[0].isoformat(),
        end=days[-1].isoformat(),
        initial_capital=1_000_000,
        slippage=0,
        max_participation=1,
        universe_mode="pit_filtered",
        eligible_by_date={
            days[0].isoformat(): ("600000.SH",),
            days[1].isoformat(): ("600000.SH",),
            days[2].isoformat(): (),
            days[3].isoformat(): (),
        },
    )
    result = NativeEngine().run(config, _AlwaysFull(), {"600000.SH": bars})
    assert [(fill.side, fill.date) for fill in result.fills] == [
        ("buy", days[1]),
        ("sell", days[3]),
    ]


def test_membership_clock_advances_when_all_selected_symbols_lack_bar():
    days = [date(2024, 1, day) for day in range(1, 5)]
    bars = _bars([days[0], days[1], days[3]])
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["600000.SH"],
        start=days[0].isoformat(),
        end=days[-1].isoformat(),
        initial_capital=1_000_000,
        slippage=0,
        max_participation=1,
        universe_mode="pit_filtered",
        eligible_by_date={
            days[0].isoformat(): ("600000.SH",),
            days[1].isoformat(): ("600000.SH",),
            days[2].isoformat(): (),
            days[3].isoformat(): (),
        },
    )
    strategy = _CaptureUniverse()
    NativeEngine().run(config, strategy, {"600000.SH": bars})
    assert strategy.seen[2] == (days[2], (), ())


def test_runner_rejects_wholly_missing_materialized_market_day(monkeypatch):
    day = date(2024, 1, 2)
    bars = _bars([day])
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["600000.SH"],
        start="2024-01-02",
        end="2024-01-03",
        universe_mode="pit_filtered",
        eligible_by_date={"2024-01-02": ("600000.SH",)},
    )
    monkeypatch.setattr(
        runner,
        "load_bars",
        lambda _config: ({"600000.SH": bars}, {"600000.SH": "full"}),
    )
    result = runner.run_backtest(config)
    assert "缺少 2024-01-03" in result["error"]


def test_calendar_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(
        xcals,
        "get_calendar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("calendar unavailable")
        ),
    )
    with pytest.raises(RuntimeError, match="PIT 过滤已拒绝"):
        expected_session_dates(date(2024, 1, 1), date(2024, 1, 2))
