"""Tests for instrument code normalization."""

from __future__ import annotations

from app.providers import symbols


def test_to_canonical_sh():
    assert symbols.to_canonical("600000") == "600000.SH"


def test_to_canonical_sz():
    assert symbols.to_canonical("000001") == "000001.SZ"


def test_to_six_from_canonical():
    assert symbols.to_six("600000.SH") == "600000"


def test_to_baostock():
    assert symbols.to_baostock("600000.SH") == "sh.600000"


def test_from_baostock():
    assert symbols.from_baostock("sz.000001") == "000001.SZ"
