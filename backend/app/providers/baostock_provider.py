"""BaoStock provider — clean historical daily/minute K-line, adjust factors, basics.

BaoStock is free, token-free, and stable for historical data, so it is the
default source for daily/minute/adjust/instruments (SPEC). Heavy import is lazy
so this module stays importable without the dependency installed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from app.core.dtutil import parse_baostock_time, parse_date, parse_datetime
from app.core.numeric import to_float
from app.core.tz import market_now
from app.providers import symbols
from app.providers.base import (
    AdjustFactorDTO,
    BarDTO,
    DataProvider,
    InstrumentDTO,
    InstrumentStatusDTO,
    ProviderSchemaError,
    ProviderUnavailable,
)


@contextmanager
def _bs_session() -> Iterator[object]:
    import baostock as bs

    login = bs.login()
    if getattr(login, "error_code", "0") != "0":
        raise RuntimeError(f"BaoStock 登录失败: {getattr(login, 'error_msg', 'unknown')}")
    try:
        yield bs
    finally:
        bs.logout()


def _collect(rs) -> list[list[str]]:
    rows: list[list[str]] = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if getattr(rs, "error_code", "0") != "0":
        raise ProviderUnavailable(
            "baostock",
            f"查询失败: {getattr(rs, 'error_msg', 'unknown')}",
        )
    return rows


class BaoStockProvider(DataProvider):
    name = "baostock"
    capabilities = {"instruments", "daily", "minute", "adjust", "status_history"}

    _MINUTE_FREQ = {"5", "15", "30", "60"}

    def get_instruments(self) -> list[InstrumentDTO]:
        with _bs_session() as bs:
            rows = _collect(bs.query_stock_basic())
        out: list[InstrumentDTO] = []
        # columns: code, code_name, ipoDate, outDate, type, status
        for row in rows:
            if len(row) < 6:
                continue
            bcode, name, ipo, out_date, typ, status = row[:6]
            canonical = symbols.from_baostock(bcode)
            out.append(
                InstrumentDTO(
                    code=canonical,
                    name=name,
                    exchange=symbols.split_canonical(canonical)[1],
                    security_type={"1": "stock", "2": "index"}.get(typ, "other"),
                    list_date=parse_date(ipo),
                    delist_date=parse_date(out_date),
                    status="listed" if status == "1" else "delisted",
                )
            )
        return out

    def get_daily_bars(
        self, code: str, start: str, end: str, adjust: str = "none"
    ) -> list[BarDTO]:
        flag = {"none": "3", "qfq": "2", "hfq": "1"}.get(adjust, "3")
        with _bs_session() as bs:
            rs = bs.query_history_k_data_plus(
                symbols.to_baostock(code),
                "date,open,high,low,close,volume,amount",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag=flag,
            )
            rows = _collect(rs)
        bars: list[BarDTO] = []
        for d, o, h, low_, c, v, a in (r[:7] for r in rows if len(r) >= 7):
            dt = parse_datetime(d)
            if dt is None:
                continue
            bars.append(
                BarDTO(
                    code=code,
                    dt=dt,
                    period="1d",
                    open=to_float(o),
                    high=to_float(h),
                    low=to_float(low_),
                    close=to_float(c),
                    volume=to_float(v),
                    amount=to_float(a),
                )
            )
        return bars

    def get_minute_bars(
        self, code: str, period: str, start: str, end: str
    ) -> list[BarDTO]:
        if str(period) not in self._MINUTE_FREQ:
            raise ValueError("BaoStock 仅支持 5/15/30/60 分钟")
        with _bs_session() as bs:
            rs = bs.query_history_k_data_plus(
                symbols.to_baostock(code),
                "time,open,high,low,close,volume,amount",
                start_date=start,
                end_date=end,
                frequency=str(period),
                adjustflag="3",
            )
            rows = _collect(rs)
        bars: list[BarDTO] = []
        for t, o, h, low_, c, v, a in (r[:7] for r in rows if len(r) >= 7):
            dt = parse_baostock_time(t)
            if dt is None:
                continue
            bars.append(
                BarDTO(
                    code=code,
                    dt=dt,
                    period=str(period),
                    open=to_float(o),
                    high=to_float(h),
                    low=to_float(low_),
                    close=to_float(c),
                    volume=to_float(v),
                    amount=to_float(a),
                )
            )
        return bars

    def get_adjust_factors(
        self, code: str, start: str, end: str
    ) -> list[AdjustFactorDTO]:
        with _bs_session() as bs:
            rs = bs.query_adjust_factor(
                code=symbols.to_baostock(code), start_date=start, end_date=end
            )
            rows = _collect(rs)
        out: list[AdjustFactorDTO] = []
        # columns: code, dividOperateDate, foreAdjustFactor, backAdjustFactor, adjustFactor
        for row in rows:
            if len(row) < 5:
                continue
            _, ex_date, fore, back, adj = row[:5]
            ex = parse_date(ex_date)
            if ex is None:
                continue
            out.append(
                AdjustFactorDTO(
                    code=code,
                    ex_date=ex,
                    fore_adjust_factor=to_float(fore),
                    back_adjust_factor=to_float(back),
                    adjust_factor=to_float(adj),
                )
            )
        return out

    def get_status_history(self, code: str) -> list[InstrumentStatusDTO]:
        """Compress BaoStock's daily ``isST`` observations into PIT intervals."""
        canonical = f"{symbols.to_six(code)}.{symbols.split_canonical(code)[1]}"
        with _bs_session() as bs:
            rs = bs.query_history_k_data_plus(
                symbols.to_baostock(canonical),
                "date,isST",
                start_date="1990-01-01",
                end_date=market_now().date().isoformat(),
                frequency="d",
                adjustflag="3",
            )
            rows = _collect(rs)

        observations: list[tuple[date, bool]] = []
        for row in rows:
            if len(row) < 2:
                continue
            day = parse_date(row[0])
            raw = str(row[1]).strip()
            if day is None:
                continue
            if raw not in {"0", "1"}:
                raise ProviderSchemaError(
                    self.name,
                    f"isST 非法值: {canonical} {day}={raw!r}",
                )
            observations.append((day, raw == "1"))
        observations.sort(key=lambda item: item[0])
        if not observations:
            return []

        out: list[InstrumentStatusDTO] = []
        interval_start, current_st = observations[0]
        previous_day = interval_start
        for day, is_st in observations[1:]:
            if is_st != current_st:
                out.append(
                    InstrumentStatusDTO(
                        code=canonical,
                        start_date=interval_start,
                        end_date=previous_day,
                        status_type="st" if current_st else "normal",
                    )
                )
                interval_start = day
                current_st = is_st
            previous_day = day
        out.append(
            InstrumentStatusDTO(
                code=canonical,
                start_date=interval_start,
                end_date=None,
                status_type="st" if current_st else "normal",
            )
        )
        return out
