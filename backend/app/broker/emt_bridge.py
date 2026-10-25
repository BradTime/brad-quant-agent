"""Entrypoint executed by the official Eastmoney terminal Python runtime."""

from __future__ import annotations

import os
import time
from pathlib import Path
from uuid import uuid4

from app.broker.emt import OfficialEmtAdapter
from app.core.config import settings
from app.services import broker_gateway

_adapter: OfficialEmtAdapter | None = None
_instance_id = uuid4().hex
_binding_id = os.getenv("EMT_BINDING_ID", "")
_last_reconcile = 0.0


def init(context) -> None:
    del context
    if not settings.emt_enabled or not _binding_id:
        raise RuntimeError("EMT bridge 未显式启用或缺少 EMT_BINDING_ID")
    global _adapter
    _adapter = OfficialEmtAdapter()
    cash = _adapter.account_snapshot(settings.emt_account_id)
    if str(cash.get("account_id") or "") != settings.emt_account_id:
        raise RuntimeError("官方 SDK 返回账户与 EMT_ACCOUNT_ID 不一致")
    broker_gateway.claim_bridge(
        _binding_id,
        instance_id=_instance_id,
        sdk_version=_adapter.sdk_version,
    )
    timer_result = _adapter.api.timer(
        timer_func=poll,
        period=3000,
        start_delay=0,
    )
    if not isinstance(timer_result, dict) or timer_result.get(
        "timer_status"
    ) != 0:
        raise RuntimeError("官方 EMT timer 启动失败")


def poll(context) -> None:
    del context
    global _last_reconcile
    if _adapter is None:
        return
    broker_gateway.claim_bridge(
        _binding_id,
        instance_id=_instance_id,
        sdk_version=_adapter.sdk_version,
    )
    if _adapter.simulation_account_verified:
        for _ in range(settings.emt_max_orders_per_second):
            if (
                broker_gateway.process_one(
                    _binding_id,
                    instance_id=_instance_id,
                    adapter=_adapter,
                )
                is None
            ):
                break
    now = time.monotonic()
    if now - _last_reconcile >= 30:
        broker_gateway.reconcile(
            _binding_id,
            instance_id=_instance_id,
            adapter=_adapter,
        )
        _last_reconcile = now


def on_order_status(context, order) -> None:
    del context, order
    if _adapter is not None:
        broker_gateway.reconcile(
            _binding_id,
            instance_id=_instance_id,
            adapter=_adapter,
        )


def on_execution_report(context, execution) -> None:
    del context, execution
    if _adapter is not None:
        broker_gateway.reconcile(
            _binding_id,
            instance_id=_instance_id,
            adapter=_adapter,
        )


def main() -> None:
    if not settings.emt_enabled:
        raise RuntimeError("EMT_ENABLED=false，拒绝启动官方 bridge")
    adapter = OfficialEmtAdapter()
    sdk = adapter.api
    sdk.set_token(settings.emt_token)
    sdk.run(
        strategy_id=settings.emt_strategy_id,
        filename=str(Path(__file__).resolve()),
        mode=sdk.MODE_LIVE,
        token=settings.emt_token,
        serv_addr=settings.emt_serv_addr,
    )


if __name__ == "__main__":
    main()
