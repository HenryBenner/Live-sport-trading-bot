from __future__ import annotations

from typing import Dict


class OpenOrderManager:
    def __init__(self) -> None:
        self._orders: Dict[str, str] = {}

    def add(self, order_id: str | None, market_ticker: str | None) -> None:
        if order_id and market_ticker:
            self._orders[order_id] = market_ticker

    def remove(self, order_id: str | None) -> None:
        if order_id:
            self._orders.pop(order_id, None)

    def items(self) -> list[tuple[str, str]]:
        return list(self._orders.items())

    def clear(self) -> None:
        self._orders.clear()

    def count(self) -> int:
        return len(self._orders)
