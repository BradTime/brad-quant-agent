"""Tushare provider for compact, effective-dated A-share status history.

The ``namechange`` endpoint is queried once per symbol without date filters.
Some early rows have a null announcement date, and filtering the endpoint by
announcement date can silently omit those valid effective-date intervals.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.dtutil import parse_date
from app.providers import symbols
from app.providers.base import (
    DataProvider,
    InstrumentStatusDTO,
    ProviderSchemaError,
    ProviderUnavailable,
)

_ST_PREFIX = re.compile(r"^(?:S)?(?P<star>\*)?ST", re.IGNORECASE)
_FIELDS = (
    "ts_code",
    "name",
    "start_date",
    "end_date",
    "ann_date",
    "change_reason",
)


def _status_type(name: str) -> str:
    match = _ST_PREFIX.match((name or "").replace(" ", ""))
    if not match:
        return "normal"
    return "star_st" if match.group("star") else "st"


class TushareProvider(DataProvider):
    name = "tushare"
    capabilities = {"status_history"}

    def _request(self, api_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if not settings.tushare_token:
            raise ProviderUnavailable(
                self.name,
                "TUSHARE_TOKEN 未配置，无法拉取历史 PIT 状态",
            )
        try:
            response = httpx.post(
                settings.tushare_base_url,
                json={
                    "api_name": api_name,
                    "token": settings.tushare_token,
                    "params": params,
                    "fields": ",".join(_FIELDS),
                },
                timeout=settings.tushare_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(
                self.name,
                f"{api_name} 请求失败: {exc}",
                cause=exc,
            ) from exc

        if not isinstance(payload, dict) or payload.get("code") != 0:
            message = payload.get("msg") if isinstance(payload, dict) else "响应不是对象"
            raise ProviderUnavailable(self.name, f"{api_name} 返回错误: {message}")
        data = payload.get("data")
        fields = data.get("fields") if isinstance(data, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(fields, list) or not isinstance(items, list):
            raise ProviderSchemaError(self.name, f"{api_name} 响应缺少 fields/items")
        return [
            dict(zip(fields, item, strict=True))
            for item in items
            if isinstance(item, list) and len(item) == len(fields)
        ]

    def get_status_history(self, code: str) -> list[InstrumentStatusDTO]:
        six, exchange = symbols.split_canonical(code)
        canonical = f"{six}.{exchange}"
        # Do not pass start_date/end_date: Tushare applies those inputs to
        # ann_date, dropping valid older rows whose ann_date is null.
        rows = self._request("namechange", {"ts_code": canonical})
        intervals: dict[object, InstrumentStatusDTO] = {}
        for row in rows:
            start = parse_date(row.get("start_date"))
            if start is None:
                continue
            end = parse_date(row.get("end_date"))
            if end is not None and end < start:
                raise ProviderSchemaError(
                    self.name,
                    f"namechange 区间倒置: {canonical} {start}..{end}",
                )
            name = str(row.get("name") or "").strip()
            intervals[start] = InstrumentStatusDTO(
                code=canonical,
                start_date=start,
                end_date=end,
                name=name,
                status_type=_status_type(name),
                change_reason=str(row.get("change_reason") or "").strip() or None,
                announced_date=parse_date(row.get("ann_date")),
            )
        return [intervals[key] for key in sorted(intervals)]
