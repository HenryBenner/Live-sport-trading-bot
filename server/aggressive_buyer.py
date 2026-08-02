from __future__ import annotations

import time
import threading
import uuid
from decimal import Decimal, ROUND_FLOOR
from typing import Any
from urllib.parse import urlencode

import requests

from .kalshi_client import KalshiClient


ZERO = Decimal("0")
ONE = Decimal("1")
CENTI_CONTRACT = Decimal("0.01")
WHOLE_CONTRACT = Decimal("1")


class AggressiveBuyError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        ambiguous_write: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ambiguous_write = ambiguous_write


class AggressiveBuyer:
    def __init__(self, kalshi: KalshiClient) -> None:
        self.kalshi = kalshi
        self.session = requests.Session()

    def sweep(
        self,
        *,
        ticker: str,
        spend_cap_dollars: float,
        outcome_side: str = "yes",
        maximum_buy_price: str = "1.0000",
        max_attempts: int = 100,
        max_seconds: float = 10.0,
        no_progress_limit: int = 20,
        retry_delay_seconds: float = 0.05,
        error_limit: int = 10,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        cap = Decimal(str(spend_cap_dollars))
        ceiling = Decimal(str(maximum_buy_price))
        self._validate(
            cap=cap,
            ceiling=ceiling,
            max_attempts=max_attempts,
            max_seconds=max_seconds,
            no_progress_limit=no_progress_limit,
            retry_delay_seconds=retry_delay_seconds,
            error_limit=error_limit,
            outcome_side=outcome_side,
        )

        started = time.monotonic()
        deadline = started + max_seconds
        count_step = (
            WHOLE_CONTRACT
            if cancel_event is not None and cancel_event.is_set()
            else self._market_count_step(ticker)
        )
        remaining = cap
        filled = ZERO
        contract_cost = ZERO
        fees = ZERO
        attempts = 0
        no_progress = 0
        consecutive_errors = 0
        stop_reason = "unknown"
        orders: list[dict[str, Any]] = []
        errors: list[str] = []

        while True:
            if cancel_event is not None and cancel_event.is_set():
                stop_reason = "canceled_by_control_command"
                break
            if attempts >= max_attempts:
                stop_reason = "max_attempts_reached"
                break
            if time.monotonic() >= deadline:
                stop_reason = "max_retry_window_reached"
                break
            if remaining < Decimal("0.0001"):
                stop_reason = "spend_cap_reached"
                break
            if no_progress >= no_progress_limit:
                stop_reason = "no_more_immediate_liquidity"
                break
            if consecutive_errors >= error_limit:
                stop_reason = "too_many_api_errors"
                break

            try:
                orderbook = self._request(
                    "GET", f"/markets/{ticker}/orderbook?depth=0"
                )
                plan = self._build_sweep_order(
                    orderbook=orderbook,
                    remaining_budget=remaining,
                    maximum_buy_price=ceiling,
                    count_step=count_step,
                    outcome_side=outcome_side,
                )
                consecutive_errors = 0
            except AggressiveBuyError as exc:
                errors.append(str(exc))
                consecutive_errors += 1
                if not self._retryable(exc):
                    stop_reason = "fatal_orderbook_error"
                    break
                self._sleep(
                    base=retry_delay_seconds,
                    streak=consecutive_errors,
                    rate_limited=exc.status_code == 429,
                    cancel_event=cancel_event,
                )
                continue

            if plan is None:
                no_progress += 1
                self._interruptible_wait(retry_delay_seconds, cancel_event)
                continue

            attempts += 1
            client_order_id = f"sweep-{uuid.uuid4()}"

            try:
                result, submit_errors = self._submit_with_retries(
                    ticker=ticker,
                    count=plan["count"],
                    price=plan["price"],
                    client_order_id=client_order_id,
                    outcome_side=outcome_side,
                    deadline=deadline,
                    error_limit=error_limit,
                    retry_delay_seconds=retry_delay_seconds,
                    cancel_event=cancel_event,
                )
                errors.extend(submit_errors)
                consecutive_errors = 0
            except AggressiveBuyError as exc:
                errors.append(str(exc))
                if cancel_event is not None and cancel_event.is_set():
                    stop_reason = "canceled_by_control_command"
                else:
                    stop_reason = (
                        "ambiguous_order_status"
                        if exc.ambiguous_write
                        else "fatal_order_error"
                    )
                break

            fill_count = self._first_decimal(
                result, "fill_count", "fill_count_fp"
            )
            average_book_price = self._first_decimal(result, "average_fill_price")
            average_price = (
                ONE - average_book_price
                if outcome_side == "no" and average_book_price > ZERO
                else average_book_price
            )
            average_fee = self._first_decimal(result, "average_fee_paid")
            if fill_count > ZERO and average_price <= ZERO:
                average_price = plan["price"]

            this_cost = min(fill_count * average_price, remaining)
            this_fees = fill_count * average_fee
            remaining -= this_cost
            filled += fill_count
            contract_cost += this_cost
            fees += this_fees

            orders.append(
                {
                    "order_id": result.get("order_id"),
                    "client_order_id": result.get(
                        "client_order_id", client_order_id
                    ),
                    "requested_count": self._format_count(plan["count"]),
                    "limit_price": self._format_price(plan["price"]),
                    "fill_count": self._format_count(fill_count),
                    "average_fill_price": self._format_price(average_price),
                    "contract_cost": self._format_money(this_cost),
                    "fees": self._format_money(this_fees),
                }
            )

            if fill_count > ZERO:
                no_progress = 0
            else:
                no_progress += 1
                self._interruptible_wait(retry_delay_seconds, cancel_event)

        elapsed = time.monotonic() - started
        weighted_average = contract_cost / filled if filled > ZERO else ZERO
        return {
            "strategy": "aggressive_orderbook_sweep",
            "ticker": ticker,
            "outcome_side": outcome_side,
            "spend_cap_dollars": self._format_money(cap),
            "contract_cost_dollars": self._format_money(contract_cost),
            "fee_cost_dollars": self._format_money(fees),
            "total_debit_dollars": self._format_money(contract_cost + fees),
            "remaining_contract_budget_dollars": self._format_money(
                max(remaining, ZERO)
            ),
            "fill_count": self._format_count(filled),
            "average_fill_price": self._format_price(weighted_average),
            "attempts": attempts,
            "elapsed_seconds": round(elapsed, 4),
            "stop_reason": stop_reason,
            "orders": orders,
            "errors": errors[-10:],
        }

    def _validate(
        self,
        *,
        cap: Decimal,
        ceiling: Decimal,
        max_attempts: int,
        max_seconds: float,
        no_progress_limit: int,
        retry_delay_seconds: float,
        error_limit: int,
        outcome_side: str,
    ) -> None:
        if cap <= ZERO:
            raise AggressiveBuyError("spend cap must be positive")
        if ceiling <= ZERO or ceiling > ONE:
            raise AggressiveBuyError(
                "maximum buy price must be greater than 0 and at most 1.0000"
            )
        if max_attempts < 1 or no_progress_limit < 1 or error_limit < 1:
            raise AggressiveBuyError("retry limits must be positive")
        if max_seconds <= 0:
            raise AggressiveBuyError("retry window must be positive")
        if retry_delay_seconds < 0:
            raise AggressiveBuyError("retry delay cannot be negative")
        if outcome_side not in {"yes", "no"}:
            raise AggressiveBuyError("outcome side must be 'yes' or 'no'")

    def _market_count_step(self, ticker: str) -> Decimal:
        try:
            data = self._request("GET", f"/markets/{ticker}")
        except AggressiveBuyError:
            return WHOLE_CONTRACT
        market = data.get("market", {})
        return (
            CENTI_CONTRACT
            if market.get("fractional_trading_enabled")
            else WHOLE_CONTRACT
        )

    def _build_sweep_order(
        self,
        *,
        orderbook: dict[str, Any],
        remaining_budget: Decimal,
        maximum_buy_price: Decimal,
        count_step: Decimal,
        outcome_side: str = "yes",
    ) -> dict[str, Decimal] | None:
        opposite_book = "no_dollars" if outcome_side == "yes" else "yes_dollars"
        raw_levels = orderbook.get("orderbook_fp", {}).get(opposite_book, [])
        asks: list[tuple[Decimal, Decimal]] = []

        for level in raw_levels:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            opposite_bid = Decimal(str(level[0]))
            count = Decimal(str(level[1]))
            outcome_ask = ONE - opposite_bid
            if (
                count <= ZERO
                or outcome_ask <= ZERO
                or outcome_ask >= ONE
                or outcome_ask > maximum_buy_price
            ):
                continue
            asks.append((outcome_ask, count))

        if not asks:
            return None

        asks.sort(key=lambda item: item[0])
        cumulative_count = ZERO
        best_count = ZERO
        best_price = ZERO

        for ask_price, level_count in asks:
            cumulative_count += level_count
            affordable = (remaining_budget / ask_price).quantize(
                count_step, rounding=ROUND_FLOOR
            )
            candidate = min(cumulative_count, affordable)
            if candidate >= count_step:
                best_count = candidate
                best_price = ask_price
            if affordable < cumulative_count:
                break

        if best_count < count_step:
            return None
        return {"count": best_count, "price": best_price}

    def _submit_with_retries(
        self,
        *,
        ticker: str,
        count: Decimal,
        price: Decimal,
        client_order_id: str,
        outcome_side: str = "yes",
        deadline: float,
        error_limit: int,
        retry_delay_seconds: float,
        cancel_event: threading.Event | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        book_price = price if outcome_side == "yes" else ONE - price
        payload = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": "bid" if outcome_side == "yes" else "ask",
            "count": self._format_count(count),
            "price": self._format_price(book_price),
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "maker",
            "post_only": False,
            "cancel_order_on_pause": True,
            "reduce_only": False,
            "subaccount": self.kalshi.subaccount,
            "exchange_index": self.kalshi.exchange_index,
        }
        errors: list[str] = []
        streak = 0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise AggressiveBuyError("order submission canceled by control command")
            try:
                return (
                    self._request(
                        "POST", "/portfolio/events/orders", json_body=payload
                    ),
                    errors,
                )
            except AggressiveBuyError as exc:
                errors.append(str(exc))
                if exc.status_code == 409:
                    recovered = self._recover_order(client_order_id)
                    if recovered is not None:
                        return recovered, errors
                    raise
                if not self._retryable(exc):
                    raise
                if exc.ambiguous_write or (
                    exc.status_code is not None and exc.status_code >= 500
                ):
                    recovered = self._recover_order(client_order_id)
                    if recovered is not None:
                        return recovered, errors

                streak += 1
                if streak >= error_limit or time.monotonic() >= deadline:
                    raise AggressiveBuyError(
                        "unable to confirm order after repeated retries",
                        status_code=exc.status_code,
                        ambiguous_write=exc.ambiguous_write
                        or exc.status_code is None
                        or exc.status_code >= 500,
                    ) from exc
                self._sleep(
                    base=retry_delay_seconds,
                    streak=streak,
                    rate_limited=exc.status_code == 429,
                    cancel_event=cancel_event,
                )

    def _recover_order(self, client_order_id: str) -> dict[str, Any] | None:
        query = urlencode(
            {"subaccount": self.kalshi.subaccount, "limit": 100}
        )
        try:
            data = self._request("GET", f"/portfolio/orders?{query}")
        except AggressiveBuyError:
            return None

        for order in data.get("orders", []):
            if order.get("client_order_id") != client_order_id:
                continue
            fill_count = self._first_decimal(
                order, "fill_count_fp", "fill_count"
            )
            total_cost = self._sum_decimal(
                order,
                "taker_fill_cost_dollars",
                "maker_fill_cost_dollars",
            )
            total_fees = self._sum_decimal(
                order, "taker_fees_dollars", "maker_fees_dollars"
            )
            return {
                "order_id": order.get("order_id"),
                "client_order_id": client_order_id,
                "fill_count": self._format_count(fill_count),
                "remaining_count": str(
                    order.get(
                        "remaining_count_fp",
                        order.get("remaining_count", "0"),
                    )
                ),
                "average_fill_price": self._format_price(
                    total_cost / fill_count if fill_count > ZERO else ZERO
                ),
                "average_fee_paid": self._format_price(
                    total_fees / fill_count if fill_count > ZERO else ZERO
                ),
            }
        return None

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        method = method.upper()
        try:
            response = self.session.request(
                method,
                self.kalshi.base_url + endpoint,
                headers=self.kalshi._headers(method, endpoint),
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise AggressiveBuyError(
                f"Kalshi {method} {endpoint} network failure: {exc}",
                ambiguous_write=method in {"POST", "PUT", "PATCH", "DELETE"},
            ) from exc

        if response.status_code >= 400:
            raise AggressiveBuyError(
                f"Kalshi {method} {endpoint} failed: "
                f"{response.status_code} {response.text}",
                status_code=response.status_code,
            )
        return response.json() if response.text else {}

    def _retryable(self, exc: AggressiveBuyError) -> bool:
        return (
            exc.status_code is None
            or exc.status_code == 429
            or exc.status_code >= 500
        )

    def _sleep(
        self,
        *,
        base: float,
        streak: int,
        rate_limited: bool,
        cancel_event: threading.Event | None = None,
    ) -> None:
        if rate_limited:
            delay = min(1.0, max(0.05, base) * (2 ** min(streak - 1, 4)))
        else:
            delay = min(0.5, max(0.01, base))
        self._interruptible_wait(delay, cancel_event)

    def _interruptible_wait(
        self, delay: float, cancel_event: threading.Event | None
    ) -> None:
        if delay <= 0:
            return
        if cancel_event is None:
            time.sleep(delay)
        else:
            cancel_event.wait(delay)

    def _first_decimal(
        self, data: dict[str, Any], *keys: str
    ) -> Decimal:
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                return Decimal(str(value))
        return ZERO

    def _sum_decimal(self, data: dict[str, Any], *keys: str) -> Decimal:
        total = ZERO
        for key in keys:
            value = data.get(key)
            if value not in (None, ""):
                total += Decimal(str(value))
        return total

    def _format_count(self, value: Decimal) -> str:
        return format(value.quantize(CENTI_CONTRACT), "f")

    def _format_price(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.0001")), "f")

    def _format_money(self, value: Decimal) -> str:
        return format(value.quantize(Decimal("0.0001")), "f")
