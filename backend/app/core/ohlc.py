"""Shared validation for persisted and provider OHLC bars."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_UNSAFE_CONTEXT = re.compile(r"[^A-Za-z0-9._:-]")


class InvalidOHLCError(ValueError):
    """Audit-safe bar validation error containing only context and a reason code."""

    def __init__(
        self,
        *,
        code: object,
        bar_time: object,
        reason: str,
    ) -> None:
        safe_code = _safe_code(code)
        safe_time = _safe_time(bar_time)
        self.code = safe_code
        self.bar_time = safe_time
        self.reason = reason
        super().__init__(
            f"invalid_ohlc code={safe_code} time={safe_time} reason={reason}"
        )


@dataclass(frozen=True)
class ValidatedOHLC:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    amount: Decimal | None


def _safe_code(value: object) -> str:
    text = str(value or "unknown")[:32]
    return _UNSAFE_CONTEXT.sub("_", text) or "unknown"


def _safe_time(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return "unknown"


def _number(
    value: object,
    *,
    field: str,
    code: object,
    bar_time: object,
    required: bool,
    positive: bool,
) -> Decimal | None:
    if value is None:
        if required:
            raise InvalidOHLCError(
                code=code,
                bar_time=bar_time,
                reason=f"missing_{field}",
            )
        return None
    if isinstance(value, bool):
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason=f"boolean_{field}",
        )
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason=f"non_numeric_{field}",
        ) from None
    if not number.is_finite():
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason=f"non_finite_{field}",
        )
    if positive and number <= 0:
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason=f"non_positive_{field}",
        )
    if not positive and number < 0:
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason=f"negative_{field}",
        )
    return number


def validate_ohlc(
    *,
    open_value: object,
    high_value: object,
    low_value: object,
    close_value: object,
    volume: object = None,
    amount: object = None,
    code: object,
    bar_time: object,
) -> ValidatedOHLC:
    """Validate and normalize one bar without echoing raw provider values."""
    open_number = _number(
        open_value,
        field="open",
        code=code,
        bar_time=bar_time,
        required=True,
        positive=True,
    )
    high_number = _number(
        high_value,
        field="high",
        code=code,
        bar_time=bar_time,
        required=True,
        positive=True,
    )
    low_number = _number(
        low_value,
        field="low",
        code=code,
        bar_time=bar_time,
        required=True,
        positive=True,
    )
    close_number = _number(
        close_value,
        field="close",
        code=code,
        bar_time=bar_time,
        required=True,
        positive=True,
    )
    assert (
        open_number is not None
        and high_number is not None
        and low_number is not None
        and close_number is not None
    )
    if not (
        low_number
        <= min(open_number, close_number)
        <= max(open_number, close_number)
        <= high_number
    ):
        raise InvalidOHLCError(
            code=code,
            bar_time=bar_time,
            reason="invalid_ohlc_order",
        )
    volume_number = _number(
        volume,
        field="volume",
        code=code,
        bar_time=bar_time,
        required=False,
        positive=False,
    )
    amount_number = _number(
        amount,
        field="amount",
        code=code,
        bar_time=bar_time,
        required=False,
        positive=False,
    )
    return ValidatedOHLC(
        open=open_number,
        high=high_number,
        low=low_number,
        close=close_number,
        volume=volume_number,
        amount=amount_number,
    )


def validate_previous_close(
    value: object,
    *,
    code: object,
    bar_time: object,
) -> Decimal:
    """Validate a minute backtest's prior-session close seed."""
    number = _number(
        value,
        field="previous_close",
        code=code,
        bar_time=bar_time,
        required=True,
        positive=True,
    )
    assert number is not None
    return number
