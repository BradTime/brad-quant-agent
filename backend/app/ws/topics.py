"""WebSocket topic 规范化与订阅配额。"""

from __future__ import annotations

import re
import time

from app.providers import symbols

TOPIC_INDICES = "market.indices"
_QUOTE_PREFIX = "market.quote."
# 规范代码：6 位数字 + .SH/.SZ/.BJ
_CANON_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

MAX_TOPICS_PER_CONNECTION = 32
MAX_SUBSCRIBE_BATCH = 20
# 每连接滑动窗口内允许的 subscribe 次数（含重复），防刷
SUBSCRIBE_RATE_LIMIT = 30
SUBSCRIBE_RATE_WINDOW_SECONDS = 10.0

# ws id -> (window_start_monotonic, count)
_subscribe_buckets: dict[int, tuple[float, int]] = {}


def normalize_topic(raw: str) -> str | None:
    """返回合法主题，非法返回 None。"""
    if not isinstance(raw, str):
        return None
    topic = raw.strip()
    if topic == TOPIC_INDICES:
        return TOPIC_INDICES
    if not topic.startswith(_QUOTE_PREFIX):
        return None
    code = topic[len(_QUOTE_PREFIX) :]
    if not code:
        return None
    # 允许裸 6 位或已规范代码
    try:
        six, ex = symbols.split_canonical(code)
        if not (six.isdigit() and len(six) == 6):
            return None
        canonical = symbols.to_canonical(six, ex)
    except Exception:  # noqa: BLE001
        return None
    if not _CANON_RE.fullmatch(canonical):
        return None
    return f"{_QUOTE_PREFIX}{canonical}"


def filter_topics(raw_topics: list[str]) -> tuple[list[str], list[str]]:
    """返回 (accepted, rejected)。"""
    accepted: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in raw_topics:
        topic = normalize_topic(raw)
        if topic is None:
            rejected.append(str(raw)[:64])
            continue
        if topic in seen:
            continue
        seen.add(topic)
        accepted.append(topic)
        if len(accepted) >= MAX_SUBSCRIBE_BATCH:
            break
    return accepted, rejected


def allow_subscribe(connection_id: int) -> bool:
    """每连接滑动窗口限流；超限返回 False。"""
    now = time.monotonic()
    start, count = _subscribe_buckets.get(connection_id, (now, 0))
    if now - start >= SUBSCRIBE_RATE_WINDOW_SECONDS:
        start, count = now, 0
    count += 1
    _subscribe_buckets[connection_id] = (start, count)
    return count <= SUBSCRIBE_RATE_LIMIT


def clear_subscribe_bucket(connection_id: int) -> None:
    _subscribe_buckets.pop(connection_id, None)
