from datetime import date

import pytest
from pydantic import ValidationError

from app.backtest import runner
from app.backtest.base import BacktestConfig
from app.backtest.context import panel_history_from_data
from app.backtest.data import Bar
from app.backtest.engines.native import NativeEngine
from app.backtest.strategies.flow_surge import FlowSurge
from app.backtest.strategies.fundamental_quality import FundamentalQuality
from app.services import backtest_run


def _bars(code: str, start: int = 2, end: int = 5) -> list[Bar]:
    return [
        Bar(
            code=code,
            date=date(2024, 1, day),
            open=10,
            high=10,
            low=10,
            close=10,
            volume=10_000_000,
            amount=100_000_000,
        )
        for day in range(start, end + 1)
    ]


def test_panel_history_selects_latest_vintage_available_asof():
    panels = {
        "capital_flow": {
            "X": [
                {
                    "date": "2024-01-02",
                    "availableAt": "2024-01-02T08:00:00+00:00",
                    "mainNetRatio": 5.0,
                },
                {
                    "date": "2024-01-02",
                    "availableAt": "2024-01-04T08:00:00+00:00",
                    "mainNetRatio": 9.0,
                },
            ]
        }
    }
    old = panel_history_from_data(
        panels, "X", "capital_flow", 1, date(2024, 1, 3)
    )
    revised = panel_history_from_data(
        panels, "X", "capital_flow", 1, date(2024, 1, 4)
    )
    assert old[0]["mainNetRatio"] == 5.0
    assert revised[0]["mainNetRatio"] == 9.0


def test_flow_surge_requires_current_consecutive_visible_rows():
    panels = {
        "capital_flow": {
            "X": [
                {
                    "date": "2024-01-02",
                    "availableAt": "2024-01-02T08:00:00+00:00",
                    "mainNetRatio": 6.0,
                },
                {
                    "date": "2024-01-03",
                    "availableAt": "2024-01-03T08:00:00+00:00",
                    "mainNetRatio": 7.0,
                },
            ]
        }
    }
    config = BacktestConfig(
        strategy_type="flow_surge",
        params={"window": 2, "minRatio": 5.0, "target": 0.5},
        codes=["X"],
        start="2024-01-02",
        end="2024-01-05",
        initial_capital=1_000_000,
        slippage=0,
        max_participation=1,
        auxiliary_panels=panels,
    )
    result = NativeEngine().run(config, FlowSurge(), {"X": _bars("X")})
    assert [(fill.side, fill.date) for fill in result.fills] == [
        ("buy", date(2024, 1, 4)),
        ("sell", date(2024, 1, 5)),
    ]


def test_fundamental_quality_uses_only_available_cross_section():
    codes = ["A", "B", "C"]
    panels = {
        "financials": {
            code: [
                {
                    "date": "2023-12-31",
                    "availableAt": "2024-01-02T08:00:00+00:00",
                    "bps": bps,
                    "roe": roe,
                }
            ]
            for code, bps, roe in (
                ("A", 15.0, 12.0),
                ("B", 10.0, 8.0),
                ("C", 5.0, 4.0),
            )
        }
    }
    config = BacktestConfig(
        strategy_type="fundamental_quality",
        params={"topN": 1, "wValue": 0.5, "wQuality": 0.5, "target": 0.5},
        codes=codes,
        start="2024-01-02",
        end="2024-01-05",
        initial_capital=1_000_000,
        slippage=0,
        max_participation=1,
        auxiliary_panels=panels,
    )
    result = NativeEngine().run(
        config,
        FundamentalQuality(),
        {code: _bars(code) for code in codes},
    )
    assert result.fills
    assert {fill.code for fill in result.fills if fill.side == "buy"} == {"A"}


def test_runner_rejects_stale_or_partial_pit_panels():
    flow_config = BacktestConfig(
        strategy_type="flow_surge",
        params={"window": 2, "minRatio": 5.0, "target": 0.5},
        codes=["X"],
        start="2024-01-03",
        end="2024-01-03",
    )
    with pytest.raises(ValueError, match="连续且可用"):
        runner.validate_pit_auxiliary_panels(
            flow_config,
            {
                "capital_flow": {
                    "X": [
                        {
                            "date": "2024-01-02",
                            "availableAt": "2024-01-02T08:00:00+00:00",
                            "mainNetRatio": 6.0,
                        }
                    ]
                }
            },
        )
    financial_config = BacktestConfig(
        strategy_type="fundamental_quality",
        params={},
        codes=["A", "B"],
        start="2024-01-03",
        end="2024-01-03",
    )
    with pytest.raises(ValueError, match="少于 3"):
        runner.validate_pit_auxiliary_panels(
            financial_config, {"financials": {}}
        )


def test_panel_validation_uses_each_days_dynamic_eligible_codes():
    config = BacktestConfig(
        strategy_type="fundamental_quality",
        params={},
        codes=["A", "B", "C"],
        start="2024-01-03",
        end="2024-01-03",
        universe_mode="pit_filtered",
        eligible_by_date={"2024-01-03": ("A", "B")},
    )
    row = {
        "date": "2023-12-31",
        "availableAt": "2024-01-02T08:00:00+00:00",
        "bps": 10.0,
        "roe": 8.0,
    }
    with pytest.raises(ValueError, match="动态股票池少于 3"):
        runner.validate_pit_auxiliary_panels(
            config,
            {"financials": {code: [row] for code in config.codes}},
        )


def test_panel_validation_rejects_range_without_market_session():
    config = BacktestConfig(
        strategy_type="flow_surge",
        params={"window": 1},
        codes=["X"],
        start="2024-01-06",
        end="2024-01-07",
    )
    with pytest.raises(ValueError, match="没有 XSHG 交易日"):
        runner.validate_pit_auxiliary_panels(
            config, {"capital_flow": {"X": []}}
        )


def test_flow_grid_is_rejected_before_loading_panels(monkeypatch):
    config = BacktestConfig(
        strategy_type="flow_surge",
        params={},
        codes=["600000.SH"],
        start="2024-01-02",
        end="2024-01-05",
    )
    monkeypatch.setattr(
        runner,
        "load_pit_auxiliary_panels",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("panel loaded")
        ),
    )
    with pytest.raises(ValidationError, match="暂不支持同步网格"):
        backtest_run.grid_search(
            config,
            {"window": [1]},
            "sharpeRatio",
        )
