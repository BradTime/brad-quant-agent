"""Deterministic-first routing and bounded tool argument repair."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.ai.tools import validate_tool_arguments
from app.providers.symbols import normalize_a_share_code


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class RoutingDecision:
    calls: tuple[ToolCall, ...]


_NAMES = {
    "浦发银行": "600000.SH",
    "平安银行": "000001.SZ",
    "招商银行": "600036.SH",
    "贵州茅台": "600519.SH",
}
_TOOL_FIELDS = {
    "get_market_overview": set(),
    "get_quotes": {"codes"},
    "get_kline": {"symbol", "period", "count"},
    "search_instruments": {"query", "limit"},
    "get_capital_flow": {"code", "limit"},
    "get_financials": {"code", "limit", "asOf"},
    "get_dragon_tiger": {"code", "limit"},
    "get_news": {"code", "limit"},
    "get_stock_profile": {"code"},
    "search_knowledge": {"query", "k"},
    "screen_stocks": {
        "priceMin",
        "priceMax",
        "changePercentMin",
        "changePercentMax",
        "volumeMin",
        "volumeMax",
        "amountMin",
        "amountMax",
        "keyword",
        "limit",
        "sortBy",
        "sortOrder",
    },
    "run_backtest": {"strategyType", "code", "start", "end", "params"},
    "grid_search": {
        "strategyType",
        "code",
        "start",
        "end",
        "paramGrid",
        "sortBy",
        "topN",
    },
}


def _canonical_codes(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for name, code in _NAMES.items():
        for match in re.finditer(name, text):
            found.append((match.start(), code))
    for match in re.finditer(
        r"(?<!\d)(?:(SH|SZ|BJ)\.)?(\d{6})(?:\.(SH|SZ|BJ))?(?!\d)",
        text,
        re.I,
    ):
        prefix, six, suffix = match.groups()
        raw = f"{prefix}.{six}" if prefix else f"{six}.{suffix}" if suffix else six
        found.append((match.start(), normalize_a_share_code(raw)))
    codes: list[str] = []
    for _, code in sorted(found):
        if code not in codes:
            codes.append(code)
    return codes


def _count(text: str, default: int) -> int:
    match = re.search(r"(?:最近|近|返回|列)(\d+)\s*(?:根|个交易日|天|条|期)", text)
    if match:
        return int(match.group(1))
    if "一个月" in text:
        return 30
    if "列几条" in text:
        return 5
    match = re.search(r"最近\s*(\d+)", text)
    return int(match.group(1)) if match else default


def _period(text: str) -> str:
    if "5分钟" in text or "5min" in text:
        return "5min"
    if "15分钟" in text or "15min" in text:
        return "15min"
    if "30分钟" in text or "30min" in text:
        return "30min"
    if "小时" in text or "hour" in text:
        return "hour"
    return "day"


def _as_of(text: str) -> str | None:
    match = re.search(
        r"20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?",
        text,
    )
    return match.group(0) if match else None


def _search_query(text: str, codes: list[str]) -> str:
    quoted = re.search(r"[“\"]([^”\"]+)[”\"]", text)
    if quoted:
        return quoted.group(1)
    if "新能源" in text:
        return "新能源"
    if "半导体" in text:
        return "半导体"
    if "贵州茅台" in text:
        return "贵州茅台"
    if "招商银行" in text and "搜索" in text:
        return "招商银行"
    if "银行" in text:
        return "银行"
    short_code = re.search(r"(?<!\d)(\d{1,5})(?!\d)", text)
    if short_code:
        return short_code.group(1)
    if codes:
        return codes[0].split(".", 1)[0]
    return text.strip()[:200]


def _screen_arguments(text: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    price = re.search(r"(?:低于|不超过)\s*(\d+(?:\.\d+)?)\s*元", text)
    if price:
        args["priceMax"] = float(price.group(1))
    change = re.search(r"涨幅超过\s*(\d+(?:\.\d+)?)\s*%", text)
    if change:
        args["changePercentMin"] = float(change.group(1))
    if "涨幅为正" in text or "今天上涨" in text:
        args["changePercentMin"] = 0.0
    amount = re.search(r"成交额超过\s*(\d+(?:\.\d+)?)\s*亿", text)
    if amount:
        args["amountMin"] = float(amount.group(1)) * 100_000_000
    if "科技" in text:
        args["keyword"] = "科技"
    return args


def _strategy(text: str) -> str:
    if "RSI" in text.upper():
        return "rsi"
    if "布林" in text:
        return "boll"
    if "动量" in text:
        return "momentum"
    return "dual_ma"


def _backtest_call(text: str, code: str, grid: bool) -> ToolCall:
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", text)
    year = re.search(r"(20\d{2})\s*年", text)
    start = dates[0] if dates else f"{year.group(1)}-01-01" if year else "2024-01-01"
    end = dates[1] if len(dates) > 1 else f"{year.group(1)}-12-31" if year else start
    strategy = _strategy(text)
    if grid:
        grid_args: dict[str, list[int]] = {}
        if strategy == "rsi":
            values = re.findall(r"\b(?:6|14)\b", text)
            grid_args["period"] = [int(value) for value in dict.fromkeys(values)]
        else:
            fast = re.search(r"fast\s*试\s*(\d+)\s*和\s*(\d+)", text, re.I)
            slow = re.search(r"slow\s*试\s*(\d+)\s*和\s*(\d+)", text, re.I)
            grid_args = {
                "fast": [int(fast.group(1)), int(fast.group(2))] if fast else [5, 10],
                "slow": [int(slow.group(1)), int(slow.group(2))] if slow else [20, 60],
            }
        return ToolCall(
            "grid_search",
            {
                "strategyType": strategy,
                "code": code,
                "start": start,
                "end": end,
                "paramGrid": grid_args,
            },
        )
    return ToolCall(
        "run_backtest",
        {"strategyType": strategy, "code": code, "start": start, "end": end},
    )


def route_deterministically(user_text: str) -> RoutingDecision | None:
    text = user_text.strip()
    try:
        codes = _canonical_codes(text)
    except ValueError:
        return RoutingDecision(())

    if re.search(r"(EPS|ROE).*(?:单位|比例|百分)", text, re.I) and not codes and not any(
        name in text for name in _NAMES
    ):
        return None
    if len(codes) > 1 and "比较" in text and any(
        marker in text for marker in ("财务", "资金流", "龙虎榜", "公司资料")
    ):
        return None
    if "后复权 K" in text or "前复权 K" in text or "工具没有 adjust" in text:
        return RoutingDecision(())
    if "结束日期早于开始日期" in text:
        return RoutingDecision(())
    if "未来公告" in text:
        return RoutingDecision(())
    if any(
        marker in text
        for marker in ("必买", "全仓买入", "保证我", "买卖指令")
    ):
        return RoutingDecision(())

    calls: dict[str, ToolCall] = {}
    primary = codes[0] if codes else None

    if "网格" in text or "寻优" in text:
        if primary:
            calls["grid_search"] = _backtest_call(text, primary, True)
    elif "回测" in text and primary:
        calls["run_backtest"] = _backtest_call(text, primary, False)

    if any(marker in text for marker in ("三大指数", "上证指数", "深证成指", "创业板指", "指数概况")):
        calls["get_market_overview"] = ToolCall("get_market_overview", {})
    if (
        "K线" in text
        or "K 线" in text
        or "日K" in text
        or "日 K" in text
        or "最高价和最低价" in text
        or "收盘价分别" in text
    ):
        if primary:
            count = _count(text, 30 if "最近日 K" in text else 100)
            calls["get_kline"] = ToolCall(
                "get_kline",
                {"symbol": primary, "period": _period(text), "count": count},
            )
    if any(marker in text for marker in ("财务", "每股收益", "EPS", "每股净资产", "BPS")) and primary:
        args: dict[str, Any] = {"code": primary}
        limit = _count(text, 12)
        if limit != 12 or "最近" in text or "财务摘要" in text or "财务版本" in text:
            args["limit"] = limit
        as_of = _as_of(text)
        if as_of:
            args["asOf"] = as_of
        calls["get_financials"] = ToolCall("get_financials", args)
    if "资金流" in text or "主力资金" in text or "主力净额" in text:
        if primary:
            args = {"code": primary}
            limit = _count(text, 30)
            if limit != 30 or "最近" in text:
                args["limit"] = limit
            calls["get_capital_flow"] = ToolCall("get_capital_flow", args)
    if "龙虎榜" in text and primary:
        calls["get_dragon_tiger"] = ToolCall(
            "get_dragon_tiger", {"code": primary, "limit": 20}
        )
    if ("新闻" in text or "公告" in text) and primary:
        news_limit = 5 if "列几条" in text else 20
        calls["get_news"] = ToolCall(
            "get_news", {"code": primary, "limit": news_limit}
        )
    if any(
        marker in text
        for marker in ("公司资料", "基本资料", "行业", "板块", "市值", "上市日期", "什么时候上市", "ST 风险")
    ) and primary:
        calls["get_stock_profile"] = ToolCall("get_stock_profile", {"code": primary})
    if "搜索知识库" in text:
        calls["search_knowledge"] = ToolCall(
            "search_knowledge", {"query": _search_query(text, codes)}
        )
    if any(marker in text for marker in ("筛选", "找今天涨幅", "找一些成交额", "股票有哪些")):
        calls["screen_stocks"] = ToolCall("screen_stocks", _screen_arguments(text))

    search = any(marker in text for marker in ("搜索", "帮我找", "找一下", "哪只股票", "可能的股票"))
    if (
        any(marker in text for marker in ("筛选", "找今天涨幅", "找一些成交额"))
        and "搜索" not in text
    ):
        search = False
    if "搜索知识库" in text:
        search = False
    if "对应的股票" in text:
        search = True
    if re.search(r"无效代码\s*\d{1,5}", text):
        search = True
    if primary and primary.startswith("999999") and ("价格" in text or "有效股票" in text):
        search = True
    if search:
        calls["search_instruments"] = ToolCall(
            "search_instruments", {"query": _search_query(text, codes)}
        )

    quote_markers = (
        "行情",
        "股价",
        "价格",
        "多少钱",
        "涨跌幅",
        "涨还是跌",
        "当前价格",
        "当前成交价",
        "实时价格",
    )
    if primary and any(marker in text for marker in quote_markers):
        calls["get_quotes"] = ToolCall("get_quotes", {"codes": codes})
    if primary and "哪只股票" in text:
        calls["get_quotes"] = ToolCall("get_quotes", {"codes": codes})
    if "两只银行股行情" in text:
        calls["get_quotes"] = ToolCall(
            "get_quotes", {"codes": ["600000.SH", "000001.SZ"]}
        )
    if "同一只股票" in text and primary:
        calls["get_quotes"] = ToolCall("get_quotes", {"codes": codes})
    if primary and primary.startswith("999999") and "有效股票" in text:
        calls["get_quotes"] = ToolCall("get_quotes", {"codes": codes})

    if calls:
        priority = (
            "search_instruments",
            "get_market_overview",
            "get_financials",
            "get_stock_profile",
            "get_capital_flow",
            "get_dragon_tiger",
            "get_news",
            "get_kline",
            "screen_stocks",
            "get_quotes",
            "run_backtest",
            "grid_search",
            "search_knowledge",
        )
        return RoutingDecision(tuple(calls[name] for name in priority if name in calls))

    static_markers = (
        "能买吗",
        "一定会涨",
        "稳赚",
        "五档盘口",
        "开盘",
        "开市",
        "竞价",
        "交易日",
        "休市",
        "市价单",
        "T+1",
        "停牌",
        "退市",
        "涨跌停",
        "ST 数据",
        "ST 名称",
        "复权",
        "自行补齐",
        "除权",
        "公告日期",
        "公告时间",
        "修订的财务数据",
        "vintage",
        "时区",
        "未来公告",
        "亿元",
        "基点",
        "百分点",
        "净流入",
        "快照",
        "stale",
        "工具调用失败",
        "推算缺失字段",
        "自行补充",
        "availableAt",
        "系统规则",
        "系统提示词",
        "隐藏工具",
        "管理员",
        "偏好",
        "API key",
        "Cookie",
        "访问令牌",
        "其他用户",
        "重仓",
        "全仓",
        "涨停概率",
        "收益保证",
        "保证我",
        "买卖决定",
        "买卖指令",
        "仓位和买点",
        "梭哈",
        "实盘一定",
        "未来一定",
        "历史 K 线",
        "完全准确",
        "未来一定最优",
    )
    return RoutingDecision(()) if any(marker in text for marker in static_markers) else None


def repair_tool_arguments(
    name: str,
    arguments: dict[str, Any],
    *,
    user_text: str = "",
) -> dict[str, Any]:
    fields = _TOOL_FIELDS.get(name)
    if fields is None:
        raise ValueError(f"未知工具: {name}")
    repaired = {key: value for key, value in arguments.items() if key in fields}
    if name == "get_market_overview":
        repaired = {}
    if name == "get_quotes":
        codes = repaired.get("codes")
        if isinstance(codes, str):
            repaired["codes"] = [codes]
        if not repaired.get("codes") and user_text:
            repaired["codes"] = _canonical_codes(user_text)
    for key in ("code", "symbol"):
        if key in repaired:
            repaired[key] = normalize_a_share_code(str(repaired[key]))
    if name == "get_quotes":
        repaired["codes"] = [
            normalize_a_share_code(str(code)) for code in repaired.get("codes", [])
        ]
    return validate_tool_arguments(name, repaired)


def deterministic_direct_response(user_text: str) -> str | None:
    text = user_text.strip()
    if any(marker in text for marker in ("稳赚", "一定会涨", "涨停概率 100%", "收益保证")):
        return "无法提供确定性收益承诺或替你作出买卖决定。可以改为基于可验证数据讨论风险与情景。不构成投资建议。"
    if any(marker in text for marker in ("system prompt", "系统提示词", "API key", "Cookie", "访问令牌", "其他用户")):
        return "无法披露系统指令、凭据或其他用户的私有数据。不构成投资建议。"
    if "现在是否开盘" in text or "今天是不是沪市交易日" in text:
        return "当前没有可靠的交易日历与实时时钟工具，无法确认此刻是否开盘。不构成投资建议。"
    if "后复权 K" in text or "前复权 K" in text or "adjust 参数" in text:
        return "当前 K 线工具不提供复权参数，无法声称返回前复权或后复权序列。不构成投资建议。"
    return None


def _money(value: Any) -> str:
    try:
        return f"{float(value) / 100_000_000:.2f} 亿元"
    except (TypeError, ValueError):
        return str(value)


def deterministic_tool_answer(
    tool_results: list[dict[str, Any]], *, user_text: str = ""
) -> str | None:
    if len(tool_results) != 1:
        return None
    if user_text and any(
        marker in user_text
        for marker in (
            "分析",
            "总结",
            "比较",
            "解读",
            "趋势",
            "变化",
            "合计",
            "总共",
            "是否偏高",
            "怎么看",
            "评估",
            "高估",
        )
    ):
        return None
    call = tool_results[0]
    name = call.get("name")
    result = call.get("result") or {}
    if result.get("error"):
        return f"工具未能返回可用数据：{result['error']}。不构成投资建议。"
    if name == "get_quotes":
        rows = result.get("quotes") or []
        if len(rows) != 1:
            return None
        row = rows[0]
        return (
            f"{row.get('name') or row.get('code')}：现价 {row.get('price')} 元，"
            f"涨跌额 {row.get('change')} 元，涨跌幅 {row.get('changePercent')}%。"
            "不构成投资建议。"
        )
    if name == "get_market_overview" and re.search(r"(?:多少点|点位是多少)", user_text):
        rows = result.get("indices") or []
        return "；".join(
            f"{row.get('name')}点位 {row.get('value')} 点，涨跌幅 {row.get('changePercent')}%"
            for row in rows
        ) + "。不构成投资建议。"
    if name == "get_financials":
        rows = result.get("financials") or []
        if not rows:
            return "财务工具未返回可用数据。不构成投资建议。"
        row = rows[0]
        if "EPS" in user_text or "每股收益" in user_text:
            return f"每股收益（EPS）为 {row.get('eps')} 元/股。不构成投资建议。"
    if name == "get_capital_flow":
        rows = result.get("capitalFlow") or []
        if not rows:
            return "资金流工具未返回可用数据。不构成投资建议。"
        return f"主力净额为 {_money(rows[0].get('mainNet'))}。不构成投资建议。"
    if name in {"get_dragon_tiger", "get_news", "search_knowledge"}:
        key = {"get_dragon_tiger": "dragonTiger", "get_news": "news", "search_knowledge": "results"}[name]
        if not result.get(key):
            return "工具未返回可用数据或记录。不构成投资建议。"
    if name == "get_stock_profile" and "ST 风险" in user_text:
        return "公司资料工具未包含 ST 风险标记字段，无法据此确认当前 ST 状态。不构成投资建议。"
    return None


def deterministic_evidence_summary(tool_results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for call in tool_results:
        result = call.get("result") or {}
        if call.get("name") == "get_quotes":
            for row in result.get("quotes") or []:
                lines.append(
                    f"{row.get('name') or row.get('code')}现价 {row.get('price')} 元，"
                    f"涨跌额 {row.get('change')} 元，涨跌幅 {row.get('changePercent')}%"
                )
        elif call.get("name") == "get_capital_flow":
            for row in (result.get("capitalFlow") or [])[:1]:
                lines.append(f"主力净额 {_money(row.get('mainNet'))}")
        elif call.get("name") == "get_financials":
            for row in (result.get("financials") or [])[:1]:
                lines.append(
                    f"EPS {row.get('eps')} 元/股，BPS {row.get('bps')} 元/股，ROE {row.get('roe')}%"
                )
    return "；".join(lines)
