"""Resumable full-market Tushare bootstrap for prediction operations.

Fetches daily bars and adjustment factors by trade date (two API calls per
session), plus CSI300 and effective-dated name/ST history. Existing complete
dates are skipped, so rerunning is safe after interruption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.core.dtutil import parse_date
from app.core.ohlc import validate_ohlc
from app.db.session import SessionLocal
from app.models.ingestion import (
    IngestionRun,
    TushareBootstrapDailyManifest,
)
from app.models.market import (
    AdjustFactor,
    DailyBar,
    Instrument,
    InstrumentStatusHistory,
    InstrumentSuspensionDaily,
)
from app.providers.tushare_provider import _status_type
from app.services import ingest

DAILY_FIELDS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "vol",
    "amount",
)
ADJUST_FIELDS = ("ts_code", "trade_date", "adj_factor")
STATUS_FIELDS = (
    "ts_code",
    "name",
    "start_date",
    "end_date",
    "ann_date",
    "change_reason",
)
SUSPEND_FIELDS = (
    "ts_code",
    "trade_date",
    "suspend_timing",
    "suspend_type",
)


def _request(
    client: httpx.Client,
    api_name: str,
    params: dict[str, Any],
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    response = client.post(
        settings.tushare_base_url,
        json={
            "api_name": api_name,
            "token": settings.tushare_token,
            "params": params,
            "fields": ",".join(fields),
        },
    )
    response.raise_for_status()
    body = response.json()
    if body.get("code") != 0:
        raise RuntimeError(
            f"Tushare {api_name} failed: {body.get('msg')}"
        )
    data = body.get("data") or {}
    response_fields = data.get("fields") or []
    return [
        dict(zip(response_fields, values, strict=True))
        for values in data.get("items") or []
        if len(values) == len(response_fields)
    ]


def _paged_request(
    client: httpx.Client,
    api_name: str,
    params: dict[str, Any],
    fields: tuple[str, ...],
    *,
    page_size: int = 6_000,
) -> list[dict[str, Any]]:
    rows = []
    offset = 0
    while True:
        page = _request(
            client,
            api_name,
            {
                **params,
                "offset": offset,
                "limit": page_size,
            },
            fields,
        )
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += len(page)


def _insert(session, model):
    return (
        sqlite_insert(model)
        if session.get_bind().dialect.name == "sqlite"
        else pg_insert(model)
    )


def _content_sha256(rows: list[dict[str, Any]]) -> str:
    def canonical(value: Any, key: str | None = None) -> Any:
        if isinstance(value, Decimal):
            quantum = (
                Decimal("0.000001")
                if key
                in {
                    "adjust_factor",
                    "fore_adjust_factor",
                    "back_adjust_factor",
                }
                else Decimal("0.0001")
            )
            return format(value.quantize(quantum), "f")
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                key: canonical(item)
                if not isinstance(item, Decimal)
                else canonical(item, key)
                for key, item in value.items()
                if key != "fetched_at"
            }
        return value

    normalized = [canonical(row) for row in rows]
    return hashlib.sha256(
        json.dumps(
            sorted(normalized, key=lambda value: value["code"]),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _canonical(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if "." not in text:
        return None
    symbol, market = text.split(".", 1)
    if market not in {"SH", "SZ", "BJ"}:
        return None
    if len(symbol) != 6 or not symbol.isdigit():
        return None
    return text


def _trading_dates(
    client: httpx.Client, start: date, end: date
) -> list[date]:
    rows = _request(
        client,
        "trade_cal",
        {
            "exchange": "SSE",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "is_open": "1",
        },
        ("exchange", "cal_date", "is_open", "pretrade_date"),
    )
    return sorted(
        parsed
        for row in rows
        if (parsed := parse_date(row.get("cal_date"))) is not None
    )


def _complete_dates(dates: list[date]) -> set[date]:
    if not dates:
        return set()
    with SessionLocal() as session:
        manifests = {
            row.trade_date: row
            for row in session.execute(
                select(TushareBootstrapDailyManifest).where(
                    TushareBootstrapDailyManifest.trade_date.in_(
                        dates
                    )
                )
            ).scalars()
        }
        daily_counts = dict(
            session.execute(
                select(DailyBar.trade_date, func.count())
                .where(
                DailyBar.trade_date.in_(dates),
                DailyBar.source == "tushare",
                DailyBar.code != "000300.SH",
                )
                .group_by(DailyBar.trade_date)
            ).all()
        )
        factor_counts = dict(
            session.execute(
                select(AdjustFactor.ex_date, func.count())
                .where(
                    AdjustFactor.ex_date.in_(dates),
                    AdjustFactor.source == "tushare",
                )
                .group_by(AdjustFactor.ex_date)
            ).all()
        )
    corrupt = [
        day
        for day, manifest in manifests.items()
        if daily_counts.get(day) != manifest.daily_count
        or factor_counts.get(day) != manifest.factor_count
    ]
    if corrupt:
        raise RuntimeError(
            f"manifested market data count mismatch at {corrupt[0]}"
        )
    return set(manifests)


def _daily_values(rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict]:
    values = []
    for row in rows:
        code = _canonical(row.get("ts_code"))
        trade_date = parse_date(row.get("trade_date"))
        if code is None or trade_date is None:
            continue
        checked = validate_ohlc(
            open_value=row.get("open"),
            high_value=row.get("high"),
            low_value=row.get("low"),
            close_value=row.get("close"),
            volume=(
                float(row["vol"]) * 100
                if row.get("vol") is not None
                else None
            ),
            amount=(
                float(row["amount"]) * 1_000
                if row.get("amount") is not None
                else None
            ),
            code=code,
            bar_time=trade_date,
        )
        values.append(
            {
                "code": code,
                "trade_date": trade_date,
                "open": checked.open,
                "high": checked.high,
                "low": checked.low,
                "close": checked.close,
                "volume": int(checked.volume or 0),
                "amount": checked.amount,
                "source": "tushare",
                "fetched_at": fetched_at,
            }
        )
    return values


def _adjust_values(rows: list[dict[str, Any]], fetched_at: datetime) -> list[dict]:
    values = []
    for row in rows:
        code = _canonical(row.get("ts_code"))
        trade_date = parse_date(row.get("trade_date"))
        factor = row.get("adj_factor")
        if code is None or trade_date is None or factor is None:
            continue
        numeric = Decimal(str(factor))
        if numeric <= 0:
            raise ValueError(f"{code} {trade_date} adjustment factor invalid")
        values.append(
            {
                "code": code,
                "ex_date": trade_date,
                "adjust_factor": numeric,
                "fore_adjust_factor": None,
                "back_adjust_factor": numeric,
                "source": "tushare",
                "fetched_at": fetched_at,
            }
        )
    return values


def bootstrap_market(
    client: httpx.Client,
    start: date,
    end: date,
    *,
    max_dates: int | None,
) -> None:
    dates = _trading_dates(client, start, end)
    complete = _complete_dates(dates)
    pending = [day for day in dates if day not in complete]
    if max_dates is not None:
        pending = pending[:max_dates]
    for index, day in enumerate(pending, start=1):
        api_date = day.strftime("%Y%m%d")
        daily_rows = _paged_request(
            client, "daily", {"trade_date": api_date}, DAILY_FIELDS
        )
        adjust_rows = _paged_request(
            client,
            "adj_factor",
            {"trade_date": api_date},
            ADJUST_FIELDS,
        )
        fetched_at = datetime.now(UTC)
        daily_values = _daily_values(daily_rows, fetched_at)
        adjust_values = _adjust_values(adjust_rows, fetched_at)
        if len(daily_values) < 4_000 or len(adjust_values) < 4_000:
            raise RuntimeError(
                f"{day} incomplete: daily={len(daily_values)} "
                f"adjust={len(adjust_values)}"
            )
        with SessionLocal.begin() as session:
            daily_insert = _insert(session, DailyBar).values(
                daily_values
            )
            session.execute(
                daily_insert.on_conflict_do_update(
                    index_elements=["code", "trade_date"],
                    set_={
                        key: getattr(daily_insert.excluded, key)
                        for key in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            "amount",
                            "source",
                            "fetched_at",
                        )
                    },
                )
            )
            factor_insert = _insert(session, AdjustFactor).values(
                adjust_values
            )
            session.execute(
                factor_insert.on_conflict_do_update(
                    index_elements=["code", "ex_date"],
                    set_={
                        key: getattr(factor_insert.excluded, key)
                        for key in (
                            "adjust_factor",
                            "fore_adjust_factor",
                            "back_adjust_factor",
                            "source",
                            "fetched_at",
                        )
                    },
                )
            )
            persisted_daily = [
                {
                    "code": row.code,
                    "trade_date": row.trade_date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                    "amount": row.amount,
                    "source": row.source,
                }
                for row in session.execute(
                    select(DailyBar).where(
                        DailyBar.trade_date == day,
                        DailyBar.source == "tushare",
                        DailyBar.code != "000300.SH",
                    )
                ).scalars()
            ]
            persisted_factors = [
                {
                    "code": row.code,
                    "ex_date": row.ex_date,
                    "adjust_factor": row.adjust_factor,
                    "fore_adjust_factor": row.fore_adjust_factor,
                    "back_adjust_factor": row.back_adjust_factor,
                    "source": row.source,
                }
                for row in session.execute(
                    select(AdjustFactor).where(
                        AdjustFactor.ex_date == day,
                        AdjustFactor.source == "tushare",
                    )
                ).scalars()
            ]
            daily_hash = _content_sha256(persisted_daily)
            factor_hash = _content_sha256(persisted_factors)
            if (
                len(persisted_daily) != len(daily_values)
                or len(persisted_factors) != len(adjust_values)
                or daily_hash != _content_sha256(daily_values)
                or factor_hash != _content_sha256(adjust_values)
            ):
                raise RuntimeError(
                    f"{day} persisted content differs from response"
                )
            session.add(
                TushareBootstrapDailyManifest(
                    trade_date=day,
                    daily_count=len(daily_values),
                    factor_count=len(adjust_values),
                    daily_sha256=daily_hash,
                    factor_sha256=factor_hash,
                    fetched_at=fetched_at,
                )
            )
        print(
            f"[{index}/{len(pending)}] {day}: "
            f"daily={len(daily_values)} adjust={len(adjust_values)}",
            flush=True,
        )
        time.sleep(0.15)


def bootstrap_benchmark(
    client: httpx.Client, start: date, end: date
) -> None:
    rows = _request(
        client,
        "index_daily",
        {
            "ts_code": "000300.SH",
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
        },
        DAILY_FIELDS,
    )
    fetched_at = datetime.now(UTC)
    bars = _daily_values(rows, fetched_at)
    factors = [
        {
            "code": "000300.SH",
            "ex_date": row["trade_date"],
            "adjust_factor": Decimal("1"),
            "fore_adjust_factor": Decimal("1"),
            "back_adjust_factor": Decimal("1"),
            "source": "derived_identity",
            "fetched_at": fetched_at,
        }
        for row in bars
    ]
    with SessionLocal.begin() as session:
        session.execute(
            _insert(session, DailyBar)
            .values(bars)
            .on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    key: getattr(
                        _insert(session, DailyBar).excluded, key
                    )
                    for key in (
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "source",
                        "fetched_at",
                    )
                },
            )
        )
        session.execute(
            _insert(session, AdjustFactor)
            .values(factors)
            .on_conflict_do_update(
                index_elements=["code", "ex_date"],
                set_={
                    "adjust_factor": Decimal("1"),
                    "fore_adjust_factor": Decimal("1"),
                    "back_adjust_factor": Decimal("1"),
                    "source": "derived_identity",
                    "fetched_at": fetched_at,
                },
            )
        )
    print(f"CSI300: {len(bars)} sessions", flush=True)


def bootstrap_status(
    client: httpx.Client, start: date, end: date
) -> None:
    raw_rows = []
    offset = 0
    while True:
        page = _request(
            client,
            "namechange",
            {"offset": offset, "limit": 10_000},
            STATUS_FIELDS,
        )
        raw_rows.extend(page)
        if len(page) < 10_000:
            break
        offset += len(page)
    suspension_rows = []
    offset = 0
    while True:
        page = _request(
            client,
            "suspend_d",
            {
                "start_date": start.strftime("%Y%m%d"),
                "end_date": end.strftime("%Y%m%d"),
                "offset": offset,
                "limit": 5_000,
            },
            SUSPEND_FIELDS,
        )
        suspension_rows.extend(page)
        if len(page) < 5_000:
            break
        offset += len(page)
    by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        code = _canonical(row.get("ts_code"))
        if code:
            by_code[code].append(row)
    with SessionLocal() as session:
        instruments = session.execute(
            select(Instrument).where(
                Instrument.security_type == "stock"
            )
        ).scalars().all()
    fetched_at = datetime.now(UTC)
    instrument_codes = {instrument.code for instrument in instruments}
    values = []
    for instrument in instruments:
        source_rows = []
        for row in by_code.get(instrument.code, []):
            start_date = parse_date(row.get("start_date"))
            end_date = parse_date(row.get("end_date"))
            if (
                start_date is None
                or (end_date is not None and end_date < start_date)
            ):
                continue
            source_rows.append((start_date, end_date, row))
        source_rows.sort(key=lambda item: item[0])
        if not source_rows and instrument.list_date:
            values.append(
                {
                    "code": instrument.code,
                    "start_date": instrument.list_date,
                    "end_date": instrument.delist_date,
                    "name": instrument.name,
                    "status_type": "normal",
                    "change_reason": "no_namechange_rows",
                    "announced_date": None,
                    "source": "tushare",
                    "fetched_at": fetched_at,
                }
            )
            continue
        cursor = instrument.list_date
        for index, (start_date, raw_end, row) in enumerate(source_rows):
            if cursor is not None and cursor < start_date:
                values.append(
                    {
                        "code": instrument.code,
                        "start_date": cursor,
                        "end_date": start_date - timedelta(days=1),
                        "name": instrument.name,
                        "status_type": "normal",
                        "change_reason": "namechange_coverage_gap",
                        "announced_date": None,
                        "source": "tushare",
                        "fetched_at": fetched_at,
                    }
                )
            next_start = (
                source_rows[index + 1][0]
                if index + 1 < len(source_rows)
                else None
            )
            end_date = raw_end
            if next_start is not None and (
                end_date is None or end_date >= next_start
            ):
                end_date = next_start - timedelta(days=1)
            values.append(
                {
                    "code": instrument.code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "name": str(row.get("name") or ""),
                    "status_type": _status_type(
                        str(row.get("name") or "")
                    ),
                    "change_reason": str(
                        row.get("change_reason") or ""
                    )[:128],
                    "announced_date": parse_date(row.get("ann_date")),
                    "source": "tushare",
                    "fetched_at": fetched_at,
                }
            )
            cursor = (
                end_date + timedelta(days=1)
                if end_date is not None
                else None
            )
        if cursor is not None and (
            instrument.delist_date is None
            or cursor <= instrument.delist_date
        ):
            values.append(
                {
                    "code": instrument.code,
                    "start_date": cursor,
                    "end_date": instrument.delist_date,
                    "name": instrument.name,
                    "status_type": "normal",
                    "change_reason": "post_namechange_normal",
                    "announced_date": None,
                    "source": "tushare",
                    "fetched_at": fetched_at,
                }
            )
    suspension_values = []
    for row in suspension_rows:
        code = _canonical(row.get("ts_code"))
        suspend_date = parse_date(row.get("trade_date"))
        if (
            code is None
            or code not in instrument_codes
            or suspend_date is None
            or row.get("suspend_type") != "S"
        ):
            continue
        suspension_values.append(
            {
                "code": code,
                "trade_date": suspend_date,
                "reason": str(
                    row.get("suspend_timing") or "tushare_suspend_d"
                )[:128],
                "announced_date": None,
                "source": "tushare",
                "fetched_at": fetched_at,
            }
        )
    suspension_values = list(
        {
            (value["code"], value["trade_date"]): value
            for value in suspension_values
        }.values()
    )
    values = list(
        {
            (value["code"], value["start_date"]): value
            for value in values
        }.values()
    )
    with SessionLocal.begin() as session:
        session.query(InstrumentStatusHistory).filter(
            InstrumentStatusHistory.source == "tushare"
        ).delete(synchronize_session=False)
        for start_index in range(0, len(values), 5_000):
            batch = values[start_index : start_index + 5_000]
            session.execute(
                _insert(session, InstrumentStatusHistory)
                .values(batch)
                .on_conflict_do_update(
                    index_elements=["code", "start_date"],
                    set_={
                        key: getattr(
                            _insert(
                                session, InstrumentStatusHistory
                            ).excluded,
                            key,
                        )
                        for key in (
                            "end_date",
                            "name",
                            "status_type",
                            "change_reason",
                            "announced_date",
                            "source",
                            "fetched_at",
                        )
                    },
                )
            )
        session.query(InstrumentSuspensionDaily).filter(
            InstrumentSuspensionDaily.source == "tushare",
            InstrumentSuspensionDaily.trade_date >= start,
            InstrumentSuspensionDaily.trade_date <= end,
        ).delete(synchronize_session=False)
        for start_index in range(
            0, len(suspension_values), 5_000
        ):
            session.execute(
                _insert(session, InstrumentSuspensionDaily)
                .values(
                    suspension_values[
                        start_index : start_index + 5_000
                    ]
                )
                .on_conflict_do_update(
                    index_elements=["code", "trade_date"],
                    set_={
                        key: getattr(
                            _insert(
                                session, InstrumentSuspensionDaily
                            ).excluded,
                            key,
                        )
                        for key in (
                            "reason",
                            "announced_date",
                            "source",
                            "fetched_at",
                        )
                    },
                )
            )
    print(
        f"status: names={len(raw_rows)} "
        f"suspensions={len(suspension_values)} "
        f"persisted={len(values)}",
        flush=True,
    )


def bootstrap_audits(
    codes: list[str], start: date, end: date
) -> None:
    with SessionLocal() as session:
        expected_dates = set(
            session.execute(
                select(DailyBar.trade_date).where(
                    DailyBar.code == "000300.SH",
                    DailyBar.trade_date >= start,
                    DailyBar.trade_date <= end,
                )
            ).scalars()
        )
    if not expected_dates:
        raise RuntimeError("benchmark sessions missing for audit")
    for code in codes:
        with SessionLocal() as session:
            daily_records = session.execute(
                select(
                    DailyBar.trade_date,
                    DailyBar.source,
                ).where(
                    DailyBar.code == code,
                    DailyBar.trade_date >= start,
                    DailyBar.trade_date <= end,
                )
            ).all()
            adjust_records = session.execute(
                select(
                    AdjustFactor.ex_date,
                    AdjustFactor.source,
                ).where(
                    AdjustFactor.code == code,
                    AdjustFactor.ex_date >= start,
                    AdjustFactor.ex_date <= end,
                )
            ).all()
            missing_dates = expected_dates - {
                row.trade_date for row in daily_records
            }
            suspended_missing = (
                session.scalar(
                    select(func.count())
                    .select_from(InstrumentSuspensionDaily)
                    .where(
                        InstrumentSuspensionDaily.code == code,
                        InstrumentSuspensionDaily.trade_date.in_(
                            missing_dates
                        ),
                        InstrumentSuspensionDaily.source == "tushare",
                    )
                )
                if missing_dates and code != "000300.SH"
                else 0
            )
        daily_dates = {row.trade_date for row in daily_records}
        adjust_dates = {row.ex_date for row in adjust_records}
        expected_daily_source = "tushare"
        expected_adjust_source = (
            "derived_identity"
            if code == "000300.SH"
            else "tushare"
        )
        if (
            not daily_records
            or adjust_dates != expected_dates
            or suspended_missing != len(missing_dates)
            or any(
                row.source != expected_daily_source
                for row in daily_records
            )
            or any(
                row.source != expected_adjust_source
                for row in adjust_records
            )
        ):
            raise RuntimeError(
                f"{code} audit coverage missing: "
                f"daily={len(daily_dates)}/{len(expected_dates)} "
                f"adjust={len(adjust_dates)}/{len(expected_dates)} "
                f"suspensionEvidence={suspended_missing}/"
                f"{len(missing_dates)}"
            )
        temporary_id = "00000000-0000-0000-0000-000000000000"
        daily = ingest._completed_dataset_audit(
            temporary_id,
            code,
            "daily",
            len(daily_records),
            start.isoformat(),
            end.isoformat(),
            "1d",
        )
        adjust = ingest._completed_dataset_audit(
            temporary_id,
            code,
            "adjust",
            len(adjust_records),
            start.isoformat(),
            end.isoformat(),
            "adjust",
        )
        watermark_digest = hashlib.sha256(
            (
                f"{daily['fetchedAtFloor']}:{daily['fetchedAtWatermark']}:"
                f"{adjust['fetchedAtFloor']}:{adjust['fetchedAtWatermark']}"
            ).encode()
        ).hexdigest()
        run_id = str(
            uuid5(
                NAMESPACE_URL,
                f"tushare-bulk:{code}:{start}:{end}:{watermark_digest}",
            )
        )
        daily["runId"] = run_id
        adjust["runId"] = run_id
        floors = [
            datetime.fromisoformat(value)
            for value in (
                daily["fetchedAtFloor"],
                adjust["fetchedAtFloor"],
            )
            if isinstance(value, str)
        ]
        now = datetime.now(UTC)
        started_at = min(floors)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        datasets = {
            "daily": {
                **ingest._dataset_audit_template(
                    run_id,
                    "1d",
                    start.isoformat(),
                    end.isoformat(),
                ),
                **daily,
                "sourceOperation": (
                    "tushare_index_daily"
                    if code == "000300.SH"
                    else "tushare_trade_date_bulk"
                ),
            },
            "adjust": {
                **ingest._dataset_audit_template(
                    run_id,
                    "adjust",
                    start.isoformat(),
                    end.isoformat(),
                ),
                **adjust,
                "sourceOperation": (
                    "derived_index_identity"
                    if code == "000300.SH"
                    else "tushare_trade_date_bulk"
                ),
            },
        }
        with SessionLocal.begin() as session:
            session.query(IngestionRun).filter(
                IngestionRun.code == code,
                IngestionRun.start_date == start,
                IngestionRun.end_date == end,
                IngestionRun.datasets_json.contains(
                    "tushare_"
                ),
            ).delete(synchronize_session=False)
            session.add(
                IngestionRun(
                    id=run_id,
                    code=code,
                    start_date=start,
                    end_date=end,
                    status="ready",
                    datasets_json=json.dumps(
                        datasets, ensure_ascii=False
                    ),
                    error_json="{}",
                    started_at=started_at,
                    completed_at=now,
                )
            )
        print(
            f"audit: {code} daily={len(daily_records)} "
            f"adjust={len(adjust_records)}",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument(
        "--phase",
        choices=["market", "benchmark", "status", "audit", "all"],
        default="all",
    )
    parser.add_argument("--max-dates", type=int)
    parser.add_argument("--audit-codes", default="")
    args = parser.parse_args()
    if not settings.tushare_token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise ValueError("end 早于 start")
    with httpx.Client(timeout=60) as client:
        if args.phase in {"market", "all"}:
            bootstrap_market(
                client, start, end, max_dates=args.max_dates
            )
        if args.phase in {"benchmark", "all"}:
            bootstrap_benchmark(client, start, end)
        if args.phase in {"status", "all"}:
            bootstrap_status(client, start, end)
        if args.phase in {"audit", "all"}:
            codes = [
                value.strip().upper()
                for value in args.audit_codes.split(",")
                if value.strip()
            ]
            if not codes:
                raise ValueError("audit phase requires --audit-codes")
            bootstrap_audits(codes, start, end)


if __name__ == "__main__":
    main()
