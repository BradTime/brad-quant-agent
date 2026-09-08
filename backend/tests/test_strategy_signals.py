import pytest

from app.services.strategy_signals import generate_signals


def _bars(count: int = 300) -> dict[str, list[dict]]:
    return {
        code: [
            {
                "date": f"day-{index}",
                "close": base + index * step,
                "high": base + index * step + 0.05,
                "low": base + index * step - 0.05,
                "volume": 1_000_000 + index,
                "amount": (1_000_000 + index) * (base + index * step),
            }
            for index in range(count)
        ]
        for code, base, step in (
            ("600000", 10.0, 0.01),
            ("000001", 12.0, 0.005),
            ("600036", 30.0, -0.002),
        )
    }


@pytest.mark.parametrize(
    "builtin_type",
    [
        "dual_ma",
        "rsi",
        "boll",
        "momentum",
        "donchian_breakout",
        "xs_momentum",
        "zscore_reversion",
        "composite_mf",
    ],
)
def test_builtin_strategies_share_versioned_signal_protocol(builtin_type):
    result = generate_signals(
        definition_type="builtin",
        builtin_type=builtin_type,
        params={},
        source_code=None,
        context={},
        bars=_bars(),
    )
    assert result["schemaVersion"] == 1
    assert result["protocolVersion"] == "signal-v1"
    assert result["signals"][0]["code"] == "600000.SH"
    assert -1 <= result["signals"][0]["score"] <= 1
    assert 0 <= result["signals"][0]["confidence"] <= 1


def test_custom_strategy_uses_same_signal_protocol():
    result = generate_signals(
        definition_type="custom_python",
        builtin_type=None,
        params={"score": 0.5},
        source_code=(
            "def generate_signals(context, bars):\n"
            "    params = get(context, 'params', {})\n"
            "    return {'signals': [{"
            "'code': '600000', 'score': get(params, 'score', 0), "
            "'confidence': 0.8, 'reason': 'custom'}]}\n"
        ),
        context={},
        bars={},
    )
    assert result == {
        "schemaVersion": 1,
        "protocolVersion": "signal-v1",
        "signals": [
            {
                "code": "600000.SH",
                "score": 0.5,
                "confidence": 0.8,
                "reason": "custom",
            }
        ],
    }
