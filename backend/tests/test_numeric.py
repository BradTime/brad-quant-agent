"""Tests for numeric parsing — especially the THS 财务摘要 quirks
(中文单位 / 百分号 / False 缺失标记)."""

from __future__ import annotations

import pytest

from app.core.numeric import parse_cn_number, to_float


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.47亿", 147000000.0),
        ("6.28亿", 628000000.0),
        ("12.5万亿", 12_500_000_000_000.0),
        ("3.2万", 32000.0),
        ("54.27%", 54.27),
        ("85.50%", 85.5),
        ("21.76", 21.76),
        ("1,234.5", 1234.5),
        (False, None),
        (True, None),
        ("--", None),
        ("", None),
        (None, None),
        (12.5, 12.5),
    ],
)
def test_parse_cn_number(value, expected):
    assert parse_cn_number(value) == expected


def test_to_float_rejects_bool():
    # 关键回归：False 不能被当成 0.0（否则"缺失"会变成有效 0 值）。
    assert to_float(False) is None
    assert to_float(True) is None
    assert to_float("3.14") == 3.14
