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
CAP_CAPITAL_FLOW = "capital_flow"
CAP_FINANCIALS = "financials"
CAP_DRAGON_TIGER = "dragon_tiger"
CAP_NEWS = "news"


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


class CapitalFlowDTO(BaseModel):
    code: str
    trade_date: date
    main_net: float | None = None
    main_net_ratio: float | None = None
    super_large_net: float | None = None
    large_net: float | None = None
    medium_net: float | None = None
    small_net: float | None = None


class FinancialSummaryDTO(BaseModel):
    code: str
    report_date: date
    eps: float | None = None
    bps: float | None = None
    roe: float | None = None
    revenue: float | None = None
    net_profit: float | None = None
    gross_margin: float | None = None


class DragonTigerDTO(BaseModel):
    code: str
    trade_date: date
    name: str = ""
    reason: str = ""
    net_buy: float | None = None
    buy_amount: float | None = None
    sell_amount: float | None = None


class NewsItemDTO(BaseModel):
    title: str
    code: str | None = None
    url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    summary: str | None = None


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

    def get_capital_flow(self, code: str) -> list[CapitalFlowDTO]:
        raise NotImplementedError

    def get_financials(self, code: str) -> list[FinancialSummaryDTO]:
        raise NotImplementedError

    def get_dragon_tiger(self, start: str, end: str) -> list[DragonTigerDTO]:
        raise NotImplementedError

    def get_news(self, code: str, limit: int = 30) -> list[NewsItemDTO]:
        raise NotImplementedError
