"""Tool registry exposed to the LLM (function calling) + dispatch.

Tools are thin wrappers over the existing market service so the AI orchestrator,
embedded assistants, and (later) autonomous agents all share one capability layer.

Every tool argument is validated by a Pydantic model with hard upper bounds so a
malicious or runaway model cannot inflate context/cost via huge codes/count/limit.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.asof import parse_as_of
from app.services import market

# ---- hard limits (also mirrored in TOOLS JSON Schema for the model) ----
_MAX_CODES = 20
_MAX_CODE_LEN = 16
_MAX_QUERY_LEN = 200
_MAX_KEYWORD_LEN = 64
_MAX_KLINE = 500
_MAX_SEARCH = 50
_MAX_FLOW = 120
_MAX_FINANCIALS = 40
_MAX_DRAGON = 50
_MAX_NEWS = 50
_MAX_RAG_K = 20
_MAX_SCREEN = 100


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArgs(_Strict):
    pass


class GetQuotesArgs(_Strict):
    codes: list[str] = Field(min_length=1, max_length=_MAX_CODES)

    @field_validator("codes")
    @classmethod
    def _codes(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            code = str(raw).strip()
            if not code or len(code) > _MAX_CODE_LEN:
                raise ValueError(f"股票代码长度须为 1..{_MAX_CODE_LEN}")
            cleaned.append(code)
        return cleaned


class GetKlineArgs(_Strict):
    symbol: str = Field(min_length=1, max_length=_MAX_CODE_LEN)
    period: Literal["day", "5min", "15min", "30min", "hour"] = "day"
    count: int = Field(default=100, ge=1, le=_MAX_KLINE)


class SearchInstrumentsArgs(_Strict):
    query: str = Field(min_length=1, max_length=_MAX_QUERY_LEN)
    limit: int = Field(default=20, ge=1, le=_MAX_SEARCH)


class GetCapitalFlowArgs(_Strict):
    code: str = Field(min_length=1, max_length=_MAX_CODE_LEN)
    limit: int = Field(default=30, ge=1, le=_MAX_FLOW)


class GetFinancialsArgs(_Strict):
    code: str = Field(min_length=1, max_length=_MAX_CODE_LEN)
    limit: int = Field(default=12, ge=1, le=_MAX_FINANCIALS)
    asOf: str | None = Field(default=None, max_length=40)


class CodeLimitArgs(_Strict):
    code: str = Field(min_length=1, max_length=_MAX_CODE_LEN)
    limit: int = Field(default=20, ge=1, le=_MAX_NEWS)


class GetDragonTigerArgs(_Strict):
    code: str = Field(min_length=1, max_length=_MAX_CODE_LEN)
    limit: int = Field(default=20, ge=1, le=_MAX_DRAGON)


class GetStockProfileArgs(_Strict):
    code: str = Field(min_length=1, max_length=_MAX_CODE_LEN)


class SearchKnowledgeArgs(_Strict):
    query: str = Field(min_length=1, max_length=_MAX_QUERY_LEN)
    k: int = Field(default=5, ge=1, le=_MAX_RAG_K)


class ScreenStocksArgs(_Strict):
    priceMin: float | None = None
    priceMax: float | None = None
    changePercentMin: float | None = None
    changePercentMax: float | None = None
    volumeMin: float | None = None
    volumeMax: float | None = None
    amountMin: float | None = None
    amountMax: float | None = None
    keyword: str | None = Field(default=None, max_length=_MAX_KEYWORD_LEN)
    limit: int = Field(default=30, ge=1, le=_MAX_SCREEN)
    sortBy: Literal["price", "changePercent", "volume", "amount"] = "changePercent"
    sortOrder: Literal["asc", "desc"] = "desc"

    @field_validator(
        "priceMin",
        "priceMax",
        "changePercentMin",
        "changePercentMax",
        "volumeMin",
        "volumeMax",
        "amountMin",
        "amountMax",
    )
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value != value or value in (float("inf"), float("-inf")):  # NaN/Inf
            raise ValueError("筛选数值必须为有限数")
        return value


_ARG_MODELS: dict[str, type[BaseModel]] = {
    "get_market_overview": EmptyArgs,
    "get_quotes": GetQuotesArgs,
    "get_kline": GetKlineArgs,
    "search_instruments": SearchInstrumentsArgs,
    "get_capital_flow": GetCapitalFlowArgs,
    "get_financials": GetFinancialsArgs,
    "get_dragon_tiger": GetDragonTigerArgs,
    "get_news": CodeLimitArgs,
    "get_stock_profile": GetStockProfileArgs,
    "search_knowledge": SearchKnowledgeArgs,
    "screen_stocks": ScreenStocksArgs,
}


def _validation_error(exc: ValidationError) -> dict:
    return {
        "error": "工具参数无效",
        "details": [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg", "")}
            for err in exc.errors()[:8]
        ],
    }


TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "获取大盘指数（上证指数、深证成指、创业板指）的实时概览。",
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_quotes",
            "description": "获取一只或多只 A 股的实时快照行情（价格、涨跌幅、成交量额等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": _MAX_CODE_LEN},
                        "minItems": 1,
                        "maxItems": _MAX_CODES,
                        "description": "股票代码列表，如 ['600000'] 或 ['600000.SH','000001.SZ']",
                    }
                },
                "required": ["codes"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_kline",
            "description": "获取某只股票的历史K线（需已落库，否则可能为空）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "maxLength": _MAX_CODE_LEN, "description": "股票代码，如 600000.SH"},
                    "period": {
                        "type": "string",
                        "enum": ["day", "5min", "15min", "30min", "hour"],
                        "description": "K线周期，默认 day",
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_KLINE,
                        "description": f"返回最近多少根，默认 100，上限 {_MAX_KLINE}",
                    },
                },
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_instruments",
            "description": "按代码或名称搜索 A 股标的，返回匹配的代码与名称。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "maxLength": _MAX_QUERY_LEN, "description": "搜索关键词（代码或名称片段）"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_SEARCH,
                        "description": f"返回条数上限，默认 20，最大 {_MAX_SEARCH}",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_capital_flow",
            "description": "获取某只股票近 N 个交易日的资金流向（主力/超大单/大单/中单/小单净额）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "maxLength": _MAX_CODE_LEN, "description": "股票代码，如 600000.SH"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_FLOW,
                        "description": f"返回最近多少日，默认 30，最大 {_MAX_FLOW}",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_financials",
            "description": "获取某只股票的财务摘要（EPS/BPS/ROE/营收/净利润/毛利率，按报告期）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "maxLength": _MAX_CODE_LEN},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_FINANCIALS,
                        "description": f"返回最近多少期，默认 12，最大 {_MAX_FINANCIALS}",
                    },
                    "asOf": {
                        "type": "string",
                        "maxLength": 40,
                        "description": "可选历史时点：RFC3339 或 YYYY-MM-DD（上海日终）",
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dragon_tiger",
            "description": "获取某只股票的龙虎榜上榜记录（日期/原因/净买额）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "maxLength": _MAX_CODE_LEN},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_DRAGON,
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "获取某只股票的最新新闻/公告（标题/来源/时间/摘要）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "maxLength": _MAX_CODE_LEN},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_NEWS,
                    },
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_profile",
            "description": "获取某只股票的概览（所属行业/板块、上市日期、总股本/流通股、总市值/流通市值）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "maxLength": _MAX_CODE_LEN, "description": "股票代码，如 600000.SH"},
                },
                "required": ["code"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "语义检索本平台已落库的新闻/公告与历史早报（RAG）。"
                "当用户问及近期消息面、事件、主题背景、或需要支撑性资料时调用；"
                "返回最相关的文本片段（含来源与时间）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "maxLength": _MAX_QUERY_LEN,
                        "description": "检索问题/主题，如 '半导体 国产替代 政策'",
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_RAG_K,
                        "description": f"返回片段数，默认 5，最大 {_MAX_RAG_K}",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_stocks",
            "description": (
                "条件选股：基于全市场实时快照，按价格/涨跌幅/成交量/成交额区间与关键词筛选。"
                "免费快照粒度有限，仅用于盘面筛选。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "priceMin": {"type": "number", "description": "最低现价(元)"},
                    "priceMax": {"type": "number", "description": "最高现价(元)"},
                    "changePercentMin": {"type": "number", "description": "最低涨跌幅(%)"},
                    "changePercentMax": {"type": "number", "description": "最高涨跌幅(%)"},
                    "volumeMin": {"type": "number", "description": "最低成交量"},
                    "volumeMax": {"type": "number", "description": "最高成交量"},
                    "amountMin": {"type": "number", "description": "最低成交额(元)"},
                    "amountMax": {"type": "number", "description": "最高成交额(元)"},
                    "keyword": {"type": "string", "maxLength": _MAX_KEYWORD_LEN, "description": "名称或代码包含的关键词"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_SCREEN,
                        "description": f"返回条数上限，默认 30，最大 {_MAX_SCREEN}",
                    },
                    "sortBy": {
                        "type": "string",
                        "enum": ["price", "changePercent", "volume", "amount"],
                        "description": "排序字段，默认 changePercent",
                    },
                    "sortOrder": {"type": "string", "enum": ["asc", "desc"]},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

_SCREEN_KEYS = {
    "priceMin",
    "priceMax",
    "changePercentMin",
    "changePercentMax",
    "volumeMin",
    "volumeMax",
    "amountMin",
    "amountMax",
    "keyword",
}


def execute_tool(name: str, arguments: dict[str, Any] | None = None) -> dict:
    model = _ARG_MODELS.get(name)
    if model is None:
        return {"error": f"未知工具: {name}"}
    try:
        args = model.model_validate(arguments or {})
    except ValidationError as exc:
        return _validation_error(exc)

    if name == "get_market_overview":
        return {"indices": market.get_market_overview()}
    if name == "get_quotes":
        assert isinstance(args, GetQuotesArgs)
        quotes: list[dict] = []
        for raw in args.codes:
            q = market.get_quote(raw)
            if q is not None:
                quotes.append(q)
        return {"quotes": quotes}
    if name == "get_kline":
        assert isinstance(args, GetKlineArgs)
        result = market.get_kline(args.symbol, args.period, args.count)
        return {
            "kline": result["bars"],
            "dataQuality": result["dataQuality"],
        }
    if name == "search_instruments":
        assert isinstance(args, SearchInstrumentsArgs)
        return {
            "instruments": market.search_instruments(args.query, args.limit)
        }
    if name == "get_capital_flow":
        assert isinstance(args, GetCapitalFlowArgs)
        return {"capitalFlow": market.get_capital_flow(args.code, args.limit)}
    if name == "get_financials":
        assert isinstance(args, GetFinancialsArgs)
        return {
            "financials": market.get_financials(
                args.code,
                args.limit,
                parse_as_of(args.asOf) if args.asOf else None,
            )
        }
    if name == "get_dragon_tiger":
        assert isinstance(args, GetDragonTigerArgs)
        return {"dragonTiger": market.get_dragon_tiger(args.code, args.limit)}
    if name == "get_news":
        assert isinstance(args, CodeLimitArgs)
        return {"news": market.get_news(args.code, args.limit)}
    if name == "get_stock_profile":
        assert isinstance(args, GetStockProfileArgs)
        return {"profile": market.get_stock_profile(args.code)}
    if name == "search_knowledge":
        assert isinstance(args, SearchKnowledgeArgs)
        from app.services import rag

        return {"results": rag.retrieve(args.query, args.k)}
    if name == "screen_stocks":
        assert isinstance(args, ScreenStocksArgs)
        payload = args.model_dump()
        filters = {k: v for k, v in payload.items() if k in _SCREEN_KEYS and v is not None}
        return market.screen_stocks(
            filters,
            args.limit,
            args.sortBy,
            args.sortOrder,
        )
    return {"error": f"未知工具: {name}"}
