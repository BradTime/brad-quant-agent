"""AkShare provider — broadest free coverage (instruments, realtime snapshot, daily).

AkShare wraps Eastmoney/Sina endpoints; column names are Chinese and may drift
across versions, so access is defensive (``.get`` with fallbacks). Heavy import
is lazy. Realtime is a snapshot (seconds-level), not true tick.
"""

from __future__ import annotations

from datetime import datetime

from app.core.dtutil import parse_datetime
from app.core.numeric import to_float
from app.providers import symbols
from app.providers.base import BarDTO, DataProvider, InstrumentDTO, QuoteDTO


def _pick(row, *keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


class AkShareProvider(DataProvider):
    name = "akshare"
    capabilities = {"instruments", "daily", "realtime", "index"}

    def get_instruments(self) -> list[InstrumentDTO]:
        import akshare as ak

        df = ak.stock_info_a_code_name()  # columns: code, name
        out: list[InstrumentDTO] = []
        for _, row in df.iterrows():
            six = str(_pick(row, "code", "代码") or "").zfill(6)
            if not six.isdigit():
                continue
            canonical = symbols.to_canonical(six)
            out.append(
                InstrumentDTO(
                    code=canonical,
                    name=str(_pick(row, "name", "名称") or ""),
                    exchange=symbols.split_canonical(canonical)[1],
                    security_type="stock",
                )
            )
        return out

    def get_realtime_quotes(self, codes: list[str] | None = None) -> list[QuoteDTO]:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        wanted = {symbols.to_six(c) for c in codes} if codes else None
        now = datetime.now()
        out: list[QuoteDTO] = []
        for _, row in df.iterrows():
            six = str(_pick(row, "代码", "code") or "").zfill(6)
            if not six.isdigit() or (wanted is not None and six not in wanted):
                continue
            canonical = symbols.to_canonical(six)
            out.append(
                QuoteDTO(
                    code=canonical,
                    name=str(_pick(row, "名称", "name") or ""),
                    price=to_float(_pick(row, "最新价")),
                    change=to_float(_pick(row, "涨跌额")),
                    change_percent=to_float(_pick(row, "涨跌幅")),
                    open=to_float(_pick(row, "今开", "开盘")),
                    high=to_float(_pick(row, "最高")),
                    low=to_float(_pick(row, "最低")),
                    prev_close=to_float(_pick(row, "昨收")),
                    volume=to_float(_pick(row, "成交量")),
                    amount=to_float(_pick(row, "成交额")),
                    ts=now,
                )
            )
        return out

    def get_daily_bars(
        self, code: str, start: str, end: str, adjust: str = "none"
    ) -> list[BarDTO]:
        import akshare as ak

        adj = {"none": "", "qfq": "qfq", "hfq": "hfq"}.get(adjust, "")
        df = ak.stock_zh_a_hist(
            symbol=symbols.to_six(code),
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust=adj,
        )
        bars: list[BarDTO] = []
        for _, row in df.iterrows():
            dt = parse_datetime(_pick(row, "日期", "date"))
            if dt is None:
                continue
            bars.append(
                BarDTO(
                    code=code,
                    dt=dt,
                    period="1d",
                    open=to_float(_pick(row, "开盘")),
                    high=to_float(_pick(row, "最高")),
                    low=to_float(_pick(row, "最低")),
                    close=to_float(_pick(row, "收盘")),
                    volume=to_float(_pick(row, "成交量")),
                    amount=to_float(_pick(row, "成交额")),
                )
            )
        return bars

    def get_index_quotes(self, codes: list[str]) -> list[QuoteDTO]:
        import akshare as ak

        df = None
        for kwargs in ({"symbol": "沪深重要指数"}, {}):
            try:
                df = ak.stock_zh_index_spot_em(**kwargs)
                break
            except Exception:
                continue
        if df is None:
            return []
        code_map = {symbols.to_six(c): c for c in codes}
        now = datetime.now()
        out: list[QuoteDTO] = []
        for _, row in df.iterrows():
            six = str(_pick(row, "代码", "code") or "").zfill(6)
            canonical = code_map.get(six)
            if canonical is None:
                continue
            out.append(
                QuoteDTO(
                    code=canonical,
                    name=str(_pick(row, "名称", "name") or ""),
                    price=to_float(_pick(row, "最新价")),
                    change=to_float(_pick(row, "涨跌额")),
                    change_percent=to_float(_pick(row, "涨跌幅")),
                    open=to_float(_pick(row, "今开", "开盘")),
                    high=to_float(_pick(row, "最高")),
                    low=to_float(_pick(row, "最低")),
                    prev_close=to_float(_pick(row, "昨收")),
                    volume=to_float(_pick(row, "成交量")),
                    amount=to_float(_pick(row, "成交额")),
                    ts=now,
                )
            )
        return out
