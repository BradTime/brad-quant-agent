"""Seed deterministic market data for CI browser and performance tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models.market import DailyBar, Instrument


def main() -> None:
    fetched_at = datetime.now(UTC)
    start = date(2025, 1, 1)
    bars = []
    for index in range(260):
        day = start + timedelta(days=index)
        price = 9 + index * 0.005
        bars.append(
            {
                "code": "600000.SH",
                "trade_date": day,
                "open": price,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price + 0.03,
                "volume": 1_000_000 + index * 100,
                "amount": (1_000_000 + index * 100) * price,
                "source": "ci_fixture",
                "fetched_at": fetched_at,
            }
        )

    with SessionLocal() as session:
        session.execute(
            insert(Instrument)
            .values(
                code="600000.SH",
                name="浦发银行",
                exchange="SH",
                security_type="stock",
                status="listed",
                source="ci_fixture",
                fetched_at=fetched_at,
            )
            .on_conflict_do_update(
                index_elements=["code"],
                set_={"name": "浦发银行", "source": "ci_fixture", "fetched_at": fetched_at},
            )
        )
        statement = insert(DailyBar).values(bars)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    "open": statement.excluded.open,
                    "high": statement.excluded.high,
                    "low": statement.excluded.low,
                    "close": statement.excluded.close,
                    "volume": statement.excluded.volume,
                    "amount": statement.excluded.amount,
                    "source": statement.excluded.source,
                    "fetched_at": statement.excluded.fetched_at,
                },
            )
        )
        session.commit()


if __name__ == "__main__":
    main()
