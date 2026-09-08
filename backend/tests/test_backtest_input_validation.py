"""H3 backtest input validation boundaries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.backtest.base import BacktestConfig
from app.backtest.strategies.dual_ma import DualMA
from app.main import app
from app.schemas.backtest import GridSearchRequest, RunBacktestRequest
from app.services import backtest_run, rate_limit


def valid_run(**overrides):
    payload = {
        "strategyType": "dual_ma",
        "params": {"fast": 5, "slow": 20, "target": 0.95},
        "codes": ["600000.sh", "600000.SH", "000001"],
        "start": "2024-01-01",
        "end": "2024-12-31",
        "initialCapital": 1_000_000,
        "slippage": 0.001,
        "engine": "native",
        "frequency": "1d",
    }
    payload.update(overrides)
    return payload


def valid_grid(**overrides):
    payload = {
        **valid_run(),
        "paramGrid": {"fast": [5, 10], "slow": [20, 30]},
        "sortBy": "sharpeRatio",
    }
    payload.pop("params")
    payload.update(overrides)
    return payload


def test_run_request_normalizes_dates_codes_and_params():
    request = RunBacktestRequest(**valid_run())

    assert request.start == date(2024, 1, 1)
    assert request.end == date(2024, 12, 31)
    assert request.codes == ["600000.SH", "000001.SZ"]
    assert request.params == {"fast": 5, "slow": 20, "target": 0.95}


def test_request_serializes_dates_and_decimal_at_json_boundary():
    request = RunBacktestRequest(
        **valid_run(initialCapital=Decimal("1000000.25"), slippage=Decimal("0.001"))
    )

    dumped = request.model_dump(mode="json")
    assert dumped["start"] == "2024-01-01"
    assert dumped["end"] == "2024-12-31"
    assert dumped["initialCapital"] == 1_000_000.25
    assert dumped["slippage"] == 0.001


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategyType", "unknown"),
        ("params", []),
        ("codes", []),
        ("codes", ["not-a-code"]),
        ("codes", ["600000.XX"]),
        ("start", "2025-01-01"),
        ("initialCapital", -1),
        ("initialCapital", 10**16),
        ("initialCapital", float("nan")),
        ("initialCapital", True),
        ("initialCapital", "1000000"),
        ("slippage", 2),
        ("slippage", float("inf")),
        ("engine", "unknown"),
        ("frequency", "2m"),
    ],
)
def test_run_request_rejects_invalid_boundaries(field, value):
    payload = valid_run(**{field: value})
    if field == "start":
        payload["end"] = "2024-01-01"

    with pytest.raises(ValidationError):
        RunBacktestRequest(**payload)


def test_run_request_rejects_more_than_ten_years_and_extra_fields():
    with pytest.raises(ValidationError):
        RunBacktestRequest(**valid_run(start="2010-01-01", end="2024-01-01"))
    with pytest.raises(ValidationError):
        RunBacktestRequest(**valid_run(legacy=True))


@pytest.mark.parametrize(
    "overrides",
    [
        {"params": {"fast": 20, "slow": 20}},
        {"params": {"fast": 5, "slow": 20, "mystery": 1}},
        {"params": {"fast": 5.5, "slow": 20}},
    ],
)
def test_run_request_uses_strategy_parameter_validation(overrides):
    with pytest.raises(ValidationError):
        RunBacktestRequest(**valid_run(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"paramGrid": {"mystery": [1]}},
        {"paramGrid": {"fast": []}},
        {"paramGrid": {"fast": list(range(11))}},
        {"paramGrid": {"fast": [float("nan")]}},
        {"paramGrid": {"fast": list(range(1, 9)), "slow": list(range(20, 29))}},
        {"paramGrid": {"fast": [20], "slow": [10]}},
        {"sortBy": "notAMetric"},
    ],
)
def test_grid_request_rejects_invalid_grid(overrides):
    with pytest.raises(ValidationError):
        GridSearchRequest(**valid_grid(**overrides))


@pytest.fixture
def backtest_client(monkeypatch):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="user-a")
    monkeypatch.setattr(rate_limit, "ai_cost_gate", lambda user_id, kind: None)
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/backtest/run", valid_run(strategyType="unknown")),
        ("/api/v1/backtest/run", valid_run(codes=["bad"])),
        ("/api/v1/backtest/run", valid_run(start="2025-01-01", end="2024-01-01")),
        ("/api/v1/backtest/run", valid_run(initialCapital=-1)),
        ("/api/v1/backtest/run", valid_run(initialCapital=10**16)),
        ("/api/v1/backtest/run", valid_run(slippage=2)),
        ("/api/v1/backtest/run", valid_run(params={"fast": 20, "slow": 10})),
        ("/api/v1/backtest/grid", valid_grid(paramGrid={"mystery": [1]})),
        ("/api/v1/backtest/grid", valid_grid(sortBy="bad")),
        (
            "/api/v1/backtest/grid",
            valid_grid(paramGrid={"fast": list(range(1, 9)), "slow": list(range(20, 29))}),
        ),
    ],
)
def test_invalid_api_requests_are_400_and_do_not_run_or_persist(
    backtest_client, monkeypatch, path, payload
):
    calls = {"run": 0, "grid": 0}

    def fail_run(*args, **kwargs):
        calls["run"] += 1
        raise AssertionError("invalid request reached run")

    def fail_grid(*args, **kwargs):
        calls["grid"] += 1
        raise AssertionError("invalid request reached grid")

    monkeypatch.setattr(backtest_run, "run_and_save", fail_run)
    monkeypatch.setattr(backtest_run, "grid_search", fail_grid)

    response = backtest_client.post(path, json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == 400
    assert response.json()["data"] is None
    assert calls == {"run": 0, "grid": 0}


def test_internal_run_entry_revalidates_before_engine_or_database(monkeypatch):
    monkeypatch.setattr(
        backtest_run,
        "run_backtest",
        lambda config: (_ for _ in ()).throw(AssertionError("engine called")),
    )

    with pytest.raises(ValidationError):
        backtest_run.run_and_save(
            "user-a",
            SimpleNamespace(**valid_run(params={"fast": 20, "slow": 10})),
        )


def test_run_request_requires_complete_strategy_version_reference():
    with pytest.raises(ValidationError, match="必须同时提供"):
        RunBacktestRequest.model_validate(
            valid_run(strategyId="strategy-1")
        )


def test_run_request_defaults_capacity_controls_and_rejects_invalid_rate():
    payload = valid_run()
    payload.pop("slippage")
    request = RunBacktestRequest.model_validate(payload)
    assert request.slippage == 0.001
    assert request.maxParticipation == 0.01
    with pytest.raises(ValidationError):
        RunBacktestRequest.model_validate(valid_run(maxParticipation=1.1))


def test_daily_only_strategies_and_pit_universe_reject_incompatible_modes():
    with pytest.raises(ValidationError, match="仅支持日线"):
        RunBacktestRequest.model_validate(
            valid_run(
                strategyType="donchian_breakout",
                params={},
                frequency="5m",
            )
        )
    with pytest.raises(ValidationError, match="native"):
        RunBacktestRequest.model_validate(
            valid_run(
                universeMode="pit_filtered",
                engine="backtrader",
            )
        )


def test_versioned_run_uses_immutable_builtin_definition(monkeypatch):
    from app.services import strategy as strategy_service

    monkeypatch.setattr(
        strategy_service,
        "get_version",
        lambda user_id, strategy_id, version: {
            "id": "version-3",
            "definitionType": "builtin",
            "builtinType": "rsi",
            "params": {"period": 12, "low": 25.0, "high": 75.0, "target": 0.7},
            "definitionSha256": "a" * 64,
            "protocolVersion": "signal-v1",
            "implementationVersion": "builtin-v1",
        },
    )
    config, provenance = backtest_run._config_from_run_request(
        RunBacktestRequest.model_validate(
            valid_run(
                strategyType="dual_ma",
                params={"fast": 5, "slow": 20},
                strategyId="strategy-1",
                strategyVersion=3,
            )
        ),
        "user-a",
    )
    assert config.strategy_type == "rsi"
    assert config.params["period"] == 12
    assert provenance == {
        "strategyId": "strategy-1",
        "strategyVersion": 3,
        "strategyVersionId": "version-3",
        "strategyDefinitionSha256": "a" * 64,
        "strategyProtocolVersion": "signal-v1",
        "strategyImplementationVersion": "builtin-v1",
    }


def test_versioned_run_rejects_custom_definition_until_sandbox_backtest_stage(
    monkeypatch,
):
    from app.services import strategy as strategy_service

    monkeypatch.setattr(
        strategy_service,
        "get_version",
        lambda *args: {
            "definitionType": "custom_python",
            "builtinType": "custom_python",
            "params": {},
            "definitionSha256": "b" * 64,
            "protocolVersion": "signal-v1",
        },
    )
    with pytest.raises(ValueError, match="M2"):
        backtest_run._config_from_run_request(
            RunBacktestRequest.model_validate(
                valid_run(
                    strategyId="strategy-1",
                    strategyVersion=1,
                )
            ),
            "user-a",
        )


def test_versioned_run_rejects_incompatible_builtin_executor(monkeypatch):
    from app.services import strategy as strategy_service

    monkeypatch.setattr(
        strategy_service,
        "get_version",
        lambda *args: {
            "id": "version-1",
            "definitionType": "builtin",
            "builtinType": "dual_ma",
            "params": {"fast": 5, "slow": 20, "target": 0.95},
            "definitionSha256": "c" * 64,
            "protocolVersion": "signal-v1",
            "implementationVersion": "builtin-v0",
        },
    )
    with pytest.raises(ValueError, match="实现版本"):
        backtest_run._config_from_run_request(
            RunBacktestRequest.model_validate(
                valid_run(
                    strategyId="strategy-1",
                    strategyVersion=1,
                )
            ),
            "user-a",
        )


def test_pinned_daily_strategy_cannot_hide_behind_minute_placeholder(
    monkeypatch,
):
    from app.services import strategy as strategy_service

    monkeypatch.setattr(
        strategy_service,
        "get_version",
        lambda *args: {
            "id": "version-1",
            "definitionType": "builtin",
            "builtinType": "donchian_breakout",
            "params": {"channel": 20, "target": 0.95},
            "definitionSha256": "d" * 64,
            "protocolVersion": "signal-v1",
            "implementationVersion": "builtin-v1",
        },
    )
    request = RunBacktestRequest.model_validate(
        valid_run(
            strategyType="dual_ma",
            frequency="5m",
            strategyId="strategy-1",
            strategyVersion=1,
        )
    )
    with pytest.raises(ValueError, match="仅支持日线"):
        backtest_run._config_from_run_request(request, "user-a")


def test_internal_grid_rejects_invalid_combination_before_loading_data(monkeypatch):
    monkeypatch.setattr(
        backtest_run.runner,
        "load_bars",
        lambda config: (_ for _ in ()).throw(AssertionError("data loaded")),
    )
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={},
        codes=["600000.SH"],
        start="2024-01-01",
        end="2024-12-31",
    )

    with pytest.raises(ValidationError):
        backtest_run.grid_search(
            config,
            {"fast": [20], "slow": [10]},
            "sharpeRatio",
        )


def test_internal_grid_merges_base_params_before_validating_each_combo(monkeypatch):
    seen = []

    code = "600000.SH"
    monkeypatch.setattr(
        backtest_run.runner,
        "load_bars",
        lambda config: ({code: [SimpleNamespace()]}, {code: "full"}),
    )
    monkeypatch.setattr(
        backtest_run.runner,
        "load_benchmark_with_quality",
        lambda start, end: ([], "full"),
    )

    def capture_combo(config, *args):
        seen.append(config.params)
        return {"metrics": {}, "dataQuality": {}}

    monkeypatch.setattr(backtest_run.runner, "run_on_bars", capture_combo)
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={"slow": 30},
        codes=[code],
        start="2024-01-01",
        end="2024-12-31",
    )

    result = backtest_run.grid_search(config, {"fast": [20]}, "sharpeRatio")

    assert seen == [{"fast": 20, "slow": 30, "target": 0.95}]
    assert len(result["results"]) == 1


def test_internal_grid_rejects_combo_equal_to_base_slow_before_loading(monkeypatch):
    monkeypatch.setattr(
        backtest_run.runner,
        "load_bars",
        lambda config: (_ for _ in ()).throw(AssertionError("data loaded")),
    )
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={"slow": 20},
        codes=["600000.SH"],
        start="2024-01-01",
        end="2024-12-31",
    )

    with pytest.raises(ValidationError):
        backtest_run.grid_search(config, {"fast": [20]}, "sharpeRatio")


def test_pit_filtered_grid_rejects_missing_membership_date(monkeypatch):
    from app.services import universe_membership

    monkeypatch.setattr(
        universe_membership,
        "eligible_map",
        lambda codes, start, end: {"2024-01-02": ("600000.SH",)},
    )
    config = BacktestConfig(
        strategy_type="dual_ma",
        params={"slow": 30},
        codes=["600000.SH"],
        start="2024-01-02",
        end="2024-01-03",
        universe_mode="pit_filtered",
    )
    with pytest.raises(ValueError, match="缺少 2024-01-03"):
        backtest_run.grid_search(
            config,
            {"fast": [10]},
            "sharpeRatio",
        )


def test_dual_ma_rejects_invalid_parameters_instead_of_relabeling_defaults():
    strategy = DualMA()

    with pytest.raises(ValueError, match="fast"):
        strategy.initialize(SimpleNamespace(params={"fast": 20, "slow": 10}))
