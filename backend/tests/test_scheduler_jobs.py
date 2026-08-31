"""Scheduler job registration for watchlist EOD / news refresh."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services import scheduler as scheduler_mod


@pytest.fixture(autouse=True)
def _reset_scheduler():
    scheduler_mod.shutdown_scheduler()
    yield
    scheduler_mod.shutdown_scheduler()


def test_scheduler_registers_watchlist_eod_and_news_jobs(monkeypatch):
    added: list[str] = []

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            self.running = False

        def add_job(self, fn, trigger, **kwargs):
            added.append(kwargs["id"])

        def start(self):
            self.running = True

        def shutdown(self, wait=False):
            self.running = False

    monkeypatch.setattr(
        "apscheduler.schedulers.background.BackgroundScheduler",
        FakeScheduler,
    )
    monkeypatch.setattr(
        "app.core.config.settings.enable_brief_scheduler",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        "app.core.config.settings.enable_watchlist_eod_backfill",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.core.config.settings.enable_watchlist_news_refresh",
        True,
        raising=False,
    )

    # Avoid importing market refresh side effects during job wrappers
    monkeypatch.setattr("app.services.market.refresh_quotes_job", MagicMock())
    monkeypatch.setattr("app.services.market.refresh_indices_job", MagicMock())

    sched = scheduler_mod.start_scheduler()
    assert sched is not None
    assert "watchlist_eod_backfill" in added
    assert "watchlist_news_refresh_am" in added
    assert "watchlist_news_refresh_pm" in added
    assert "ingest_dragon_tiger" in added


def test_cli_backfill_passes_dragon_tiger_flag(monkeypatch, capsys):
    from app import cli

    captured: dict = {}

    def fake_backfill(*args, **kwargs):
        captured.update(kwargs)
        return {
            "daily": 1,
            "adjust": 0,
            "capital_flow": 0,
            "financials": 0,
            "news": 0,
            "minute": 0,
            "dragon_tiger": 3,
            "errors": 0,
            "runs": [{"code": "X", "status": "ready", "failedDatasets": []}],
        }

    monkeypatch.setattr("app.services.ingest.backfill_codes", fake_backfill)

    exit_code = cli.main(
        ["backfill", "--codes", "X", "--start", "2024-01-01", "--end", "2024-01-03"]
    )
    assert exit_code == 0
    assert captured.get("include_dragon_tiger") is True
    assert "龙虎榜 3" in capsys.readouterr().out

    exit_code = cli.main(
        [
            "backfill",
            "--codes",
            "X",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-03",
            "--no-dragon-tiger",
        ]
    )
    assert exit_code == 0
    assert captured.get("include_dragon_tiger") is False
