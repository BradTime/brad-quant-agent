"""Adapter for the official Eastmoney/掘金 ``gm.api`` SDK."""

from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
from typing import Any

from app.broker.base import BrokerOrderRequest


def to_emt_symbol(code: str) -> str:
    symbol, market = code.split(".", 1)
    exchange = {
        "SH": "SHSE",
        "SZ": "SZSE",
        "BJ": "BJSE",
    }.get(market)
    if exchange is None or len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("EMT 不支持该证券代码")
    return f"{exchange}.{symbol}"


def from_emt_symbol(symbol: str) -> str:
    exchange, code = symbol.split(".", 1)
    market = {"SHSE": "SH", "SZSE": "SZ", "BJSE": "BJ"}.get(
        exchange
    )
    if market is None or len(code) != 6 or not code.isdigit():
        raise ValueError("官方 SDK 返回未知证券代码")
    return f"{code}.{market}"


class OfficialEmtAdapter:
    """Thin typed wrapper; the official terminal must initialize live mode."""

    def __init__(self, sdk: Any | None = None) -> None:
        if sdk is None:
            try:
                sdk = importlib.import_module("gm.api")
            except ImportError as exc:
                raise RuntimeError(
                    "未安装东财终端提供的官方 gm.api SDK"
                ) from exc
        required = (
            "order_volume",
            "order_cancel",
            "get_cash",
            "get_position",
            "get_orders",
            "get_execution_reports",
            "timer",
            "run",
            "set_token",
        )
        missing = [name for name in required if not hasattr(sdk, name)]
        if missing:
            raise RuntimeError(
                f"官方 gm.api SDK 缺少接口: {','.join(missing)}"
            )
        self._sdk = sdk

    @property
    def sdk_version(self) -> str:
        return str(
            getattr(
                self._sdk,
                "__version__",
                getattr(self._sdk, "SDK_VERSION", "unknown"),
            )
        )[:32]

    @property
    def api(self) -> Any:
        return self._sdk

    @property
    def simulation_account_verified(self) -> bool:
        # gm.api exposes the same MODE_LIVE path for simulation and live
        # accounts and documents no machine-verifiable account-type field.
        return False

    def runtime_evidence(self) -> dict[str, str]:
        module_name = str(getattr(self._sdk, "__name__", ""))
        file_value = str(getattr(self._sdk, "__file__", ""))
        if module_name != "gm.api" or not file_value:
            raise RuntimeError("不是官方 gm.api 模块运行时")
        path = Path(file_value).resolve()
        if not path.is_file():
            raise RuntimeError("官方 gm.api 模块文件不存在")
        return {
            "module": module_name,
            "sdkVersion": self.sdk_version,
            "moduleSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    @staticmethod
    def _dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "__dict__"):
            return {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        raise RuntimeError("官方 SDK 返回了未知对象")

    def _normalize_order(self, value: Any) -> dict[str, Any]:
        row = self._dict(value)
        status = row.get("status")
        mapping = {
            getattr(self._sdk, "OrderStatus_New", object()): "acked",
            getattr(
                self._sdk, "OrderStatus_PartiallyFilled", object()
            ): "partially_filled",
            getattr(self._sdk, "OrderStatus_Filled", object()): "filled",
            getattr(self._sdk, "OrderStatus_Canceled", object()): "cancelled",
            getattr(self._sdk, "OrderStatus_Rejected", object()): "rejected",
        }
        row["_normalizedStatus"] = mapping.get(status, "unknown")
        if row.get("symbol"):
            row["_normalizedCode"] = from_emt_symbol(
                str(row["symbol"])
            )
        side = row.get("side")
        row["_normalizedSide"] = (
            "buy"
            if side == getattr(self._sdk, "OrderSide_Buy", object())
            else (
                "sell"
                if side
                == getattr(self._sdk, "OrderSide_Sell", object())
                else "unknown"
            )
        )
        row["_normalizedQty"] = int(
            row.get("volume") or row.get("target_volume") or 0
        )
        return row

    def _normalize_execution(self, value: Any) -> dict[str, Any]:
        row = self._dict(value)
        if row.get("symbol"):
            row["_normalizedCode"] = from_emt_symbol(
                str(row["symbol"])
            )
        row["_normalizedQty"] = int(row.get("volume") or 0)
        return row

    def submit_order(self, request: BrokerOrderRequest) -> dict[str, Any]:
        if request.side not in {"buy", "sell"}:
            raise ValueError("委托方向无效")
        if request.order_type not in {"limit", "market"}:
            raise ValueError("委托类型无效")
        result = self._sdk.order_volume(
            symbol=to_emt_symbol(request.symbol),
            volume=request.qty,
            side=(
                self._sdk.OrderSide_Buy
                if request.side == "buy"
                else self._sdk.OrderSide_Sell
            ),
            order_type=(
                self._sdk.OrderType_Limit
                if request.order_type == "limit"
                else self._sdk.OrderType_Market
            ),
            position_effect=(
                self._sdk.PositionEffect_Open
                if request.side == "buy"
                else self._sdk.PositionEffect_Close
            ),
            price=request.price or 0,
            account=request.account_id,
        )
        rows = result if isinstance(result, list) else [result]
        if len(rows) != 1:
            raise RuntimeError("官方 SDK 未返回唯一委托")
        return self._normalize_order(rows[0])

    def cancel_order(
        self, broker_client_order_id: str, *, account_id: str
    ) -> dict[str, Any]:
        result = self._sdk.order_cancel(
            wait_cancel_orders={
                "cl_ord_id": broker_client_order_id,
                "account_id": account_id,
            }
        )
        rows = result if isinstance(result, list) else [result]
        return self._dict(rows[0]) if rows and rows[0] else {}

    def account_snapshot(self, account_id: str) -> dict[str, Any]:
        return self._dict(self._sdk.get_cash(account_id=account_id))

    def positions(self, account_id: str) -> list[dict[str, Any]]:
        return [
            self._dict(row)
            for row in self._sdk.get_position(account_id=account_id)
        ]

    def orders(self, account_id: str) -> list[dict[str, Any]]:
        rows = [
            self._normalize_order(row) for row in self._sdk.get_orders()
        ]
        return [
            row
            for row in rows
            if not row.get("account_id")
            or row.get("account_id") == account_id
        ]

    def executions(self, account_id: str) -> list[dict[str, Any]]:
        rows = [
            self._normalize_execution(row)
            for row in self._sdk.get_execution_reports()
        ]
        return [
            row
            for row in rows
            if not row.get("account_id")
            or row.get("account_id") == account_id
        ]
