"""Ingestion: pull from a provider and upsert into Postgres.

Upserts use PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` so re-runs are
idempotent. Realtime quotes are not persisted here (transient); ``fetch_quotes``
just returns them for connectivity checks / API serving.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dt_time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import partial
from threading import Lock, RLock
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.numeric import to_decimal, to_int
from app.core.ohlc import validate_ohlc
from app.db.session import SessionLocal
from app.models.extra import CapitalFlow, DragonTiger, FinancialSummary, NewsItem
from app.models.ingestion import IngestionRun
from app.models.market import AdjustFactor, DailyBar, Instrument, MinuteBar
from app.providers.base import FinancialSummaryDTO, QuoteDTO
from app.providers.registry import get_provider, get_provider_for

logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_FINANCIAL_METRICS = (
    "eps",
    "bps",
    "roe",
    "revenue",
    "net_profit",
    "gross_margin",
)
_FINANCIAL_NUMERIC_SPECS = {
    field: (
        int(FinancialSummary.__table__.c[field].type.precision),
        int(FinancialSummary.__table__.c[field].type.scale),
    )
    for field in _FINANCIAL_METRICS
}
_AUTH_SCHEME_RE = re.compile(r"(?i)\b(Basic|Bearer)\s+[^\s,'\"}\]]+")
_SECRET_KEYS = (
    r"x[-_]?api[-_]?key|api[-_]?key|access[-_]?token|authorization|"
    r"password|passwd|secret|token"
)
_QUOTED_SECRET_FIELD_RE = re.compile(
    rf"(?i)([\"']?(?:{_SECRET_KEYS})[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)"
)
_SECRET_FIELD_RE = re.compile(
    rf"(?i)\b({_SECRET_KEYS})\b(\s*[:=]\s*)(?![\"'])([^\s&;,}}\]]+)"
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+(@)")
_PROCESS_CODE_LOCKS: dict[str, RLock] = {}
_PROCESS_CODE_LOCKS_GUARD = Lock()


class EmptyDatasetError(RuntimeError):
    """A required OHLC request returned no rows."""


@dataclass(frozen=True)
class _ActiveIngestionRun:
    id: str
    code: str


_ACTIVE_INGESTION_RUN: ContextVar[_ActiveIngestionRun | None] = ContextVar(
    "active_ingestion_run",
    default=None,
)


def _now():
    return datetime.now(UTC)


def _resolve(provider_name: str | None, capability: str):
    return get_provider(provider_name) if provider_name else get_provider_for(capability)


def _utc_datetime(value: datetime) -> datetime:
    """Treat source-naive financial timestamps as Asia/Shanghai, then store UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=_SHANGHAI)
    return value.astimezone(UTC)


