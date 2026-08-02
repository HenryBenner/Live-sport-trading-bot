from __future__ import annotations

import asyncio
import os
import shlex
import threading
from decimal import Decimal, InvalidOperation
from typing import Any

from .aggressive_buyer import AggressiveBuyError
from .audit_log import AuditLogger
from .kalshi_client import KalshiClient, KalshiClientError
from .mode_handler import handle_buy, handle_sell_last
from .open_order_manager import OpenOrderManager
from .runtime_state import RuntimeState, RuntimeStateError, money_text, parse_optional_money


ZERO = Decimal("0")
CENT = Decimal("0.01")


class CommandRouter:
    def __init__(
        self,
        *,
        config: dict[str, Any],
        kalshi: KalshiClient,
        open_orders: OpenOrderManager,
        runtime: RuntimeState,
        audit: AuditLogger,
    ) -> None:
        self.config = config
        self.kalshi = kalshi
        self.open_orders = open_orders
        self.runtime = runtime
        self.audit = audit
        self.last_market_ticker: str | None = None
        self.last_label: str | None = None
        self.last_outcome_side: str | None = None
        self._execution_lock = asyncio.Lock()
        self._active_lock = threading.Lock()
        self._active_cancels: dict[str, threading.Event] = {}

        self.default_market_cap = parse_optional_money(
            os.environ.get("DEFAULT_MARKET_COST_CAP_DOLLARS"),
            name="DEFAULT_MARKET_COST_CAP_DOLLARS",
        )
        self.default_event_cap = parse_optional_money(
            os.environ.get("EVENT_COST_CAP_DOLLARS"),
            name="EVENT_COST_CAP_DOLLARS",
        )
        self.fee_reserve_rate = self._nonnegative_decimal_env(
            "ALL_IN_FEE_RESERVE_RATE", "0.10"
        )
        self.fee_reserve_dollars = self._nonnegative_decimal_env(
            "ALL_IN_FEE_RESERVE_DOLLARS", "0.25"
        )

    async def route(self, raw_command: str) -> dict[str, Any]:
        raw_command = raw_command.strip()
        if raw_command.startswith("/"):
            return await self._route_control(raw_command)

        key = raw_command.upper()
        mode = self.config.get("mode", "paper")

        command = self.config["commands"].get(key)
        if command is None:
            return self._error(key, "Unknown command. Use /commands.")

        if not command.get("enabled", False):
            return self._error(key, "Command disabled by the event config.")

        action = command.get("action")
        if action == "kill_switch":
            return await self._kill(key)

        if self.runtime.kill_active():
            return self._error(key, "Kill switch is active. Use /reset kill when ready.")

        if self.runtime.is_blocked(key):
            return self._error(key, "Command blocked for this event session.")

        if action == "buy":
            return await self._buy(key, command, mode)

        if action == "sell_last_market_position":
            return await self._sell_last(key, mode)

        return self._error(key, f"Unsupported action: {action}")

    async def _buy(
        self, key: str, command: dict[str, Any], mode: str
    ) -> dict[str, Any]:
        if mode != "paper" and not self.kalshi.ready():
            return self._error(key, "Kalshi client is not ready. Check .env.")

        async with self._execution_lock:
            if self.runtime.kill_active() or self.runtime.is_blocked(key):
                return self._error(key, "Command was blocked before execution began.")

            all_in_allowance = self._all_in_allowance(key, command)
            if all_in_allowance <= ZERO:
                return self._error(key, "Event or market cost cap has been reached.")

            contract_budget = self._contract_budget(all_in_allowance)
            if contract_budget < CENT:
                return self._error(
                    key,
                    "Remaining all-in allowance is too small after the fee reserve.",
                )
            if mode == "test" and contract_budget < Decimal("0.9900"):
                return self._error(
                    key,
                    "Remaining all-in allowance is too small for a one-contract test order.",
                )

            cancel_event = threading.Event()
            with self._active_lock:
                self._active_cancels[key] = cancel_event

            try:
                response = await asyncio.to_thread(
                    handle_buy,
                    mode=mode,
                    command_key=key,
                    command=command,
                    config=self.config,
                    kalshi=self.kalshi,
                    spend_cap_dollars=float(contract_budget),
                    cancel_event=cancel_event,
                )
            except (KalshiClientError, AggressiveBuyError) as exc:
                return self._error(key, str(exc))
            finally:
                with self._active_lock:
                    self._active_cancels.pop(key, None)

            all_in_spend = self._all_in_spend(response)
            if mode != "paper" and all_in_spend > ZERO:
                self.runtime.record_spend(key, all_in_spend)
                self.last_market_ticker = command.get("market_ticker")
                self.last_label = command.get("label")
                self.last_outcome_side = command.get("side", "yes")

            response["all_in_spend_dollars"] = money_text(all_in_spend)
            response["all_in_allowance_dollars"] = money_text(all_in_allowance)
            self._track_open_order(response)
            self.audit.write(
                "buy_result",
                session_id=self.runtime.session_id,
                key=key,
                mode=mode,
                market_ticker=command.get("market_ticker"),
                all_in_spend_dollars=money_text(all_in_spend),
                response=response,
            )
            return response

    async def _sell_last(self, key: str, mode: str) -> dict[str, Any]:
        if mode != "paper" and not self.kalshi.ready():
            return self._error(key, "Kalshi client is not ready. Check .env.")
        async with self._execution_lock:
            try:
                response = await asyncio.to_thread(
                    handle_sell_last,
                    mode=mode,
                    command_key=key,
                    last_market_ticker=self.last_market_ticker,
                    last_label=self.last_label,
                    last_outcome_side=self.last_outcome_side,
                    config=self.config,
                    kalshi=self.kalshi,
                )
                self._track_open_order(response)
                return response
            except KalshiClientError as exc:
                return self._error(key, str(exc))

    async def _kill(self, key: str) -> dict[str, Any]:
        self.runtime.kill()
        with self._active_lock:
            for cancel_event in self._active_cancels.values():
                cancel_event.set()

        canceled: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        if self.config.get("mode") != "paper" and self.kalshi.ready():
            first = await self._cancel_all_safely()
            canceled.extend(first["canceled"])
            errors.extend(first["errors"])

            # Wait for an in-flight sweep to observe its cancellation flag, then
            # query Kalshi once more to close the small submit/cancel race.
            async with self._execution_lock:
                pass
            second = await self._cancel_all_safely()
            canceled.extend(second["canceled"])
            errors.extend(second["errors"])

        self.open_orders.clear()
        response = {
            "type": "kill_switch",
            "key": key,
            "status": "active",
            "canceled": canceled,
            "errors": errors,
            "message": "Trading disabled, active sweeps stopped, and all resting orders canceled.",
        }
        self.audit.write(
            "kill_switch",
            session_id=self.runtime.session_id,
            canceled_count=len(canceled),
            errors=errors,
        )
        return response

    async def _cancel_all_safely(self) -> dict[str, list[dict[str, Any]]]:
        try:
            return await asyncio.to_thread(self.kalshi.cancel_all_open_orders)
        except Exception as exc:
            return {"canceled": [], "errors": [{"error": str(exc)}]}

    async def _route_control(self, raw_command: str) -> dict[str, Any]:
        try:
            parts = shlex.split(raw_command)
        except ValueError as exc:
            return self._error(raw_command, f"Invalid command: {exc}")
        if not parts:
            return self._error(raw_command, "Empty command.")

        name = parts[0].lower()
        if name in {"/help", "/commands"}:
            return self._commands_response()
        if name == "/status":
            return self.status_response()
        if name in {"/block", "/unblock"}:
            return self._set_block(name == "/block", parts)
        if name == "/limit":
            return self._set_limit(parts)
        if name == "/disarm":
            return self._set_block(True, ["/block", "all"])
        if name == "/arm":
            if self.runtime.kill_active():
                return self._error(raw_command, "Reset the kill switch before arming.")
            return self._set_block(False, ["/unblock", "all"])
        if name == "/reset" and len(parts) == 2 and parts[1].lower() == "kill":
            self.runtime.reset_kill()
            self.audit.write("kill_switch_reset", session_id=self.runtime.session_id)
            return self._control_result("Kill switch reset. Existing command blocks remain.")
        return self._error(raw_command, "Unknown control command. Use /help.")

    def _set_block(self, should_block: bool, parts: list[str]) -> dict[str, Any]:
        if len(parts) != 2:
            verb = "block" if should_block else "unblock"
            return self._error(" ".join(parts), f"Usage: /{verb} A or /{verb} all")

        target = parts[1].upper()
        buy_keys = self._buy_keys()
        keys = buy_keys if target == "ALL" else [target]
        if target != "ALL" and target not in buy_keys:
            return self._error(target, "Only configured buy commands can be blocked.")

        if should_block:
            self.runtime.block(keys)
            with self._active_lock:
                for key in keys:
                    cancel_event = self._active_cancels.get(key)
                    if cancel_event is not None:
                        cancel_event.set()
        else:
            self.runtime.unblock(keys)

        action = "blocked" if should_block else "unblocked"
        self.audit.write(
            f"commands_{action}", session_id=self.runtime.session_id, keys=keys
        )
        return self._control_result(f"{', '.join(keys)} {action} for this event session.")

    def _set_limit(self, parts: list[str]) -> dict[str, Any]:
        if len(parts) not in {3, 4}:
            return self._error(
                " ".join(parts),
                "Usage: /limit event 500, /limit market A 100, or /limit press A 25",
            )

        scope = parts[1].lower()
        if scope == "event" and len(parts) == 3:
            key = None
            raw_amount = parts[2]
        elif scope in {"market", "press"} and len(parts) == 4:
            key = parts[2].upper()
            if key not in self._buy_keys():
                return self._error(key, "Unknown buy command.")
            raw_amount = parts[3]
        else:
            return self._error(" ".join(parts), "Invalid /limit syntax. Use /help.")

        if raw_amount.lower() in {"infinite", "infinity", "off", "none"}:
            if scope == "press":
                return self._error(
                    " ".join(parts), "A per-press limit must be a dollar amount."
                )
            amount = None
        else:
            try:
                amount = parse_optional_money(raw_amount, name=f"{scope} limit")
            except RuntimeStateError as exc:
                return self._error(" ".join(parts), str(exc))

        self.runtime.set_limit_override(scope, key, amount)
        with self._active_lock:
            targets = (
                list(self._active_cancels.values())
                if scope == "event"
                else [self._active_cancels.get(str(key))]
            )
            for cancel_event in targets:
                if cancel_event is not None:
                    cancel_event.set()
        label = "infinite" if amount is None else f"${amount:.2f}"
        target = "event" if key is None else f"{scope} {key}"
        self.audit.write(
            "limit_changed",
            session_id=self.runtime.session_id,
            scope=scope,
            key=key,
            amount_dollars=money_text(amount),
        )
        return self._control_result(f"{target} cost cap set to {label}.")

    def status_response(self) -> dict[str, Any]:
        commands = []
        for key in self._buy_keys():
            command = self.config["commands"][key]
            commands.append(
                {
                    "key": key,
                    "label": command.get("label", ""),
                    "line_or_prop": command.get("line_or_prop", ""),
                    "market_ticker": command.get("market_ticker", ""),
                    "side": command.get("side", ""),
                    "blocked": self.runtime.is_blocked(key),
                    "press_cap_dollars": money_text(self._effective_press_cap(key, command)),
                    "market_cap_dollars": money_text(self._effective_market_cap(key)),
                    "spent_all_in_dollars": money_text(self.runtime.spent_market(key)),
                }
            )
        return {
            "type": "status",
            "message": "Current event-session status.",
            "session_id": self.runtime.session_id,
            "profile_name": self.config.get("profile_name", ""),
            "event_name": self.config.get("event_name", ""),
            "event_ticker": self.config.get("event_ticker", ""),
            "mode": self.config.get("mode", ""),
            "kill_switch_active": self.runtime.kill_active(),
            "event_cap_dollars": money_text(self._effective_event_cap()),
            "event_spent_all_in_dollars": money_text(self.runtime.spent_event()),
            "commands": commands,
        }

    def _commands_response(self) -> dict[str, Any]:
        response = self.status_response()
        response["type"] = "commands"
        response["message"] = (
            "/status | /block A|all | /unblock A|all | "
            "/limit event AMOUNT|infinite | /limit market A AMOUNT|infinite | "
            "/limit press A AMOUNT|infinite | /disarm | /arm | /reset kill | K"
        )
        return response

    def _all_in_allowance(self, key: str, command: dict[str, Any]) -> Decimal:
        allowances = [self._effective_press_cap(key, command)]
        event_cap = self._effective_event_cap()
        market_cap = self._effective_market_cap(key)
        if event_cap is not None:
            allowances.append(max(event_cap - self.runtime.spent_event(), ZERO))
        if market_cap is not None:
            allowances.append(max(market_cap - self.runtime.spent_market(key), ZERO))
        return min(allowances)

    def _contract_budget(self, all_in_allowance: Decimal) -> Decimal:
        usable = all_in_allowance - self.fee_reserve_dollars
        if usable <= ZERO:
            return ZERO
        return (usable / (Decimal("1") + self.fee_reserve_rate)).quantize(
            Decimal("0.0001")
        )

    def _effective_press_cap(
        self, key: str, command: dict[str, Any]
    ) -> Decimal:
        has_override, override = self.runtime.limit_override("press", key)
        if has_override:
            if override is None:
                raise RuntimeError("Per-press limit cannot be infinite.")
            return override
        return Decimal(str(command.get("spend_up_to_dollars", "0")))

    def _effective_market_cap(self, key: str) -> Decimal | None:
        has_override, override = self.runtime.limit_override("market", key)
        return override if has_override else self.default_market_cap

    def _effective_event_cap(self) -> Decimal | None:
        has_override, override = self.runtime.limit_override("event")
        return override if has_override else self.default_event_cap

    def _all_in_spend(self, response: dict[str, Any]) -> Decimal:
        kalshi = response.get("kalshi")
        if not isinstance(kalshi, dict):
            return ZERO
        if kalshi.get("total_debit_dollars") not in (None, ""):
            return Decimal(str(kalshi["total_debit_dollars"]))
        fill_count = Decimal(str(kalshi.get("fill_count", "0")))
        average_price = Decimal(str(kalshi.get("average_fill_price", "0")))
        average_fee = Decimal(str(kalshi.get("average_fee_paid", "0")))
        return fill_count * (average_price + average_fee)

    def _track_open_order(self, response: dict[str, Any]) -> None:
        kalshi_response = response.get("kalshi")
        if not isinstance(kalshi_response, dict):
            return
        order_id = kalshi_response.get("order_id")
        market_ticker = response.get("market_ticker")
        try:
            remaining_value = Decimal(str(kalshi_response.get("remaining_count", "0")))
        except InvalidOperation:
            remaining_value = ZERO
        if order_id and remaining_value > ZERO:
            self.open_orders.add(order_id, market_ticker)

    def _buy_keys(self) -> list[str]:
        return sorted(
            key
            for key, command in self.config["commands"].items()
            if command.get("action") == "buy" and command.get("enabled", False)
        )

    def _nonnegative_decimal_env(self, name: str, default: str) -> Decimal:
        raw = os.environ.get(name, default).strip()
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise RuntimeError(f"{name} must be numeric.") from exc
        if not value.is_finite() or value < ZERO:
            raise RuntimeError(f"{name} must be nonnegative.")
        return value

    def _control_result(self, message: str) -> dict[str, Any]:
        return {"type": "control", "status": "ok", "message": message}

    def _error(self, key: str, message: str) -> dict[str, Any]:
        return {"type": "error", "key": key, "message": message}
