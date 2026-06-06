"""LLMQuant Data 接入（经官方 MCP server，stdio）。

后端在这里**充当 MCP 客户端**：按需 `npx -y @llmquant/data-mcp` 拉起官方 MCP server，
完成握手后批量调用工具（美国宏观快照 / wiki 知识检索）。用官方 MCP 接口而非逆向其私有 REST。

成本控制：结果带 **TTL 进程内缓存**（默认 12h），避免每次早报生成都重复 npx + 计费；
调度器每日定时刷新缓存。优雅降级：未启用 / 无 key / 无 npx / 超时 / 出错 → 返回 []。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time

from app.core.config import settings

logger = logging.getLogger(__name__)

# 进程内 TTL 缓存：key -> (timestamp, value)
_cache: dict[str, tuple[float, list]] = {}


def _cached(key: str, producer, force: bool = False) -> list:
    ttl = settings.llmquant_cache_ttl_seconds
    now = time.time()
    if not force:
        hit = _cache.get(key)
        if hit and (now - hit[0]) < ttl:
            return hit[1]
    value = producer()
    if value:  # 只缓存非空结果，避免把瞬时失败的 [] 固化进缓存
        _cache[key] = (now, value)
    return value


def _extract_payload(result: dict) -> dict | None:
    """从 MCP tools/call 结果取出工具返回的 JSON 负载（兼容 structuredContent / content[].text）。"""
    if not isinstance(result, dict) or result.get("isError"):
        return None
    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        return sc
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            try:
                return json.loads(block["text"])
            except (ValueError, TypeError):
                return None
    return None


def _run_mcp(tool_calls: list[tuple[str, dict]], timeout: int = 60) -> dict[int, dict]:
    """一次 npx 子进程跑完一批 tools/call。返回 {request_id: payload}。失败返回 {}。

    request_id 从 2 起（1 留给 initialize）。
    """
    if not (settings.llmquant_enabled and settings.llmquant_api_key) or not tool_calls:
        return {}
    npx = shutil.which("npx")
    if not npx:
        logger.info("未找到 npx，跳过 LLMQuant 取数（降级为空）")
        return {}

    messages: list[dict] = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "brad-quant-agent", "version": "0.1.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]
    for offset, (name, args) in enumerate(tool_calls):
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": 2 + offset,
                "method": "tools/call",
                "params": {"name": name, "arguments": args},
            }
        )
    stdin_payload = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n"

    env = os.environ.copy()
    env["LLMQUANT_API_KEY"] = settings.llmquant_api_key
    if settings.llmquant_base_url:
        env["LLMQUANT_BASE_URL"] = settings.llmquant_base_url

    try:
        proc = subprocess.run(
            [npx, "-y", "@llmquant/data-mcp"],
            input=stdin_payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLMQuant 取数失败，降级为空：%s", exc)
        return {}

    out: dict[int, dict] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            continue
        rid = msg.get("id")
        if isinstance(rid, int) and rid >= 2 and "result" in msg:
            payload = _extract_payload(msg["result"])
            if payload is not None:
                out[rid] = payload
    return out


# ---------- 美国宏观快照（带缓存） ----------


def get_us_macro_snapshot(force: bool = False) -> list[dict]:
    """取一组美国宏观指标最新快照（CPI/核心PCE/失业率/联邦基金利率/10Y/10y-2y 等）。带 TTL 缓存。"""
    indicators = settings.llmquant_macro_list
    if not indicators:
        return []

    def produce() -> list[dict]:
        results = _run_mcp([("macro_indicator_snapshot", {"indicator": ind}) for ind in indicators])
        out: list[dict] = []
        for rid in sorted(results):
            item = (results[rid] or {}).get("item") or {}
            latest = item.get("latest") or {}
            if latest.get("value") is None:
                continue
            out.append(
                {
                    "indicator": item.get("indicator"),
                    "title": item.get("title"),
                    "value": latest.get("value"),
                    "date": latest.get("date"),
                    "deltaPct": item.get("deltaPct"),
                    "units": item.get("units"),
                }
            )
        return out

    return _cached("macro", produce, force=force)


def refresh_macro_job() -> None:
    """调度器入口：每日定时强制刷新海外宏观缓存（让当日早报无需在生成时再取数）。"""
    try:
        n = len(get_us_macro_snapshot(force=True))
        logger.info("LLMQuant 海外宏观缓存已刷新：%d 项", n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLMQuant 海外宏观缓存刷新失败：%s", exc)


# ---------- 量化知识背景（wiki 语义检索，带缓存） ----------


def search_quant_knowledge(query: str, k: int | None = None) -> list[dict]:
    """对 LLMQuant wiki 知识库做语义检索，返回若干条目（标题/摘要/slug）。按 query 缓存。"""
    query = (query or "").strip()
    if not settings.llmquant_knowledge_enabled or not query:
        return []
    k = k or settings.llmquant_knowledge_topk

    def produce() -> list[dict]:
        results = _run_mcp([("wiki_search", {"query": query[:2000], "topK": min(max(k, 1), 10)})])
        items = (results.get(2) or {}).get("items") or []
        return [
            {
                "title": it.get("title"),
                "summary": it.get("summary"),
                "slug": it.get("slug"),
                "wikiItemId": it.get("wikiItemId"),
            }
            for it in items
        ]

    return _cached(f"wiki:{query}", produce)
