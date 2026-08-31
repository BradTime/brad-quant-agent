"""Distributed Redis rate limits with deterministic in-process fallback.

两块：
- 行情手动刷新冷却（每用户 + 每标的）。
- AI 成本闸：对昂贵的 LLM 生成端点（问答/深研/早报）做**每用户每日配额** +
  **重型生成最小间隔**，防超额与连点。Redis 路径跨 API 副本原子共享；
  未配置 Redis 的开发/测试环境继续使用进程内状态。
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from datetime import datetime, timedelta
from datetime import time as dt_time

from app.core import redis_client
from app.core.config import settings
from app.core.tz import MARKET_TZ, market_now

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LAST_REFRESH: dict[tuple[str, str], float] = {}

REFRESH_COOLDOWN_SEC = 60

# AI 成本闸状态（进程内）
_DAILY_COUNTS: dict[tuple[str, str], int] = {}  # (user_id, bucket) -> 当日已用次数
_LAST_HEAVY: dict[tuple[str, str], float] = {}  # (user_id, bucket) -> 上次时间戳
_DAILY_DAY: str = ""  # 当前计数所属自然日；跨日清零

_HEAVY_BUCKETS = {"research", "brief"}

_AI_GATE_SCRIPT = """
local interval_ttl = redis.call('PTTL', KEYS[2])
if tonumber(ARGV[2]) > 0 and interval_ttl > 0 then
  return {1, interval_ttl}
end
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if tonumber(ARGV[1]) > 0 and count >= tonumber(ARGV[1]) then
  return {2, count}
end
if tonumber(ARGV[1]) > 0 then
  local updated = redis.call('INCR', KEYS[1])
  if updated == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[3])
  end
end
if tonumber(ARGV[2]) > 0 then
  redis.call('SET', KEYS[2], '1', 'PX', ARGV[2])
end
return {0, 0}
"""


def _refresh_key(user_id: str, code: str) -> str:
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    return redis_client.key("rate", f"{{{user_hash}}}", "refresh", code)


def _seconds_to_market_midnight() -> int:
    now = market_now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), dt_time.min, MARKET_TZ)
    return max(int((tomorrow - now).total_seconds()), 60)


def seconds_until_refresh_allowed(user_id: str, code: str) -> float | None:
    """Return seconds to wait if throttled, else None."""
    client = redis_client.get_redis()
    if client is not None:
        try:
            ttl_ms = int(client.pttl(_refresh_key(user_id, code)))
            return ttl_ms / 1000 if ttl_ms > 0 else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis refresh cooldown read failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("refresh_cooldown_read", exc) from exc
    key = (user_id, code)
    now = time.time()
    with _LOCK:
        last = _LAST_REFRESH.get(key, 0.0)
        elapsed = now - last
        if elapsed < REFRESH_COOLDOWN_SEC:
            return REFRESH_COOLDOWN_SEC - elapsed
    return None


def mark_refresh(user_id: str, code: str) -> None:
    client = redis_client.get_redis()
    if client is not None:
        try:
            client.set(
                _refresh_key(user_id, code),
                b"1",
                px=REFRESH_COOLDOWN_SEC * 1000,
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis refresh cooldown write failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("refresh_cooldown_write", exc) from exc
    key = (user_id, code)
    with _LOCK:
        _LAST_REFRESH[key] = time.time()


def acquire_refresh_cooldown(user_id: str, code: str) -> float | None:
    """Atomically reserve a refresh slot; return remaining wait when occupied."""
    client = redis_client.get_redis()
    if client is not None:
        key = _refresh_key(user_id, code)
        try:
            acquired = client.set(
                key,
                b"1",
                nx=True,
                px=REFRESH_COOLDOWN_SEC * 1000,
            )
            if acquired:
                return None
            ttl_ms = int(client.pttl(key))
            return max(ttl_ms, 1) / 1000
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis refresh cooldown acquire failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("refresh_cooldown_acquire", exc) from exc
    key = (user_id, code)
    now = time.time()
    with _LOCK:
        elapsed = now - _LAST_REFRESH.get(key, 0.0)
        if elapsed < REFRESH_COOLDOWN_SEC:
            return REFRESH_COOLDOWN_SEC - elapsed
        _LAST_REFRESH[key] = now
    return None


def _bucket_quota(bucket: str) -> int:
    return {
        "chat": settings.ai_daily_quota_chat,
        "research": settings.ai_daily_quota_research,
        "brief": settings.ai_daily_quota_brief,
        "backtest": settings.ai_daily_quota_backtest,
    }.get(bucket, 0)


def _redis_ai_cost_gate(
    client,
    user_id: str,
    bucket: str,
    quota: int,
    interval: float,
) -> str | None:
    ymd = market_now().date().isoformat()
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:16]
    slot = f"{{{user_hash}}}"
    count_key = redis_client.key("quota", slot, ymd, bucket)
    interval_key = redis_client.key("quota", slot, "interval", bucket)
    script = client.register_script(_AI_GATE_SCRIPT)
    result = script(
        keys=[count_key, interval_key],
        args=[
            max(int(quota), 0),
            max(int(interval * 1000), 0),
            48 * 60 * 60 * 1000,
        ],
        client=client,
    )
    code = int(result[0])
    value = int(result[1])
    if code == 1:
        return f"操作过于频繁，请 {max(math.ceil(value / 1000), 1)} 秒后再试。"
    if code == 2:
        return f"今日额度已用尽（{bucket} 每日 {quota} 次），请明日再试。"
    return None


def ai_cost_gate(
    user_id: str,
    bucket: str,
    *,
    quota: int | None = None,
    interval: float | None = None,
) -> str | None:
    """AI 生成成本闸：超限返回**面向用户的中文提示**（调用方据此拒绝并不触发 LLM）；
    放行则消费一次配额并刷新间隔时间戳，返回 ``None``。原子操作。

    ``quota`` / ``interval`` 省略时取配置（``quota<=0`` 不限配额，``interval<=0`` 不限间隔）。
    """
    global _DAILY_DAY
    if quota is None:
        quota = _bucket_quota(bucket)
    if interval is None:
        interval = settings.ai_heavy_min_interval_sec if bucket in _HEAVY_BUCKETS else 0
    client = redis_client.get_redis()
    if client is not None:
        try:
            return _redis_ai_cost_gate(
                client,
                user_id,
                bucket,
                int(quota),
                float(interval),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis AI cost gate failed: %s", type(exc).__name__)
            if redis_client.required():
                raise redis_client.unavailable("ai_cost_gate", exc) from exc
    now = time.time()
    ymd = market_now().date().isoformat()
    key = (user_id, bucket)
    with _LOCK:
        if ymd != _DAILY_DAY:  # 跨日整体清零，避免内存泄漏
            _DAILY_COUNTS.clear()
            _DAILY_DAY = ymd
        if interval and interval > 0:
            wait = interval - (now - _LAST_HEAVY.get(key, 0.0))
            if wait > 0:
                return f"操作过于频繁，请 {int(wait) + 1} 秒后再试。"
        if quota and quota > 0 and _DAILY_COUNTS.get(key, 0) >= quota:
            return f"今日额度已用尽（{bucket} 每日 {quota} 次），请明日再试。"
        # 放行：消费
        if quota and quota > 0:
            _DAILY_COUNTS[key] = _DAILY_COUNTS.get(key, 0) + 1
        if interval and interval > 0:
            _LAST_HEAVY[key] = now
    return None
