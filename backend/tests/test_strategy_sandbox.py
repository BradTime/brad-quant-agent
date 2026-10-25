import pytest

from app.services.strategy_sandbox import (
    PROTOCOL_VERSION,
    StrategySandboxError,
    run_source,
    source_sha256,
    validate_source,
)

VALID_SOURCE = """
def generate_signals(context, bars):
    signals = []
    codes = get(context, "codes", [])
    for code in codes:
        rows = get(bars, code, [])
        if len(rows) >= 2:
            latest = get(rows[-1], "close", 0)
            previous = get(rows[-2], "close", 0)
            score = 1 if latest > previous else -1
            signals = signals + [{
                "code": code,
                "score": score,
                "confidence": 0.6,
                "reason": "two-bar direction"
            }]
    return {"signals": signals}
"""


def test_sandbox_runs_deterministic_signal_protocol():
    payload = {
        "context": {"codes": ["600000.SH"]},
        "bars": {
            "600000.SH": [
                {"date": "2026-09-01", "close": 10.0},
                {"date": "2026-09-02", "close": 10.5},
            ]
        },
    }
    first = run_source(VALID_SOURCE, **payload)
    second = run_source(VALID_SOURCE, **payload)

    assert first == second
    assert first == {
        "schemaVersion": 1,
        "protocolVersion": PROTOCOL_VERSION,
        "signals": [
            {
                "code": "600000.SH",
                "score": 1.0,
                "confidence": 0.6,
                "reason": "two-bar direction",
            }
        ],
    }
    assert len(source_sha256(validate_source(VALID_SOURCE))) == 64


@pytest.mark.parametrize(
    "source",
    [
        "import os\ndef generate_signals(context, bars):\n return {'signals': []}",
        "def generate_signals(context, bars):\n return open('/etc/passwd').read()",
        "def generate_signals(context, bars):\n return context.__class__",
        "def other(context, bars):\n return {'signals': []}",
        "x = 1\ndef generate_signals(context, bars):\n return {'signals': []}",
    ],
)
def test_sandbox_rejects_import_io_attributes_and_top_level_code(source):
    with pytest.raises(StrategySandboxError):
        validate_source(source)


@pytest.mark.parametrize(
    "result",
    [
        "{'signals': [{'code': '600000.SH', 'score': 2, 'confidence': 1}]}",
        "{'signals': [{'code': '600000.SZ', 'score': 1, 'confidence': 1}]}",
        "{'signals': [{'code': '600000.SH', 'score': 1, 'confidence': -0.1}]}",
        "{'extra': True, 'signals': []}",
    ],
)
def test_sandbox_rejects_invalid_output(result):
    source = (
        "def generate_signals(context, bars):\n"
        f"    return {result}\n"
    )
    with pytest.raises(StrategySandboxError):
        run_source(source, context={}, bars={})


def test_sandbox_rejects_oversized_output_before_parent_accepts_it():
    source = (
        "def generate_signals(context, bars):\n"
        "    return {'signals': [{"
        "'code': '600000', 'score': 1, 'confidence': 1, "
        "'reason': 'x' * 2000000}]}\n"
    )
    with pytest.raises(StrategySandboxError, match="执行失败"):
        run_source(source, context={}, bars={})
