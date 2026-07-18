from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import tools as ai_tools
from app.api.deps import get_current_user
from app.api.v1.market import _parse_financial_as_of
from app.main import app
from app.models.extra import FinancialSummary
from app.providers.akshare_provider import AkShareProvider
from app.providers.base import FinancialSummaryDTO
from app.services import ingest, market


@pytest.fixture
def financial_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    FinancialSummary.__table__.create(bind=engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(ingest, "SessionLocal", test_session)
    monkeypatch.setattr(market, "SessionLocal", test_session)
    try:
        yield test_session
    finally:
        engine.dispose()


def _provider(*items: FinancialSummaryDTO):
    return SimpleNamespace(name="test-financials", get_financials=lambda _code: list(items))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _dto(
    *,
    eps: Decimal = Decimal("1.0"),
    revenue: Decimal = Decimal("1000.0"),
    announced_at: datetime | None = None,
    available_at: datetime | None = None,
    announced_at_precision: str | None = None,
) -> FinancialSummaryDTO:
    return FinancialSummaryDTO(
        code="600000.SH",
        report_date=date(2025, 12, 31),
        announced_at=announced_at,
        available_at=available_at,
        announced_at_precision=announced_at_precision,
        eps=eps,
        bps=Decimal("10.0"),
        roe=Decimal("8.0"),
        revenue=revenue,
        net_profit=Decimal("100.0"),
        gross_margin=Decimal("20.0"),
    )


def test_same_financial_vintage_is_idempotent_and_keeps_earliest_available_at(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_fetch = datetime(2026, 3, 10, 2, tzinfo=UTC)
    later_fetch = datetime(2026, 3, 11, 2, tzinfo=UTC)
    monkeypatch.setattr(ingest, "_resolve", lambda *_args: _provider(_dto()))
    monkeypatch.setattr(ingest, "_now", lambda: first_fetch)
    ingest.ingest_financials("600000.SH")
    monkeypatch.setattr(ingest, "_now", lambda: later_fetch)
    ingest.ingest_financials("600000.SH")

    with financial_db() as session:
        rows = list(session.scalars(select(FinancialSummary)))

    assert len(rows) == 1
    assert _utc(rows[0].available_at) == first_fetch
    assert _utc(rows[0].fetched_at) == later_fetch
    assert len(rows[0].vintage) == 64


def test_changed_financial_values_append_a_new_vintage(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed = iter(
        (
            datetime(2026, 3, 10, 2, tzinfo=UTC),
            datetime(2026, 3, 20, 2, tzinfo=UTC),
        )
    )
    current = {"dto": _dto(eps=Decimal("1.0"))}
    monkeypatch.setattr(
        ingest,
        "_resolve",
        lambda *_args: _provider(current["dto"]),
    )
    monkeypatch.setattr(ingest, "_now", lambda: next(observed))
    ingest.ingest_financials("600000.SH")
    current["dto"] = _dto(eps=Decimal("1.2"))
    ingest.ingest_financials("600000.SH")

    with financial_db() as session:
        rows = list(
            session.scalars(
                select(FinancialSummary).order_by(FinancialSummary.available_at)
            )
        )

    assert len(rows) == 2
    assert [row.eps for row in rows] == [Decimal("1.0000"), Decimal("1.2000")]
    assert rows[0].vintage != rows[1].vintage


def test_as_of_returns_old_vintage_and_hides_future_revision(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    with financial_db() as session:
        session.add_all(
            [
                FinancialSummary(
                    id="old",
                    code="600000.SH",
                    report_date=date(2025, 12, 31),
                    available_at=datetime(2026, 3, 10, tzinfo=UTC),
                    vintage="a" * 64,
                    eps=Decimal("1.0"),
                    source="test",
                    fetched_at=datetime(2026, 3, 10, tzinfo=UTC),
                ),
                FinancialSummary(
                    id="new",
                    code="600000.SH",
                    report_date=date(2025, 12, 31),
                    available_at=datetime(2026, 3, 20, tzinfo=UTC),
                    vintage="b" * 64,
                    eps=Decimal("1.2"),
                    source="test",
                    fetched_at=datetime(2026, 3, 20, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    historical = market.get_financials(
        "600000.SH", as_of=datetime(2026, 3, 15, tzinfo=UTC)
    )
    current = market.get_financials("600000.SH")

    assert historical[0]["eps"] == 1.0
    assert historical[0]["availableAt"] == "2026-03-10T00:00:00+00:00"
    assert current[0]["eps"] == 1.2


def test_announced_at_precedes_provider_availability_and_fetch_time(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    announced = datetime(2026, 3, 5, 10, tzinfo=UTC)
    provider_available = datetime(2026, 3, 6, 10, tzinfo=UTC)
    fetched = datetime(2026, 3, 7, 10, tzinfo=UTC)
    monkeypatch.setattr(
        ingest,
        "_resolve",
        lambda *_args: _provider(
            _dto(announced_at=announced, available_at=provider_available)
        ),
    )
    monkeypatch.setattr(ingest, "_now", lambda: fetched)

    ingest.ingest_financials("600000.SH")

    with financial_db() as session:
        row = session.scalar(select(FinancialSummary))
    assert row is not None
    assert _utc(row.announced_at) == announced
    assert _utc(row.available_at) == announced


def test_missing_announcement_uses_first_fetch_time(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched = datetime(2026, 3, 7, 10, tzinfo=UTC)
    monkeypatch.setattr(ingest, "_resolve", lambda *_args: _provider(_dto()))
    monkeypatch.setattr(ingest, "_now", lambda: fetched)

    ingest.ingest_financials("600000.SH")

    with financial_db() as session:
        row = session.scalar(select(FinancialSummary))
    assert row is not None
    assert row.announced_at is None
    assert _utc(row.available_at) == fetched


def test_akshare_financials_parse_announcement_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "报告期": "2025-12-31",
                "公告日期": "2026-03-05",
                "基本每股收益": "1.20",
            }
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_financial_abstract_ths=lambda **_kwargs: frame),
    )

    row = AkShareProvider().get_financials("600000.SH")[0]

    assert row.announced_at == datetime(2026, 3, 5)
    assert row.available_at is None
    assert row.announced_at_precision == "date"
    assert row.eps == Decimal("1.20")


def test_date_only_announcement_is_hidden_intraday_and_visible_after_close(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ingest,
        "_resolve",
        lambda *_args: _provider(
            _dto(
                announced_at=datetime(2026, 3, 5),
                announced_at_precision="date",
            )
        ),
    )
    monkeypatch.setattr(
        ingest,
        "_now",
        lambda: datetime(2026, 3, 6, 2, tzinfo=UTC),
    )
    ingest.ingest_financials("600000.SH")

    before_close = market.get_financials(
        "600000.SH",
        as_of=datetime(2026, 3, 5, 6, 59, 59, tzinfo=UTC),
    )
    at_close = market.get_financials(
        "600000.SH",
        as_of=datetime(2026, 3, 5, 7, 0, tzinfo=UTC),
    )

    assert before_close == []
    assert at_close[0]["availableAt"] == "2026-03-05T07:00:00+00:00"
    assert at_close[0]["availabilityQuality"] == "source_announced_date_close"


def test_large_financial_decimals_quantize_without_float_round_trip() -> None:
    first = ingest._normalize_financial_metrics(
        _dto(revenue=Decimal("12345678901234567890.12344"))
    )
    second = ingest._normalize_financial_metrics(
        _dto(revenue=Decimal("12345678901234567890.12346"))
    )

    assert first["revenue"] == Decimal("12345678901234567890.1234")
    assert second["revenue"] == Decimal("12345678901234567890.1235")
    assert ingest._financial_vintage(first) != ingest._financial_vintage(second)


@pytest.mark.parametrize(
    ("field", "accepted", "overflow"),
    [
        (
            "revenue",
            Decimal("99999999999999999999.9999"),
            Decimal("100000000000000000000"),
        ),
        (
            "roe",
            Decimal("99999999.9999"),
            Decimal("100000000"),
        ),
    ],
)
def test_financial_decimal_respects_orm_numeric_precision_and_scale(
    field: str,
    accepted: Decimal,
    overflow: Decimal,
) -> None:
    column_type = FinancialSummary.__table__.c[field].type
    assert (column_type.precision, column_type.scale) in {(24, 4), (12, 4)}
    accepted_item = _dto()
    negative_accepted_item = _dto()
    overflow_item = _dto()
    negative_overflow_item = _dto()
    setattr(accepted_item, field, accepted)
    setattr(negative_accepted_item, field, -accepted)
    setattr(overflow_item, field, overflow)
    setattr(negative_overflow_item, field, -overflow)

    normalized = ingest._normalize_financial_metrics(accepted_item)
    negative_normalized = ingest._normalize_financial_metrics(
        negative_accepted_item
    )

    assert normalized[field] == accepted
    assert negative_normalized[field] == -accepted
    with pytest.raises(ValueError, match=field):
        ingest._normalize_financial_metrics(overflow_item)
    with pytest.raises(ValueError, match=field):
        ingest._normalize_financial_metrics(negative_overflow_item)


def test_financial_overflow_is_rejected_before_opening_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ingest,
        "_resolve",
        lambda *_args: _provider(
            _dto(revenue=Decimal("100000000000000000000"))
        ),
    )

    def database_must_not_open():
        raise AssertionError("database opened before financial validation")

    monkeypatch.setattr(ingest, "SessionLocal", database_must_not_open)

    with pytest.raises(ValueError, match="revenue"):
        ingest.ingest_financials("600000.SH")


def test_positive_and_negative_zero_share_one_vintage(
    financial_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = {"dto": _dto(eps=Decimal("-0.00001"))}
    monkeypatch.setattr(ingest, "_resolve", lambda *_args: _provider(current["dto"]))
    monkeypatch.setattr(
        ingest,
        "_now",
        lambda: datetime(2026, 3, 10, tzinfo=UTC),
    )
    ingest.ingest_financials("600000.SH")
    current["dto"] = _dto(eps=Decimal("0"))
    ingest.ingest_financials("600000.SH")

    with financial_db() as session:
        rows = list(session.scalars(select(FinancialSummary)))

    assert len(rows) == 1
    assert rows[0].eps == Decimal("0.0000")


def test_akshare_financials_preserve_large_source_decimal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "报告期": "2025-12-31",
                "营业收入": "12345678901234567890.1234",
            }
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_financial_abstract_ths=lambda **_kwargs: frame),
    )

    row = AkShareProvider().get_financials("600000.SH")[0]

    assert row.revenue == Decimal("12345678901234567890.1234")


def test_akshare_financials_preserve_exact_announcement_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "报告期": "2025-12-31",
                "发布时间": "2026-03-05 18:30:00",
            }
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_financial_abstract_ths=lambda **_kwargs: frame),
    )

    row = AkShareProvider().get_financials("600000.SH")[0]

    assert row.announced_at == datetime(2026, 3, 5, 18, 30)
    assert row.available_at == row.announced_at
    assert row.announced_at_precision == "datetime"


def test_ai_financial_tool_accepts_historical_as_of(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = next(
        item for item in ai_tools.TOOLS if item["function"]["name"] == "get_financials"
    )
    assert "asOf" in definition["function"]["parameters"]["properties"]
    captured: dict[str, object] = {}

    def fake_get_financials(
        code: str, limit: int, as_of: datetime | None = None
    ) -> list[dict]:
        captured.update(code=code, limit=limit, as_of=as_of)
        return [{"eps": 1.0}]

    monkeypatch.setattr(ai_tools.market, "get_financials", fake_get_financials)

    result = ai_tools.execute_tool(
        "get_financials",
        {"code": "600000.SH", "limit": 4, "asOf": "2026-03-05T14:30:00+08:00"},
    )

    assert result == {"financials": [{"eps": 1.0}]}
    assert captured == {
        "code": "600000.SH",
        "limit": 4,
        "as_of": _parse_financial_as_of("2026-03-05T14:30:00+08:00"),
    }


def test_financials_api_rejects_invalid_as_of_with_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="test-user")
    monkeypatch.setattr(market, "get_financials", lambda *_args, **_kwargs: [])
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/market/financials",
                params={"code": "600000.SH", "asOf": "not-a-time"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_financial_model_has_append_only_constraints(financial_db) -> None:
    table = FinancialSummary.__table__
    assert list(table.primary_key.columns.keys()) == ["id"]
    assert any(
        tuple(column.name for column in constraint.columns)
        == ("code", "report_date", "vintage")
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    )
    assert any(
        tuple(column.name for column in index.columns)
        == ("code", "report_date", "available_at")
        for index in table.indexes
    )
    with financial_db() as session:
        assert session.scalar(select(func.count()).select_from(FinancialSummary)) == 0