def _financial_vintage(metrics: dict[str, object]) -> str:
    """Hash canonical decimal values so equivalent source formatting is stable."""

    def canonical(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            raise TypeError("financial vintage values must be Decimal or None")
        return format(value.normalize(), "f")

    payload = {
        field: canonical(metrics.get(field))
        for field in _FINANCIAL_METRICS
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalize_financial_metrics(
    item: FinancialSummaryDTO,
) -> dict[str, Decimal | None]:
    """Quantize to ORM column scales without a binary-float round trip."""
    normalized: dict[str, Decimal | None] = {}
    for field, (precision, scale) in _FINANCIAL_NUMERIC_SPECS.items():
        value = getattr(item, field)
        if value is None:
            normalized[field] = None
            continue
        if not isinstance(value, Decimal):
            raise TypeError(f"{field} must be Decimal")
        if not value.is_finite():
            raise ValueError(f"{field} must be finite")
        quantum = Decimal(1).scaleb(-scale)
        try:
            quantized = value.quantize(quantum, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError(f"{field} exceeds supported precision") from exc
        integer_limit = Decimal(10) ** (precision - scale)
        if abs(quantized) >= integer_limit:
            raise ValueError(
                f"{field} exceeds Numeric({precision}, {scale}) precision"
            )
        normalized[field] = abs(quantized) if quantized == 0 else quantized
    return normalized


def _financial_availability(
    item: FinancialSummaryDTO,
    fetched_at: datetime,
) -> tuple[datetime | None, datetime]:
    if item.announced_at is None:
        provider_available = (
            _utc_datetime(item.available_at)
            if item.available_at is not None
            else None
        )
        return None, provider_available or fetched_at

    announced_at = _utc_datetime(item.announced_at)
    if item.announced_at_precision == "date":
        source_date = (
            item.announced_at.astimezone(_SHANGHAI).date()
            if item.announced_at.tzinfo is not None
            else item.announced_at.date()
        )
        conservative_close = datetime.combine(
            source_date,
            dt_time(15, 0),
            tzinfo=_SHANGHAI,
        ).astimezone(UTC)
        return announced_at, conservative_close
    return announced_at, announced_at


def _sanitize_error(exc: Exception) -> str:
    """Return a bounded audit-safe exception summary without credentials."""
    text = str(exc).replace("\r", " ").replace("\n", " ").strip() or type(exc).__name__
    text = _AUTH_SCHEME_RE.sub(r"\1 [REDACTED]", text)
    text = _QUOTED_SECRET_FIELD_RE.sub(r"\1\2[REDACTED]\2", text)
    text = _SECRET_FIELD_RE.sub(r"\1\2[REDACTED]", text)
    text = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", text)
    return f"{type(exc).__name__}: {text}"[:512]


def _process_code_lock(code: str) -> RLock:
    with _PROCESS_CODE_LOCKS_GUARD:
        return _PROCESS_CODE_LOCKS.setdefault(code, RLock())


def _advisory_lock_key(code: str) -> int:
    digest = hashlib.blake2b(f"ingestion:{code}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@contextmanager
def _code_backfill_lock(code: str):
    """Serialize one symbol in-process and across PostgreSQL workers."""
    with _process_code_lock(code):
        with SessionLocal() as lock_session:
            is_postgresql = lock_session.get_bind().dialect.name == "postgresql"
            key = _advisory_lock_key(code)
            if is_postgresql:
                lock_session.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
            try:
                yield
            finally:
                if is_postgresql:
                    lock_session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


def _dataset_audit_template(
    run_id: str,
    period: str | None,
    requested_start: str | None,
    requested_end: str | None,
) -> dict[str, object]:
    audit = {
        "success": None,
        "rows": 0,
        "error": None,
        "period": period,
        "requested": {"start": requested_start, "end": requested_end},
        "actual": {"start": None, "end": None},
        "runId": run_id,
        "fetchedAtFloor": None,
        "fetchedAtWatermark": None,
    }
    if period and period.endswith("m"):
        audit["previousClose"] = None
    return audit


def _create_ingestion_run(
    run_id: str,
    code: str,
    start: str,
    end: str,
    datasets: dict[str, dict[str, object]],
) -> None:
    with SessionLocal() as session:
        session.add(
            IngestionRun(
                id=run_id,
                code=code,
                start_date=date.fromisoformat(start[:10]),
                end_date=date.fromisoformat(end[:10]),
                status="running",
                datasets_json=json.dumps(datasets, ensure_ascii=False),
                error_json="{}",
                started_at=_now(),
            )
        )
        session.commit()


def _finalize_ingestion_run(
    run_id: str,
    status: str,
    datasets: dict[str, dict[str, object]],
    errors: dict[str, str],
) -> None:
    with SessionLocal() as session:
        run = session.get(IngestionRun, run_id)
        if run is None:
            raise RuntimeError(f"回填运行记录丢失: {run_id}")
        run.status = status
        run.datasets_json = json.dumps(datasets, ensure_ascii=False)
        run.error_json = json.dumps(errors, ensure_ascii=False)
        run.completed_at = _now()
        session.commit()


def _completed_dataset_audit(
    run_id: str,
    code: str,
    dataset: str,
    rows: int,
    requested_start: str | None,
    requested_end: str | None,
    period: str | None,
) -> dict[str, object]:
    if rows == 0 and (dataset == "daily" or dataset.startswith("minute:")):
        raise EmptyDatasetError(f"{dataset} 请求返回 0 行")
    persistence = (
        _dataset_actual_range(
            code,
            dataset,
            requested_start,
            requested_end,
            period,
        )
        if rows > 0 or dataset == "adjust"
        else {
            "start": None,
            "end": None,
            "fetchedAtFloor": None,
            "fetchedAtWatermark": None,
        }
    )
    if rows > 0 and (
        dataset == "daily" or dataset == "adjust" or dataset.startswith("minute:")
    ):
        required_audit_values = (
            persistence.get("start"),
            persistence.get("end"),
            persistence.get("fetchedAtFloor"),
            persistence.get("fetchedAtWatermark"),
        )
        if not all(required_audit_values):
            raise RuntimeError(f"{dataset} 已写入但无法建立 fetched_at 审计水位")
    return {
        "success": True,
        "rows": rows,
        "error": None,
        "actual": {
            "start": persistence.get("start"),
            "end": persistence.get("end"),
        },
        "runId": run_id,
        "fetchedAtFloor": persistence.get("fetchedAtFloor"),
        "fetchedAtWatermark": persistence.get("fetchedAtWatermark"),
        **(
            {"previousClose": persistence.get("previousClose")}
            if dataset.startswith("minute:")
            else {}
        ),
    }


def _standalone_dataset_write(
    code: str,
    dataset: str,
    period: str,
    start: str,
    end: str,
    writer,
) -> int:
    active = _ACTIVE_INGESTION_RUN.get()
    if active is not None:
        if active.code != code:
            raise RuntimeError(
                f"活动回填 run {active.id} 属于 {active.code}，不能写入 {code}"
            )
        return int(writer())

    with _code_backfill_lock(code):
        run_id = uuid4().hex
        datasets = {
            dataset: _dataset_audit_template(run_id, period, start, end)
        }
        _create_ingestion_run(run_id, code, start, end, datasets)
        token = _ACTIVE_INGESTION_RUN.set(_ActiveIngestionRun(run_id, code))
        try:
            try:
                rows = int(writer())
                datasets[dataset].update(
                    _completed_dataset_audit(
                        run_id,
                        code,
                        dataset,
                        rows,
                        start,
                        end,
                        period,
                    )
                )
            except Exception as exc:
                summary = _sanitize_error(exc)
                datasets[dataset].update(
                    {"success": False, "rows": 0, "error": summary}
                )
                _finalize_ingestion_run(
                    run_id,
                    "failed",
                    datasets,
                    {dataset: summary},
                )
                raise
            _finalize_ingestion_run(run_id, "ready", datasets, {})
            return rows
        finally:
            _ACTIVE_INGESTION_RUN.reset(token)


def _validate_adjust_factors(factors: list) -> None:
    """Validate only adjustment coverage primitives, not general OHLC data."""
    for factor in factors:
        if not isinstance(getattr(factor, "ex_date", None), date):
            raise ValueError("复权因子日期无效")
        values = [
            getattr(factor, "adjust_factor", None),
            getattr(factor, "fore_adjust_factor", None),
            getattr(factor, "back_adjust_factor", None),
        ]
        present = [value for value in values if value is not None]
        if not present:
            raise ValueError("复权因子记录不含有效因子")
        for value in present:
            if isinstance(value, bool):
                raise ValueError("复权因子必须为有限正数")
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("复权因子必须为有限正数") from exc
            if not math.isfinite(numeric) or numeric <= 0:
                raise ValueError("复权因子必须为有限正数")


def _validated_bar_fields(bar: object, code: str) -> dict[str, object]:
    """Validate provider values before converting them to storage precision."""
    bar_time = getattr(bar, "dt", None)
    checked = validate_ohlc(
        open_value=getattr(bar, "open", None),
        high_value=getattr(bar, "high", None),
        low_value=getattr(bar, "low", None),
        close_value=getattr(bar, "close", None),
        volume=getattr(bar, "volume", None),
        amount=getattr(bar, "amount", None),
        code=code,
        bar_time=bar_time,
    )
    converted = {
        "open": to_decimal(float(checked.open)),
        "high": to_decimal(float(checked.high)),
        "low": to_decimal(float(checked.low)),
        "close": to_decimal(float(checked.close)),
        "volume": (
            to_int(float(checked.volume)) if checked.volume is not None else None
        ),
        "amount": (
            to_decimal(float(checked.amount)) if checked.amount is not None else None
        ),
    }
    # Numeric(18, 4) conversion can round a tiny positive price to zero or
    # collapse a valid ordering, so validate the exact values we will persist.
    validate_ohlc(
        open_value=converted["open"],
        high_value=converted["high"],
        low_value=converted["low"],
        close_value=converted["close"],
        volume=converted["volume"],
        amount=converted["amount"],
        code=code,
        bar_time=bar_time,
    )
    return converted


def _upsert(
    session: Session,
    model,
    rows: list[dict],
    index_elements: list[str],
    update_cols: list[str],
) -> int:
    if not rows:
        return 0
    # 同一批次内相同冲突键只保留最后一条，避免 ON CONFLICT 二次影响同一行报错。
    deduped: dict[tuple, dict] = {}
    for row in rows:
        deduped[tuple(row[c] for c in index_elements)] = row
    values = list(deduped.values())
    stmt = pg_insert(model).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={c: getattr(stmt.excluded, c) for c in update_cols},
    )
    session.execute(stmt)
    return len(values)


def ingest_instruments(provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "instruments")
    items = provider.get_instruments()
    now = _now()
    rows = [
        {
            "code": i.code,
            "name": i.name,
            "exchange": i.exchange,
            "security_type": i.security_type,
            "list_date": i.list_date,
            "delist_date": i.delist_date,
            "status": i.status,
            "source": provider.name,
            "fetched_at": now,
        }
        for i in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            Instrument,
            rows,
            ["code"],
            ["name", "exchange", "security_type", "list_date", "delist_date", "status", "source", "fetched_at"],
        )
        session.commit()
    return n


def _ingest_daily_raw(
    code: str, start: str, end: str, adjust: str = "none", provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "daily")
    bars = provider.get_daily_bars(code, start, end, adjust=adjust)
    now = _now()
    rows = []
    for bar in bars:
        values = _validated_bar_fields(bar, code)
        rows.append(
            {
                "code": bar.code,
                "trade_date": bar.dt.date(),
                **values,
                "source": provider.name,
                "fetched_at": now,
            }
        )
    with SessionLocal() as session:
        n = _upsert(
            session,
            DailyBar,
            rows,
            ["code", "trade_date"],
            ["open", "high", "low", "close", "volume", "amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def _ingest_minute_raw(
    code: str, period: str, start: str, end: str, provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "minute")
    bars = provider.get_minute_bars(code, period, start, end)
    now = _now()
    rows = []
    for bar in bars:
        values = _validated_bar_fields(bar, code)
        rows.append(
            {
                "code": bar.code,
                "dt": bar.dt,
                "period": bar.period,
                **values,
                "source": provider.name,
                "fetched_at": now,
            }
        )
    with SessionLocal() as session:
        n = _upsert(
            session,
            MinuteBar,
            rows,
            ["code", "dt", "period"],
            ["open", "high", "low", "close", "volume", "amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def _ingest_adjust_raw(
    code: str, start: str, end: str, provider_name: str | None = None
) -> int:
    provider = _resolve(provider_name, "adjust")
    factors = provider.get_adjust_factors(code, start, end)
    _validate_adjust_factors(factors)
    now = _now()
    rows = [
        {
            "code": f.code,
            "ex_date": f.ex_date,
            "adjust_factor": to_decimal(f.adjust_factor, 6),
            "fore_adjust_factor": to_decimal(f.fore_adjust_factor, 6),
            "back_adjust_factor": to_decimal(f.back_adjust_factor, 6),
            "source": provider.name,
            "fetched_at": now,
        }
        for f in factors
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            AdjustFactor,
            rows,
            ["code", "ex_date"],
            ["adjust_factor", "fore_adjust_factor", "back_adjust_factor", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_daily(
    code: str,
    start: str,
    end: str,
    adjust: str = "none",
    provider_name: str | None = None,
) -> int:
    return _standalone_dataset_write(
        code,
        "daily",
        "1d",
        start,
        end,
        partial(_ingest_daily_raw, code, start, end, adjust, provider_name),
    )


def ingest_minute(
    code: str,
    period: str,
    start: str,
    end: str,
    provider_name: str | None = None,
) -> int:
    return _standalone_dataset_write(
        code,
        f"minute:{period}",
        f"{period}m",
        start,
        end,
        partial(_ingest_minute_raw, code, period, start, end, provider_name),
    )


def ingest_adjust(
    code: str,
    start: str,
    end: str,
    provider_name: str | None = None,
) -> int:
    return _standalone_dataset_write(
        code,
        "adjust",
        "adjust",
        start,
        end,
        partial(_ingest_adjust_raw, code, start, end, provider_name),
    )


def fetch_quotes(
    codes: list[str] | None = None, provider_name: str | None = None
) -> list[QuoteDTO]:
    provider = _resolve(provider_name, "realtime")
    return provider.get_realtime_quotes(codes)


def ingest_capital_flow(code: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "capital_flow")
    items = provider.get_capital_flow(code)
    now = _now()
    rows = [
        {
            "code": r.code,
            "trade_date": r.trade_date,
            "main_net": to_decimal(r.main_net),
            "main_net_ratio": to_decimal(r.main_net_ratio),
            "super_large_net": to_decimal(r.super_large_net),
            "large_net": to_decimal(r.large_net),
            "medium_net": to_decimal(r.medium_net),
            "small_net": to_decimal(r.small_net),
            "source": provider.name,
            "fetched_at": now,
        }
        for r in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            CapitalFlow,
            rows,
            ["code", "trade_date"],
            ["main_net", "main_net_ratio", "super_large_net", "large_net", "medium_net", "small_net", "source", "fetched_at"],
        )
        session.commit()
    return n


def ingest_financials(code: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "financials")
    items = provider.get_financials(code)
    fetched_at = _utc_datetime(_now())
    prepared: list[tuple[FinancialSummaryDTO, dict[str, Decimal | None], str, datetime | None, datetime]] = []
    for item in items:
        metrics = _normalize_financial_metrics(item)
        prepared.append(
            (
                item,
                metrics,
                _financial_vintage(metrics),
                *_financial_availability(item, fetched_at),
            )
        )
    with SessionLocal() as session:
        for item, metrics, vintage, announced_at, available_at in prepared:
            values = {
                "id": str(uuid4()),
                "code": item.code,
                "report_date": item.report_date,
                "announced_at": announced_at,
                "available_at": available_at,
                "vintage": vintage,
                **metrics,
                "source": provider.name,
                "fetched_at": fetched_at,
            }
            dialect_name = session.get_bind().dialect.name
            insert = sqlite_insert if dialect_name == "sqlite" else pg_insert
            statement = insert(FinancialSummary).values(**values)
            excluded = statement.excluded
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=["code", "report_date", "vintage"],
                    set_={
                        "announced_at": case(
                            (
                                FinancialSummary.announced_at.is_(None),
                                excluded.announced_at,
                            ),
                            (
                                excluded.announced_at.is_(None),
                                FinancialSummary.announced_at,
                            ),
                            (
                                excluded.announced_at
                                < FinancialSummary.announced_at,
                                excluded.announced_at,
                            ),
                            else_=FinancialSummary.announced_at,
                        ),
                        "available_at": case(
                            (
                                excluded.available_at
                                < FinancialSummary.available_at,
                                excluded.available_at,
                            ),
                            else_=FinancialSummary.available_at,
                        ),
                        "source": excluded.source,
                        "fetched_at": case(
                            (
                                excluded.fetched_at > FinancialSummary.fetched_at,
                                excluded.fetched_at,
                            ),
                            else_=FinancialSummary.fetched_at,
                        ),
                    },
                )
            )
        session.commit()
    return len(items)


def ingest_dragon_tiger(start: str, end: str, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "dragon_tiger")
    items = provider.get_dragon_tiger(start, end)
    now = _now()
    rows = [
        {
            "code": r.code,
            "trade_date": r.trade_date,
            "reason": r.reason or "—",
            "name": r.name,
            "net_buy": to_decimal(r.net_buy),
            "buy_amount": to_decimal(r.buy_amount),
            "sell_amount": to_decimal(r.sell_amount),
            "source": provider.name,
            "fetched_at": now,
        }
        for r in items
    ]
    with SessionLocal() as session:
        n = _upsert(
            session,
            DragonTiger,
            rows,
            ["code", "trade_date", "reason"],
            ["name", "net_buy", "buy_amount", "sell_amount", "source", "fetched_at"],
        )
        session.commit()
    return n


def _dataset_actual_range(
    code: str,
    dataset: str,
    requested_start: str | None,
    requested_end: str | None,
    period: str | None = None,
) -> dict[str, object]:
    """Read the resulting persisted coverage for one audited dataset."""
    if dataset == "daily":
        model, range_column, code_column, fetched_column = (
            DailyBar,
            DailyBar.trade_date,
            DailyBar.code,
            DailyBar.fetched_at,
        )
    elif dataset == "adjust":
        model, range_column, code_column, fetched_column = (
            AdjustFactor,
            AdjustFactor.ex_date,
            AdjustFactor.code,
            AdjustFactor.fetched_at,
        )
    elif dataset == "capital_flow":
        model, range_column, code_column, fetched_column = (
            CapitalFlow,
            CapitalFlow.trade_date,
            CapitalFlow.code,
            CapitalFlow.fetched_at,
        )
    elif dataset == "financials":
        model = FinancialSummary
        range_column, code_column, fetched_column = (
            FinancialSummary.report_date,
            FinancialSummary.code,
            FinancialSummary.fetched_at,
        )
    elif dataset == "news":
        model, range_column, code_column, fetched_column = (
            NewsItem,
            NewsItem.published_at,
            NewsItem.code,
            NewsItem.fetched_at,
        )
    elif dataset.startswith("minute:"):
        model, range_column, code_column, fetched_column = (
            MinuteBar,
            MinuteBar.dt,
            MinuteBar.code,
            MinuteBar.fetched_at,
        )
    else:
        return {
            "start": None,
            "end": None,
            "fetchedAtFloor": None,
            "fetchedAtWatermark": None,
        }

    stmt = (
        select(
            func.min(range_column),
            func.max(range_column),
            func.min(fetched_column),
            func.max(fetched_column),
        )
        .select_from(model)
        .where(code_column == code)
    )
    is_datetime = dataset.startswith("minute:") or dataset == "news"
    if dataset == "adjust" and requested_start and requested_end:
        start_date = date.fromisoformat(requested_start[:10])
        end_date = date.fromisoformat(requested_end[:10])
        latest_prior = (
            select(func.max(AdjustFactor.ex_date))
            .where(
                AdjustFactor.code == code,
                AdjustFactor.ex_date < start_date,
            )
            .scalar_subquery()
        )
        stmt = stmt.where(
            or_(
                AdjustFactor.ex_date.between(start_date, end_date),
                AdjustFactor.ex_date == latest_prior,
            )
        )
    elif requested_start:
        lower = (
            datetime.combine(date.fromisoformat(requested_start[:10]), datetime.min.time())
            if is_datetime
            else date.fromisoformat(requested_start[:10])
        )
        stmt = stmt.where(range_column >= lower)
    if requested_end and dataset != "adjust":
        upper = (
            datetime.combine(date.fromisoformat(requested_end[:10]), datetime.max.time())
            if is_datetime
            else date.fromisoformat(requested_end[:10])
        )
        stmt = stmt.where(range_column <= upper)
    if dataset.startswith("minute:") and period:
        stmt = stmt.where(MinuteBar.period == period.removesuffix("m"))

    previous_close = None
    with SessionLocal() as session:
        actual_start, actual_end, fetched_floor, fetched_watermark = session.execute(stmt).one()
        if dataset.startswith("minute:") and actual_start is not None:
            previous_rows = session.execute(
                select(DailyBar)
                .where(
                    DailyBar.code == code,
                    DailyBar.trade_date < actual_start.date(),
                    DailyBar.close.is_not(None),
                    DailyBar.close > 0,
                )
                .order_by(DailyBar.trade_date.desc())
            ).scalars()
            for row in previous_rows:
                close = float(row.close)
                if not math.isfinite(close) or close <= 0:
                    continue
                previous_close = {
                    "tradeDate": row.trade_date.isoformat(),
                    "fetchedAt": (
                        row.fetched_at.isoformat()
                        if row.fetched_at is not None
                        else None
                    ),
                    "value": close,
                }
                break
    result = {
        "start": actual_start.isoformat() if actual_start is not None else None,
        "end": actual_end.isoformat() if actual_end is not None else None,
        "fetchedAtFloor": fetched_floor.isoformat() if fetched_floor is not None else None,
        "fetchedAtWatermark": (
            fetched_watermark.isoformat() if fetched_watermark is not None else None
        ),
    }
    if dataset.startswith("minute:"):
        result["previousClose"] = previous_close
    return result


def watchlist_codes() -> list[str]:
    """所有自选股去重代码（批量回填的默认目标）。"""
    from sqlalchemy import distinct, select

    from app.models.watchlist import WatchlistItem

    with SessionLocal() as session:
        return [c for (c,) in session.execute(select(distinct(WatchlistItem.code))).all() if c]


def backfill_codes(
    codes: list[str],
    start: str,
    end: str,
    provider_name: str | None = None,
    minute_periods: list[str] | None = None,
    minute_start: str | None = None,
) -> dict[str, object]:
    """批量回填一组标的的 日K + 复权因子 + 资金流 + 财务 + 新闻（+ 可选分钟K）。

    逐标的、逐类目独立 try，单点失败不影响其余（免费源易限流/缺数据）；返回各类目落库计数。

    ``minute_periods``：如 ``["5","30"]`` 时额外回填对应分钟周期；缺省不回填（分钟数据量大、
    免费源易限流）。分钟起始日用 ``minute_start``（缺省复用 ``start``，建议传更短窗口）。
    """
    runs: list[dict[str, object]] = []
    stats: dict[str, object] = {
        "daily": 0, "adjust": 0, "capital_flow": 0,
        "financials": 0, "news": 0, "minute": 0, "errors": 0,
        "runs": runs,
    }
    m_start = minute_start or start
    for code in codes:
        with _code_backfill_lock(code):
            tasks: list[
                tuple[str, str, str | None, str | None, str | None, partial]
            ] = [
                (
                    "daily",
                    "daily",
                    "1d",
                    start,
                    end,
                    partial(ingest_daily, code, start, end, "none", provider_name),
                ),
                (
                    "adjust",
                    "adjust",
                    "adjust",
                    start,
                    end,
                    partial(ingest_adjust, code, start, end, provider_name),
                ),
                (
                    "capital_flow",
                    "capital_flow",
                    None,
                    None,
                    None,
                    partial(ingest_capital_flow, code, provider_name),
                ),
                (
                    "financials",
                    "financials",
                    None,
                    None,
                    None,
                    partial(ingest_financials, code, provider_name),
                ),
                (
                    "news",
                    "news",
                    None,
                    None,
                    None,
                    partial(ingest_news, code, 30, provider_name),
                ),
            ]
            for period in minute_periods or []:
                tasks.append(
                    (
                        f"minute:{period}",
                        "minute",
                        f"{period}m",
                        m_start,
                        end,
                        partial(ingest_minute, code, period, m_start, end, provider_name),
                    )
                )

            run_id = uuid4().hex
            datasets: dict[str, dict[str, object]] = {
                dataset: _dataset_audit_template(
                    run_id,
                    period,
                    requested_start,
                    requested_end,
                )
                for dataset, _, period, requested_start, requested_end, _ in tasks
            }
            _create_ingestion_run(run_id, code, start, end, datasets)

            errors: dict[str, str] = {}
            token = _ACTIVE_INGESTION_RUN.set(_ActiveIngestionRun(run_id, code))
            try:
                for dataset, stat_key, period, requested_start, requested_end, fn in tasks:
                    try:
                        rows = int(fn())
                        stats[stat_key] = int(stats[stat_key]) + rows
                        datasets[dataset].update(
                            _completed_dataset_audit(
                                run_id,
                                code,
                                dataset,
                                rows,
                                requested_start,
                                requested_end,
                                period,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001  (单源失败降级，继续其余)
                        summary = _sanitize_error(exc)
                        stats["errors"] = int(stats["errors"]) + 1
                        datasets[dataset].update(
                            {"success": False, "rows": 0, "error": summary}
                        )
                        errors[dataset] = summary
                        logger.warning("回填 %s/%s 失败: %s", code, dataset, summary)
            finally:
                _ACTIVE_INGESTION_RUN.reset(token)

            successes = sum(item["success"] is True for item in datasets.values())
            if not errors:
                status = "ready"
            elif successes:
                status = "partial"
            else:
                status = "failed"
            _finalize_ingestion_run(run_id, status, datasets, errors)
            runs.append(
                {
                    "id": run_id,
                    "code": code,
                    "status": status,
                    "failedDatasets": list(errors),
                }
            )
    return stats


def ingest_news(code: str, limit: int = 30, provider_name: str | None = None) -> int:
    provider = _resolve(provider_name, "news")
    items = provider.get_news(code, limit)
    now = _now()
    rows = []
    for r in items:
        key = (r.url or r.title or "").encode("utf-8")
        if not key:
            continue
        rows.append(
            {
                "id": hashlib.sha1(key).hexdigest(),
                "code": r.code,
                "title": r.title,
                "url": r.url,
                "source_name": r.source_name,
                "published_at": r.published_at,
                "summary": r.summary,
                "source": provider.name,
                "fetched_at": now,
            }
        )
    with SessionLocal() as session:
        n = _upsert(
            session,
            NewsItem,
            rows,
            ["id"],
            ["code", "title", "url", "source_name", "published_at", "summary", "source", "fetched_at"],
        )
        session.commit()
    return n
