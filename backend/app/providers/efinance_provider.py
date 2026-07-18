"""efinance provider — lightweight Eastmoney wrapper, used to supplement realtime.

Heavy import is lazy. Realtime is a snapshot, not true tick.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.dtutil import parse_datetime
from app.core.numeric import to_float
from app.providers import symbols
from app.providers.base import BarDTO, DataProvider, QuoteDTO

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _pick(row, *keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


class EfinanceProvider(DataProvider):
    name = "efinance"
    capabilities = {"realtime", "daily"}

    def get_realtime_quotes(self, codes: list[str] | None = None) -> list[QuoteDTO]:
        import efinance as ef

        df = ef.stock.get_realtime_quotes()
        wanted = {symbols.to_six(c) for c in codes} if codes else None
        # The free snapshot has no reliable per-row exchange event timestamp.
        # Use the actual observation time, never the later WS delivery time.
        now = datetime.now(_SHANGHAI)
        out: list[QuoteDTO] = []
        for _, row in df.iterrows():
            six = str(_pick(row, "股票代码", "代码") or "").zfill(6)
            if not six.isdigit() or (wanted is not None and six not in wanted):
                continue
            canonical = symbols.to_canonical(six)
            out.append(
                QuoteDTO(
                    code=canonical,
                    name=str(_pick(row, "股票名称", "名称") or ""),
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
        import efinance as ef

        fqt = {"none": 0, "qfq": 1, "hfq": 2}.get(adjust, 0)
        df = ef.stock.get_quote_history(
            symbols.to_six(code),
            beg=start.replace("-", ""),
            end=end.replace("-", ""),
            klt=101,  # 101 = daily
            fqt=fqt,
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
