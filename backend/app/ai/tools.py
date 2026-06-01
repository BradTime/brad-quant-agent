"""Tool registry exposed to the LLM (function calling) + dispatch.

Tools are thin wrappers over the existing market service so the AI orchestrator,
embedded assistants, and (later) autonomous agents all share one capability layer.
"""

from __future__ import annotations

from typing import Any

from app.services import market

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "获取大盘指数（上证指数、深证成指、创业板指）的实时概览。",
            "parameters": {"type": "object", "properties": {}, "required": []},
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
                        "items": {"type": "string"},
                        "description": "股票代码列表，如 ['600000'] 或 ['600000.SH','000001.SZ']",
                    }
                },
                "required": ["codes"],
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
                    "symbol": {"type": "string", "description": "股票代码，如 600000.SH"},
                    "period": {
                        "type": "string",
                        "enum": ["day", "5min", "15min", "30min", "hour"],
                        "description": "K线周期，默认 day",
                    },
                    "count": {"type": "integer", "description": "返回最近多少根，默认 100"},
                },
                "required": ["symbol"],
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
                    "query": {"type": "string", "description": "搜索关键词（代码或名称片段）"},
                    "limit": {"type": "integer", "description": "返回条数上限，默认 20"},
                },
                "required": ["query"],
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
                    "code": {"type": "string", "description": "股票代码，如 600000.SH"},
                    "limit": {"type": "integer", "description": "返回最近多少日，默认 30"},
                },
                "required": ["code"],
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
                    "code": {"type": "string"},
                    "limit": {"type": "integer", "description": "返回最近多少期，默认 12"},
                },
                "required": ["code"],
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
                    "code": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["code"],
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
                    "code": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["code"],
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
                    "code": {"type": "string", "description": "股票代码，如 600000.SH"},
                },
                "required": ["code"],
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
                    "query": {"type": "string", "description": "检索问题/主题，如 '半导体 国产替代 政策'"},
                    "k": {"type": "integer", "description": "返回片段数，默认 5"},
                },
                "required": ["query"],
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
                    "keyword": {"type": "string", "description": "名称或代码包含的关键词"},
                    "limit": {"type": "integer", "description": "返回条数上限，默认 30"},
                    "sortBy": {
                        "type": "string",
                        "enum": ["price", "changePercent", "volume", "amount"],
                        "description": "排序字段，默认 changePercent",
                    },
                    "sortOrder": {"type": "string", "enum": ["asc", "desc"]},
                },
                "required": [],
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


def execute_tool(name: str, arguments: dict[str, Any]) -> dict:
    if name == "get_market_overview":
        return {"indices": market.get_market_overview()}
    if name == "get_quotes":
        codes = arguments.get("codes") or []
        quotes: list[dict] = []
        for raw in codes:
            q = market.get_quote(str(raw))
            if q is not None:
                quotes.append(q)
        return {"quotes": quotes}
    if name == "get_kline":
        return {
            "kline": market.get_kline(
                str(arguments.get("symbol", "")),
                str(arguments.get("period", "day")),
                int(arguments.get("count", 100) or 100),
            )
        }
    if name == "search_instruments":
        return {
            "instruments": market.search_instruments(
                str(arguments.get("query", "")),
                int(arguments.get("limit", 20) or 20),
            )
        }
    if name == "get_capital_flow":
        return {
            "capitalFlow": market.get_capital_flow(
                str(arguments.get("code", "")), int(arguments.get("limit", 30) or 30)
            )
        }
    if name == "get_financials":
        return {
            "financials": market.get_financials(
                str(arguments.get("code", "")), int(arguments.get("limit", 12) or 12)
            )
        }
    if name == "get_dragon_tiger":
        return {
            "dragonTiger": market.get_dragon_tiger(
                str(arguments.get("code", "")), int(arguments.get("limit", 20) or 20)
            )
        }
    if name == "get_news":
        return {
            "news": market.get_news(
                str(arguments.get("code", "")), int(arguments.get("limit", 20) or 20)
            )
        }
    if name == "get_stock_profile":
        return {"profile": market.get_stock_profile(str(arguments.get("code", "")))}
    if name == "search_knowledge":
        from app.services import rag

        return {
            "results": rag.retrieve(
                str(arguments.get("query", "")), int(arguments.get("k", 0) or 0) or None
            )
        }
    if name == "screen_stocks":
        filters = {k: v for k, v in arguments.items() if k in _SCREEN_KEYS and v is not None}
        return market.screen_stocks(
            filters,
            int(arguments.get("limit", 30) or 30),
            str(arguments.get("sortBy", "changePercent")),
            str(arguments.get("sortOrder", "desc")),
        )
    return {"error": f"未知工具: {name}"}
