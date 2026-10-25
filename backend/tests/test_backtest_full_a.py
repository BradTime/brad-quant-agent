from datetime import date
from types import SimpleNamespace

import pytest

from app.backtest import full_a, runner
from app.backtest.base import BacktestConfig
from app.backtest.data import Bar
from app.schemas.backtest import FullABacktestRequest
from app.services import backtest_run


def _config() -> BacktestConfig:
    return BacktestConfig(
        strategy_type="xs_momentum",
        params={"lookback": 2, "topN": 1, "target": 0.5},
        codes=[],
        start="2024-01-03",
        end="2024-01-04",
        initial_capital=1_000_000,
        slippage=0,
        max_participation=0.01,
        universe_mode="full_a_pit",
    )


def _row(code: str, day: date, close: float):
    return SimpleNamespace(
        code=code,
        trade_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000_000,
        amount=close * 1_000_000,
    )


def _patch_data(monkeypatch):
    days = [date(2024, 1, day) for day in range(1, 5)]
    monkeypatch.setattr(
        full_a,
        "_session_window",
        lambda start, end, warmup: (days, days[2:]),
    )
    monkeypatch.setattr(
        full_a, "_membership_codes", lambda run_dates: {"A", "B"}
    )
    monkeypatch.setattr(
        full_a,
        "_load_instrument_dates",
        lambda: {"A": date(2000, 1, 1), "B": date(2000, 1, 1)},
    )
    monkeypatch.setattr(
        full_a,
        "_load_adjustments",
        lambda codes, start, end: (
            {"A": [date(2024, 1, 1)], "B": [date(2024, 1, 1)]},
            {"A": [1.0], "B": [1.0]},
        ),
    )

    def membership(chunk):
        return (
            {day: {"A", "B"} for day in chunk},
            {day: {} for day in chunk},
            {day: "a" * 64 for day in chunk},
        )

    monkeypatch.setattr(full_a, "_load_membership", membership)
    loaded_chunks = []

    def bars(chunk, codes):
        assert codes == {"A", "B"}
        loaded_chunks.append(tuple(chunk))
        return [
            _row(code, day, 10 + index * step)
            for index, day in enumerate(chunk)
            for code, step in (("A", 1.0), ("B", 0.1))
        ]

    monkeypatch.setattr(full_a, "_load_bar_rows", bars)
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (
            [
                Bar(
                    code="000300.SH",
                    date=day,
                    open=100 + index,
                    high=100 + index,
                    low=100 + index,
                    close=100 + index,
                    volume=1,
                    amount=1,
                )
                for index, day in enumerate(days[2:])
            ],
            "full",
        ),
    )
    return loaded_chunks


def test_full_a_executor_reads_bounded_chunks_and_records_hashes(
    monkeypatch,
):
    loaded_chunks = _patch_data(monkeypatch)
    monkeypatch.setattr(
        full_a.settings, "full_a_backtest_chunk_sessions", 2
    )
    progress = []

    result = full_a.run_chunked(
        _config(),
        on_progress=lambda done, total: progress.append((done, total)),
    )

    assert loaded_chunks == [
        (date(2024, 1, 1), date(2024, 1, 2)),
        (date(2024, 1, 3), date(2024, 1, 4)),
    ]
    assert progress[0] == (0, 2)
    assert progress[-2:] == [(1, 2), (2, 2)]
    assert result["engine"] == "native-full-a-chunked"
    assert result["equityCurve"][0]["benchmark"] == 0.0
    assert len(result["dataQuality"]["dailyBarsSha256"]) == 64
    assert len(result["universeQuality"]["membershipSha256"]) == 64


def test_full_a_executor_checks_cancellation_during_dates(monkeypatch):
    _patch_data(monkeypatch)
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        return checks >= 3

    result = full_a.run_chunked(_config(), cancel_check=cancel)

    assert result["cancelled"] is True
    assert result["progressDone"] < result["progressTotal"]


def test_full_a_service_rechecks_cancel_before_persisting(monkeypatch):
    monkeypatch.setattr(
        full_a,
        "run_chunked",
        lambda *args, **kwargs: {
            "equityCurve": [{"date": "2024-01-02", "equity": 1_000_000}],
            "metrics": {},
        },
    )
    monkeypatch.setattr(
        backtest_run,
        "_save_run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("cancelled result persisted")
        ),
    )
    request = FullABacktestRequest.model_validate(
        {
            "strategyType": "xs_momentum",
            "params": {"lookback": 60, "topN": 3, "target": 0.95},
            "start": "2024-01-02",
            "end": "2024-01-03",
        }
    )
    result = backtest_run.run_full_a_and_save(
        "user-a",
        request,
        cancel_check=lambda: True,
    )
    assert result["cancelled"] is True


def test_full_a_hfq_extends_first_known_back_factor_backward():
    factor_dates = {"A": [date(2024, 1, 3), date(2024, 1, 4)]}
    factor_values = {"A": [2.0, 2.1]}
    assert (
        full_a._factor_at(
            "A",
            date(2024, 1, 1),
            factor_dates,
            factor_values,
        )
        == 2.0
    )
    with pytest.raises(ValueError, match="缺少后复权因子"):
        full_a._factor_at("B", date(2024, 1, 1), {}, {})


def test_full_a_rejects_incomplete_benchmark_dates(monkeypatch):
    _patch_data(monkeypatch)
    monkeypatch.setattr(
        runner,
        "load_benchmark_with_quality",
        lambda start, end: (
            [
                Bar(
                    code="000300.SH",
                    date=date(2024, 1, 3),
                    open=100,
                    high=100,
                    low=100,
                    close=100,
                    volume=1,
                    amount=1,
                )
            ],
            "full",
        ),
    )
    with pytest.raises(ValueError, match="基准日期覆盖不完整"):
        full_a.run_chunked(_config())
