"""LLMQuant Data 接入（经官方 MCP server，stdio）。

后端在这里**充当 MCP 客户端**：按需 `npx -y @llmquant/data-mcp` 拉起官方 MCP server，
完成握手后批量调用 `macro_indicator_snapshot` 取美国宏观快照。用官方 MCP 接口而非
逆向其私有 REST，对上游更稳。

优雅降级（与项目其它数据源一致）：未启用 / 无 API key / 无 npx / 超时 / 出错 → 返回 []，
绝不影响早报主流程。仅在早报生成（低频）时调用，子进程开销可接受。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

from app.core.config import settings

logger = logging.getLogger(__name__)


def _extract_payload(result: dict) -> dict | None:
    """从 MCP tools/call 结果里取出工具返回的 JSON 负载。

    兼容两种形态：``result.structuredContent`` 或 ``result.content[0].text``（JSON 串）。
    """
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


def get_us_macro_snapshot(timeout: int = 60) -> list[dict]:
    """取一组美国宏观指标的最新快照（CPI / 核心PCE / 失业率 / 联邦基金利率 / 10Y / 10y-2y 等）。

    返回 ``[{indicator, title, value, date, deltaPct, units}, ...]``；任何失败均降级为 []。
    """
    if not settings.llmquant_enabled or not settings.llmquant_api_key:
        return []
    npx = shutil.which("npx")
    if not npx:
        logger.info("未找到 npx，跳过 LLMQuant 海外宏观取数（降级为空）")
        return []

    indicators = settings.llmquant_macro_list
    if not indicators:
        return []

    # 批量 JSON-RPC：initialize -> initialized -> 每个指标一个 tools/call，靠 stdin EOF 结束
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
    id_to_indicator: dict[int, str] = {}
    for offset, indicator in enumerate(indicators):
        req_id = 2 + offset
        id_to_indicator[req_id] = indicator
        messages.append(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {
                    "name": "macro_indicator_snapshot",
                    "arguments": {"indicator": indicator},
                },
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
    except Exception as exc:  # noqa: BLE001  (子进程/超时/环境问题均降级)
        logger.warning("LLMQuant 海外宏观取数失败，降级为空：%s", exc)
        return []

    out: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            continue
        rid = msg.get("id")
        if rid not in id_to_indicator or "result" not in msg:
            continue
        payload = _extract_payload(msg["result"])
        if not payload:
            continue
        item = payload.get("item") or {}
        latest = item.get("latest") or {}
        if latest.get("value") is None:
            continue
        out.append(
            {
                "indicator": item.get("indicator") or id_to_indicator[rid],
                "title": item.get("title"),
                "value": latest.get("value"),
                "date": latest.get("date"),
                "deltaPct": item.get("deltaPct"),
                "units": item.get("units"),
            }
        )
    if not out:
        logger.info("LLMQuant 海外宏观无有效返回（降级为空）")
    return out
