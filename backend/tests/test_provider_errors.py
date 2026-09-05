"""H15：Provider 错误类型与 AkShare 不可用上抛。"""

from __future__ import annotations

import sys
import types

import pytest

from app.providers.akshare_provider import AkShareProvider
from app.providers.base import ProviderUnavailable


def test_provider_unavailable_message():
    err = ProviderUnavailable("akshare", "timeout", code="net")
    assert err.provider == "akshare"
    assert "akshare" in str(err)
    assert err.code == "net"


def test_akshare_capital_flow_raises_unavailable(monkeypatch):
    def boom(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        types.SimpleNamespace(stock_individual_fund_flow=boom),
    )
    provider = AkShareProvider()
    with pytest.raises(ProviderUnavailable) as ei:
        provider.get_capital_flow("600000.SH")
    assert ei.value.provider == "akshare"
    assert "boom" in str(ei.value)
