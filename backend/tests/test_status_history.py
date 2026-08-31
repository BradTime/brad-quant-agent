"""Historical PIT ST status: provider, atomic ingestion, and backtest limits."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.data import Bar, _load_hfq_bars_in_session
from app.backtest.runner import _rule_quality
from app.db.base import Base
from app.models.market import (
    AdjustFactor,
    DailyBar,
    Instrument,
    InstrumentStatusHistory,
)
from app.providers.baostock_provider import BaoStockProvider
from app.providers.base import InstrumentStatusDTO, ProviderUnavailable
from app.providers.tushare_provider import TushareProvider
from app.services import ingest


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _BaoResult:
    def __init__(self, rows: list[list[str]], *, error_code: str = "0"):
        self.rows = rows
        self.error_code = error_code
        self.error_msg = "query failed" if error_code != "0" else ""
        self.index = -1

    def next(self) -> bool:
        self.index += 1
        return self.index < len(self.rows)

    def get_row_data(self) -> list[str]:
        return self.rows[self.index]


def _sqlite_sessions(*tables):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=list(tables))
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_tushare_namechange_maps_effective_intervals_without_date_filters(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.providers import tushare_provider

    captured: dict = {}

    def fake_post(url, *, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse(
            {
                "code": 0,
                "data": {
                    "fields": [
                        "ts_code",
                        "name",
                        "start_date",
                        "end_date",
                        "ann_date",
                        "change_reason",
                    ],
                    "items": [
                        ["600848.SH", "上海临港", "20151118", None, "20151117", "改名"],
                        ["600848.SH", "ST自仪", "20010508", "20061008", None, "ST"],
                        ["600848.SH", "*ST自仪", "20061009", "20070513", "20061008", "退市风险警示"],
                    ],
                },
            }
        )

    monkeypatch.setattr(tushare_provider.settings, "tushare_token", "test-token")
    monkeypatch.setattr(tushare_provider.httpx, "post", fake_post)

    rows = TushareProvider().get_status_history("600848.SH")

    assert [row.start_date for row in rows] == [
        date(2001, 5, 8),
        date(2006, 10, 9),
        date(2015, 11, 18),
    ]
    assert [row.status_type for row in rows] == ["st", "star_st", "normal"]
    assert captured["json"]["params"] == {"ts_code": "600848.SH"}
    assert "start_date" not in captured["json"]["params"]
    assert "end_date" not in captured["json"]["params"]


def test_baostock_daily_is_st_is_compressed_into_intervals(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.providers import baostock_provider

    result = _BaoResult(
        [
            ["2007-05-10", "1"],
            ["2007-05-11", "1"],
            ["2007-05-14", "0"],
            ["2007-05-15", "0"],
            ["2008-04-01", "1"],
        ]
    )

    @contextmanager
    def fake_session():
        yield SimpleNamespace(query_history_k_data_plus=lambda *_args, **_kwargs: result)

    monkeypatch.setattr(baostock_provider, "_bs_session", fake_session)
    rows = BaoStockProvider().get_status_history("600848.SH")

    assert [
        (row.start_date, row.end_date, row.status_type)
        for row in rows
    ] == [
        (date(2007, 5, 10), date(2007, 5, 11), "st"),
        (date(2007, 5, 14), date(2007, 5, 15), "normal"),
        (date(2008, 4, 1), None, "st"),
    ]


def test_status_ingestion_replaces_atomically_and_preserves_on_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    engine, sessions = _sqlite_sessions(InstrumentStatusHistory.__table__)
    provider = SimpleNamespace(
        name="test-status",
        get_status_history=lambda _code: [
            InstrumentStatusDTO(
                code="600848.SH",
                start_date=date(2001, 5, 8),
                end_date=date(2007, 5, 13),
                name="ST自仪",
                status_type="st",
            ),
            InstrumentStatusDTO(
                code="600848.SH",
                start_date=date(2007, 5, 14),
                name="自仪股份",
                status_type="normal",
            ),
        ],
    )
    monkeypatch.setattr(ingest, "SessionLocal", sessions)
    monkeypatch.setattr(ingest, "_resolve", lambda *_args: provider)
    try:
        assert ingest.ingest_status_history("600848.SH") == 2
        with sessions() as session:
            assert len(session.execute(select(InstrumentStatusHistory)).scalars().all()) == 2

        provider.get_status_history = lambda _code: []
        with pytest.raises(ingest.EmptyDatasetError):
            ingest.ingest_status_history("600848.SH")
        with sessions() as session:
            assert len(session.execute(select(InstrumentStatusHistory)).scalars().all()) == 2
    finally:
        engine.dispose()


def test_daily_backtest_uses_effective_st_interval_for_main_board_limit():
    engine, sessions = _sqlite_sessions(
        Instrument.__table__,
        DailyBar.__table__,
        AdjustFactor.__table__,
        InstrumentStatusHistory.__table__,
    )
    try:
        with sessions.begin() as session:
            session.add(
                Instrument(
                    code="600848.SH",
                    name="上海临港",
                    exchange="SH",
                    list_date=date(1994, 3, 24),
                    source="test",
                )
            )
            session.add_all(
                [
                    InstrumentStatusHistory(
                        code="600848.SH",
                        start_date=date(2001, 5, 8),
                        end_date=date(2007, 5, 13),
                        name="ST自仪",
                        status_type="st",
                        source="test",
                    ),
                    InstrumentStatusHistory(
                        code="600848.SH",
                        start_date=date(2007, 5, 14),
                        end_date=None,
                        name="自仪股份",
                        status_type="normal",
                        source="test",
                    ),
                ]
            )
            session.add_all(
                [
                    DailyBar(
                        code="600848.SH",
                        trade_date=date(2007, 5, 11),
                        open=10,
                        high=10,
                        low=10,
                        close=10,
                        volume=100,
                        amount=1000,
                        source="test",
                    ),
                    DailyBar(
                        code="600848.SH",
                        trade_date=date(2007, 5, 14),
                        open=10,
                        high=10,
                        low=10,
                        close=10,
                        volume=100,
                        amount=1000,
                        source="test",
                    ),
                ]
            )

        with sessions() as session:
            bars, coverage = _load_hfq_bars_in_session(
                session,
                "600848.SH",
                "2007-05-11",
                "2007-05-14",
            )
        assert coverage == "none"
        assert [bar.status_type for bar in bars] == ["st", "normal"]
        assert [bar.limit_ratio for bar in bars] == [0.05, 0.10]
    finally:
        engine.dispose()


def test_rule_quality_distinguishes_full_partial_and_unavailable_status():
    def bar(status_type: str | None) -> Bar:
        return Bar(
            code="600848.SH",
            date=date(2007, 5, 11),
            open=10,
            high=10,
            low=10,
            close=10,
            volume=100,
            amount=1000,
            status_type=status_type,
        )

    assert _rule_quality({"600848.SH": [bar("st")]})["historicalST"] == "full"
    assert (
        _rule_quality({"600848.SH": [bar("st"), bar(None)]})["historicalST"]
        == "partial"
    )
    assert (
        _rule_quality({"600848.SH": [bar(None)]})["historicalST"]
        == "unavailable"
    )


def test_explicit_provider_must_advertise_requested_capability():
    with pytest.raises(ProviderUnavailable):
        ingest._resolve("akshare", "status_history")


def test_batch_status_cli_reports_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from app.cli import main

    monkeypatch.setattr(ingest, "ingest_status_history", lambda _code, _provider: 3)

    assert (
        main(
            [
                "backfill-status-history",
                "--codes",
                "600848.SH,000001.SZ",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "6 个区间" in output
    assert "失败 0" in output
