"""AkShare provider — broadest free coverage (instruments, realtime snapshot, daily).

AkShare wraps Eastmoney/Sina endpoints; column names are Chinese and may drift
across versions, so access is defensive (``.get`` with fallbacks). Heavy import
is lazy. Realtime is a snapshot (seconds-level), not true tick.
"""

from __future__ import annotations

from datetime import datetime

from app.core.dtutil import parse_date, parse_datetime
from app.core.numeric import to_float
from app.providers import symbols
from app.providers.base import (
    BarDTO,
    CapitalFlowDTO,
    DataProvider,
    DragonTigerDTO,
    FinancialSummaryDTO,
    InstrumentDTO,
    NewsItemDTO,
    QuoteDTO,
)


def _pick(row, *keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _opt_str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class AkShareProvider(DataProvider):
    name = "akshare"
    capabilities = {
        "instruments",
        "daily",
        "realtime",
        "index",
        "capital_flow",
        "financials",
        "dragon_tiger",
        "news",
    }

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

    def get_capital_flow(self, code: str) -> list[CapitalFlowDTO]:
        import akshare as ak

        six = symbols.to_six(code)
        market = symbols.split_canonical(code)[1].lower()
        try:
            df = ak.stock_individual_fund_flow(stock=six, market=market)
        except Exception:
            return []
        out: list[CapitalFlowDTO] = []
        for _, row in df.iterrows():
            d = parse_date(_pick(row, "日期", "date"))
            if d is None:
                continue
            out.append(
                CapitalFlowDTO(
                    code=code,
                    trade_date=d,
                    main_net=to_float(_pick(row, "主力净流入-净额")),
                    main_net_ratio=to_float(_pick(row, "主力净流入-净占比")),
                    super_large_net=to_float(_pick(row, "超大单净流入-净额")),
                    large_net=to_float(_pick(row, "大单净流入-净额")),
                    medium_net=to_float(_pick(row, "中单净流入-净额")),
                    small_net=to_float(_pick(row, "小单净流入-净额")),
                )
            )
        return out

    def get_financials(self, code: str) -> list[FinancialSummaryDTO]:
        import akshare as ak

        six = symbols.to_six(code)
        try:
            df = ak.stock_financial_abstract_ths(symbol=six, indicator="按报告期")
        except Exception:
            return []
        out: list[FinancialSummaryDTO] = []
        for _, row in df.iterrows():
            d = parse_date(_pick(row, "报告期", "报告日", "date"))
            if d is None:
                continue
            out.append(
                FinancialSummaryDTO(
                    code=code,
                    report_date=d,
                    eps=to_float(_pick(row, "基本每股收益", "每股收益")),
                    bps=to_float(_pick(row, "每股净资产")),
                    roe=to_float(_pick(row, "净资产收益率")),
                    revenue=to_float(_pick(row, "营业总收入", "营业收入")),
                    net_profit=to_float(_pick(row, "净利润")),
                    gross_margin=to_float(_pick(row, "销售毛利率", "毛利率")),
                )
            )
        return out

    def get_dragon_tiger(self, start: str, end: str) -> list[DragonTigerDTO]:
        import akshare as ak

        try:
            df = ak.stock_lhb_detail_em(
                start_date=start.replace("-", ""), end_date=end.replace("-", "")
            )
        except Exception:
            return []
        out: list[DragonTigerDTO] = []
        for _, row in df.iterrows():
            six = str(_pick(row, "代码", "证券代码") or "").zfill(6)
            if not six.isdigit():
                continue
            d = parse_date(_pick(row, "上榜日", "上榜日期", "交易日"))
            if d is None:
                continue
            out.append(
                DragonTigerDTO(
                    code=symbols.to_canonical(six),
                    trade_date=d,
                    name=str(_pick(row, "名称", "证券名称") or ""),
                    reason=str(_pick(row, "上榜原因", "解读") or "")[:160],
                    net_buy=to_float(_pick(row, "龙虎榜净买额", "净买额")),
                    buy_amount=to_float(_pick(row, "龙虎榜买入额", "买入额")),
                    sell_amount=to_float(_pick(row, "龙虎榜卖出额", "卖出额")),
                )
            )
        return out

    def get_news(self, code: str, limit: int = 30) -> list[NewsItemDTO]:
        import akshare as ak

        six = symbols.to_six(code)
        try:
            df = ak.stock_news_em(symbol=six)
        except Exception:
            return []
        out: list[NewsItemDTO] = []
        for _, row in df.head(limit).iterrows():
            title = str(_pick(row, "新闻标题", "标题") or "").strip()
            if not title:
                continue
            out.append(
                NewsItemDTO(
                    code=code,
                    title=title[:512],
                    url=_opt_str(_pick(row, "新闻链接", "链接")),
                    source_name=_opt_str(_pick(row, "文章来源", "来源")),
                    published_at=parse_datetime(_pick(row, "发布时间", "时间")),
                    summary=_opt_str(_pick(row, "新闻内容", "内容")),
                )
            )
        return out
