"""DataProvider abstraction + transport DTOs.

Implementations (AkShare / BaoStock / efinance) are hot-swappable behind this
interface so the rest of the platform never depends on a concrete source
(SPEC: ``DataProvider`` abstraction, supports adding paid sources later).
"""

from __future__ import annotations

from abc import ABC
from datetime import date, datetime

from pydantic import BaseModel

# Capability tokens used by the registry to route requests.
CAP_INSTRUMENTS = "instruments"
CAP_DAILY = "daily"
CAP_MINUTE = "minute"
CAP_ADJUST = "adjust"
CAP_REALTIME = "realtime"
CAP_INDEX = "index"


class InstrumentDTO(BaseModel):
    code: str
    name: str = ""
    exchange: str = ""
    security_type: str = "stock"
    list_date: date | None = None
    delist_date: date | None = None
    status: str = "listed"


class BarDTO(BaseModel):
    code: str
    dt: datetime
    period: str = "1d"  # 1d / 5 / 15 / 30 / 60
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    amount: float | None = None


class QuoteDTO(BaseModel):
    code: str
    name: str = ""
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    ts: datetime | None = None


class AdjustFactorDTO(BaseModel):
    code: str
    ex_date: date
    adjust_factor: float | None = None
    fore_adjust_factor: float | None = None
    back_adjust_factor: float | None = None


class DataProvider(ABC):
    """Base class. Subclasses set ``name`` + ``capabilities`` and override the
    methods they support; unsupported methods raise ``NotImplementedError``."""

    name: str = "base"
    capabilities: set[str] = set()

    def get_instruments(self) -> list[InstrumentDTO]:
        raise NotImplementedError

    def get_daily_bars(
        self, code: str, start: str, end: str, adjust: str = "none"
    ) -> list[BarDTO]:
        raise NotImplementedError

    def get_minute_bars(
        self, code: str, period: str, start: str, end: str
    ) -> list[BarDTO]:
        raise NotImplementedError

    def get_realtime_quotes(self, codes: list[str] | None = None) -> list[QuoteDTO]:
        raise NotImplementedError

    def get_index_quotes(self, codes: list[str]) -> list[QuoteDTO]:
        raise NotImplementedError

    def get_adjust_factors(
        self, code: str, start: str, end: str
    ) -> list[AdjustFactorDTO]:
        raise NotImplementedError
