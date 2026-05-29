"""Background scheduler (APScheduler) for periodic market-data refresh.

APScheduler is imported lazily so the module stays importable without the
dependency, and startup is guarded by ``settings.enable_scheduler``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_scheduler = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler

    from app.core.config import settings
    from app.services import market

    # APScheduler 自身的 INFO/WARNING（如任务跳过提示）对轮询缓存属正常现象，调高阈值降噪。
    logging.getLogger("apscheduler").setLevel(logging.ERROR)

    quote_secs = max(settings.quote_refresh_seconds, 1)
    index_secs = max(settings.index_refresh_seconds, 1)
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        market.refresh_quotes_job,
        "interval",
        seconds=quote_secs,
        id="refresh_quotes",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        market.refresh_indices_job,
        "interval",
        seconds=index_secs,
        id="refresh_indices",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("行情调度器已启动（行情 %ss / 指数 %ss）", quote_secs, index_secs)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
