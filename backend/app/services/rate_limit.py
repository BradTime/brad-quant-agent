"""In-process rate limit / 成本闸（个人单机起步；Redis 后置）。

两块：
- 行情手动刷新冷却（每用户 + 每标的）。
- AI 成本闸：对昂贵的 LLM 生成端点（问答/深研/早报）做**每用户每日配额** +
  **重型生成最小间隔**，防超额与连点。进程内、按本地自然日重置（粗粒度，足够个人用）。
"""

from __future__ import annotations

import threading
import time
from datetime import date

_LOCK = threading.Lock()
_LAST_REFRESH: dict[tuple[str, str], float] = {}

REFRESH_COOLDOWN_SEC = 60

# AI 成本闸状态（进程内）
_DAILY_COUNTS: dict[tuple[str, str], int] = {}  # (user_id, bucket) -> 当日已用次数
_LAST_HEAVY: dict[tuple[str, str], float] = {}  # (user_id, bucket) -> 上次时间戳
_DAILY_DAY: str = ""  # 当前计数所属自然日；跨日清零

_HEAVY_BUCKETS = {"research", "brief"}


def seconds_until_refresh_allowed(user_id: str, code: str) -> float | None:
    """Return seconds to wait if throttled, else None."""
    key = (user_id, code)
    now = time.time()
    with _LOCK:
        last = _LAST_REFRESH.get(key, 0.0)
        elapsed = now - last
        if elapsed < REFRESH_COOLDOWN_SEC:
            return REFRESH_COOLDOWN_SEC - elapsed
    return None


def mark_refresh(user_id: str, code: str) -> None:
    key = (user_id, code)
    with _LOCK:
        _LAST_REFRESH[key] = time.time()


def _bucket_quota(bucket: str) -> int:
    from app.core.config import settings

    return {
        "chat": settings.ai_daily_quota_chat,
        "research": settings.ai_daily_quota_research,
        "brief": settings.ai_daily_quota_brief,
        "backtest": settings.ai_daily_quota_backtest,
    }.get(bucket, 0)


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
        from app.core.config import settings

        interval = settings.ai_heavy_min_interval_sec if bucket in _HEAVY_BUCKETS else 0
    now = time.time()
    ymd = date.today().isoformat()
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
