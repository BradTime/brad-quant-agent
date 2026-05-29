"""Data source providers.

A ``DataProvider`` abstraction with hot-swappable implementations
(AkShare / BaoStock / efinance), routed by capability via ``registry``.
"""

from app.providers.base import (
    AdjustFactorDTO,
    BarDTO,
    DataProvider,
    InstrumentDTO,
    QuoteDTO,
)
from app.providers.registry import (
    available_providers,
    get_provider,
    get_provider_for,
)

__all__ = [
    "DataProvider",
    "InstrumentDTO",
    "BarDTO",
    "QuoteDTO",
    "AdjustFactorDTO",
    "get_provider",
    "get_provider_for",
    "available_providers",
]
