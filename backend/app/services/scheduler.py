"""Background scheduler (APScheduler) for periodic market-data refresh.

APScheduler is imported lazily so the module stays importable without the
dependency, and startup is guarded by ``settings.enable_scheduler``.
Jobs are wrapped with ``job_health`` so ``/ready`` can reflect last success/failure.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_scheduler = None


def _add_outbox_job(scheduler) -> None:
    from app.core.config import settings

    if not settings.enable_auth_outbox_scheduler:
        return
    from app.services.verification_outbox import deliver_due_verification_emails

    scheduler.add_job(
        deliver_due_verification_emails,
        "interval",
        seconds=max(settings.auth_outbox_poll_seconds, 1),
        id="deliver_verification_email_outbox",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )


def _add_training_maintenance_job(scheduler) -> None:
    from app.services.training_data import purge_expired_traces

    scheduler.add_job(
        purge_expired_traces,
        "interval",
        hours=24,
        id="purge_expired_training_traces",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    from apscheduler.schedulers.background import BackgroundScheduler

    from app.core.config import settings
    from app.core.tz import MARKET_TZ
    from app.services import job_health, market

    # APScheduler 自身的 INFO/WARNING（如任务跳过提示）对轮询缓存属正常现象，调高阈值降噪。
    logging.getLogger("apscheduler").setLevel(logging.ERROR)

    quote_secs = max(settings.quote_refresh_seconds, 1)
    index_secs = max(settings.index_refresh_seconds, 1)
    scheduler = BackgroundScheduler(timezone=MARKET_TZ)
    if not settings.enable_scheduler:
        _add_outbox_job(scheduler)
        _add_training_maintenance_job(scheduler)
        scheduler.start()
        _scheduler = scheduler
        logger.info("认证邮件 outbox 调度器已启动")
        return scheduler

    @job_health.tracked("refresh_quotes")
    def _refresh_quotes() -> None:
        market.refresh_quotes_job()

    @job_health.tracked("refresh_indices")
    def _refresh_indices() -> None:
        market.refresh_indices_job()

    scheduler.add_job(
        _refresh_quotes,
        "interval",
        seconds=quote_secs,
        id="refresh_quotes",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _refresh_indices,
        "interval",
        seconds=index_secs,
        id="refresh_indices",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )

    # 模拟交易：用最新快照价撮合挂单（限价单），cache-only 价源、开销小
    @job_health.tracked("match_pending_orders")
    def _match_pending_tracked() -> None:
        from app.services import trading

        trading.try_match_pending()

    def _match_pending_job() -> None:
        try:
            _match_pending_tracked()
        except Exception as exc:  # noqa: BLE001
            logger.debug("挂单撮合失败（忽略）：%s", exc)

    scheduler.add_job(
        _match_pending_job,
        "interval",
        seconds=max(index_secs, 15),
        id="match_pending_orders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )

    # 日终：收盘后撤销未成交 DAY 挂单并解冻 T+1（不依赖用户再次访问）
    @job_health.tracked("settle_day_orders")
    def _settle_day_tracked() -> None:
        from app.services import trading

        trading.settle_all_accounts()

    def _settle_day_orders_job() -> None:
        try:
            _settle_day_tracked()
        except Exception as exc:  # noqa: BLE001
            logger.debug("日终结算失败（忽略）：%s", exc)

    scheduler.add_job(
        _settle_day_orders_job,
        "cron",
        hour=15,
        minute=5,
        id="settle_day_orders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # 收盘后落库近期龙虎榜（全市场按日期范围，非逐股）
    @job_health.tracked("ingest_dragon_tiger")
    def _ingest_dragon_tiger_tracked() -> None:
        from datetime import date, timedelta

        from app.services import ingest

        end = date.today()
        start = end - timedelta(days=7)
        ingest.ingest_dragon_tiger(start.isoformat(), end.isoformat())

    def _ingest_dragon_tiger_job() -> None:
        try:
            _ingest_dragon_tiger_tracked()
        except Exception as exc:  # noqa: BLE001
            logger.warning("龙虎榜落库失败（忽略）：%s", exc)

    scheduler.add_job(
        _ingest_dragon_tiger_job,
        "cron",
        hour=16,
        minute=5,
        id="ingest_dragon_tiger",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=1800,
    )

    # 收盘后增量回填自选股（日K + 复权 + 资金流 + 财务 + 新闻；不含分钟）
    if settings.enable_watchlist_eod_backfill:

        @job_health.tracked("watchlist_eod_backfill")
        def _watchlist_eod_tracked() -> None:
            from datetime import date, timedelta

            from app.services import ingest

            codes = ingest.watchlist_codes()
            if not codes:
                logger.info("自选股 EOD 回填跳过：自选为空")
                return
            end = date.today()
            start = end - timedelta(days=max(settings.watchlist_eod_lookback_days, 1))
            ingest.backfill_codes(
                codes,
                start.isoformat(),
                end.isoformat(),
                include_dragon_tiger=False,
            )

        def _watchlist_eod_job() -> None:
            try:
                _watchlist_eod_tracked()
            except Exception as exc:  # noqa: BLE001
                logger.warning("自选股 EOD 回填失败（忽略）：%s", exc)

        scheduler.add_job(
            _watchlist_eod_job,
            "cron",
            hour=settings.watchlist_eod_cron_hour,
            minute=settings.watchlist_eod_cron_minute,
            id="watchlist_eod_backfill",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=1800,
        )

    # 自选股新闻：盘前 + 盘后各一次
    if settings.enable_watchlist_news_refresh:

        @job_health.tracked("watchlist_news_refresh")
        def _watchlist_news_tracked() -> None:
            from app.services import ingest

            codes = ingest.watchlist_codes()
            if not codes:
                logger.info("自选股新闻刷新跳过：自选为空")
                return
            limit = max(settings.watchlist_news_limit, 1)
            for code in codes:
                try:
                    ingest.ingest_news(code, limit)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("自选股新闻刷新失败 code=%s: %s", code, exc)

        def _watchlist_news_job() -> None:
            try:
                _watchlist_news_tracked()
            except Exception as exc:  # noqa: BLE001
                logger.warning("自选股新闻刷新失败（忽略）：%s", exc)

        for hour, job_id in ((7, "watchlist_news_refresh_am"), (18, "watchlist_news_refresh_pm")):
            scheduler.add_job(
                _watchlist_news_job,
                "cron",
                hour=hour,
                minute=0,
                id=job_id,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=1800,
            )

    if settings.enable_brief_scheduler:
        from app.services import brief

        # 早报生成前先把海外宏观缓存刷新（避免在生成时同步 npx 取数 + 重复计费）
        if settings.llmquant_enabled:
            from app.providers import llmquant

            @job_health.tracked("refresh_us_macro")
            def _refresh_macro() -> None:
                llmquant.refresh_macro_job()

            scheduler.add_job(
                _refresh_macro,
                "cron",
                hour=settings.brief_cron_hour,
                minute=max(settings.brief_cron_minute - 30, 0),
                id="refresh_us_macro",
                max_instances=1,
                coalesce=True,
                misfire_grace_time=1800,
            )

        @job_health.tracked("daily_brief")
        def _daily_brief() -> None:
            brief.generate_daily_global()

        scheduler.add_job(
            _daily_brief,
            "cron",
            hour=settings.brief_cron_hour,
            minute=settings.brief_cron_minute,
            id="daily_brief",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    _add_outbox_job(scheduler)
    _add_training_maintenance_job(scheduler)
    scheduler.start()
    _scheduler = scheduler
    logger.info("行情调度器已启动（行情 %ss / 指数 %ss）", quote_secs, index_secs)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_running() -> bool:
    return _scheduler is not None and bool(getattr(_scheduler, "running", False))
