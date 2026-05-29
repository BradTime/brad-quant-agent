"""Provider registry + capability-based routing.

Default routing follows the SPEC: historical/minute/adjust/instruments -> BaoStock;
realtime -> efinance (fallback AkShare). Providers are instantiated lazily and
cached; swapping in a paid source later means editing only this file.
"""

from __future__ import annotations

from app.providers.akshare_provider import AkShareProvider
from app.providers.base import DataProvider
from app.providers.baostock_provider import BaoStockProvider
from app.providers.efinance_provider import EfinanceProvider

_REGISTRY: dict[str, type[DataProvider]] = {
    BaoStockProvider.name: BaoStockProvider,
    AkShareProvider.name: AkShareProvider,
    EfinanceProvider.name: EfinanceProvider,
}

_DEFAULT_ROUTE: dict[str, list[str]] = {
    "instruments": ["baostock", "akshare"],
    "daily": ["baostock", "akshare", "efinance"],
    "minute": ["baostock"],
    "adjust": ["baostock"],
    "realtime": ["akshare", "efinance"],
    "index": ["akshare"],
    "capital_flow": ["akshare"],
    "financials": ["akshare"],
    "dragon_tiger": ["akshare"],
    "news": ["akshare"],
}

_instances: dict[str, DataProvider] = {}


def get_provider(name: str) -> DataProvider:
    if name not in _REGISTRY:
        raise KeyError(f"未知数据源: {name}（可选: {', '.join(_REGISTRY)}）")
    return _instances.setdefault(name, _REGISTRY[name]())


def get_providers_for(capability: str) -> list[DataProvider]:
    route = _DEFAULT_ROUTE.get(capability)
    if not route:
        raise KeyError(f"未知能力: {capability}")
    return [get_provider(name) for name in route]


def get_provider_for(capability: str) -> DataProvider:
    return get_providers_for(capability)[0]


def available_providers() -> list[str]:
    return list(_REGISTRY)
