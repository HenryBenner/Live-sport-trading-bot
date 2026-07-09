from __future__ import annotations

from typing import Any

from .kalshi_client import KalshiClient, KalshiClientError
from .mode_handler import handle_buy, handle_sell_last
from .open_order_manager import OpenOrderManager


class CommandRouter:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        kalshi: KalshiClient,
        open_orders: OpenOrderManager,
    ) -> None:
        self.config = config
        self.kalshi = kalshi
        self.open_orders = open_orders
        self.kill_switch_active = False
        self.last_market_ticker: str | None = None
        self.last_label: str | None = None

    async def route(self, key: str) -> dict[str, Any]:
        key = key.strip()
        mode = self.config.get("mode", "paper")

        if len(key) != 1:
            return self._error(key, "Command must be one character.")

        command = self.config["commands"].get(key)
        if command is None:
            return self._error(key, "Unknown command.")

        if not command.get("enabled", False):
            return self._error(key, "Command disabled.")

        action = command.get("action")

        if self.kill_switch_active and action != "kill_switch":
            return self._error(key, "Kill switch is active. Restart server to reset.")

        if action == "kill_switch":
            return await self._kill(key)

        if action == "buy":
            if mode != "paper" and not self.kalshi.ready():
                return self._error(key, "Kalshi client is not ready. Check .env.")

            try:
                response = handle_buy(
                    mode=mode,
                    command_key=key,
                    command=command,
                    config=self.config,
                    kalshi=self.kalshi,
                )
                self.last_market_ticker = command.get("market_ticker")
                self.last_label = command.get("label")
                self._track_open_order(response)
                return response
            except KalshiClientError as exc:
                return self._error(key, str(exc))

        if action == "sell_last_market_position":
            if mode != "paper" and not self.kalshi.ready():
                return self._error(key, "Kalshi client is not ready. Check .env.")

            try:
                response = handle_sell_last(
                    mode=mode,
                    command_key=key,
                    last_market_ticker=self.last_market_ticker,
                    last_label=self.last_label,
                    config=self.config,
                    kalshi=self.kalshi,
                )
                self._track_open_order(response)
                return response
            except KalshiClientError as exc:
                return self._error(key, str(exc))

        return self._error(key, f"Unsupported action: {action}")

    async def _kill(self, key: str) -> dict[str, Any]:
        self.kill_switch_active = True

        canceled = []
        errors = []

        if self.config.get("cancel_open_orders_on_kill", True):
            for order_id, ticker in self.open_orders.items():
                try:
                    result = self.kalshi.cancel_order(order_id, ticker)
                    canceled.append({"order_id": order_id, "result": result})
                    self.open_orders.remove(order_id)
                except Exception as exc:
                    errors.append({"order_id": order_id, "error": str(exc)})

        return {
            "type": "kill_switch",
            "key": key,
            "status": "active",
            "canceled": canceled,
            "errors": errors,
            "message": "Trading disabled. Open order cancel requested.",
        }

    def _track_open_order(self, response: dict[str, Any]) -> None:
        kalshi_response = response.get("kalshi")
        if not isinstance(kalshi_response, dict):
            return

        order_id = kalshi_response.get("order_id")
        market_ticker = response.get("market_ticker")
        remaining = str(kalshi_response.get("remaining_count", "0"))

        try:
            remaining_value = float(remaining)
        except ValueError:
            remaining_value = 0.0

        if order_id and remaining_value > 0:
            self.open_orders.add(order_id, market_ticker)

    def _error(self, key: str, message: str) -> dict[str, Any]:
        return {
            "type": "error",
            "key": key,
            "message": message,
        }
