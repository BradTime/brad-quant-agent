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
]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict:
    if name == "get_market_overview":
        return {"indices": market.get_market_overview()}
    if name == "get_quotes":
        codes = arguments.get("codes") or []
        return {"quotes": market.get_quotes_by_codes(list(codes))}
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
    return {"error": f"未知工具: {name}"}
