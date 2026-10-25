from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class BrokerOrderRequest:
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    qty: int
    price: float | None
    account_id: str


class BrokerAdapter(Protocol):
    @property
    def sdk_version(self) -> str: ...

    @property
    def simulation_account_verified(self) -> bool: ...

    def submit_order(self, request: BrokerOrderRequest) -> dict[str, Any]: ...

    def cancel_order(
        self, broker_client_order_id: str, *, account_id: str
    ) -> dict[str, Any]: ...

    def account_snapshot(self, account_id: str) -> dict[str, Any]: ...

    def positions(self, account_id: str) -> list[dict[str, Any]]: ...

    def orders(self, account_id: str) -> list[dict[str, Any]]: ...

    def executions(self, account_id: str) -> list[dict[str, Any]]: ...
