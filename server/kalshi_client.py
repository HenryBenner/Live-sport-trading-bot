from __future__ import annotations

import base64
import datetime as dt
import os
import uuid
from decimal import Decimal, ROUND_FLOOR
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiClientError(RuntimeError):
    pass


class KalshiClient:
    def __init__(self) -> None:
        self.api_key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
        self.private_key_pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "").strip()

        env = os.environ.get("KALSHI_ENV", "demo").strip().lower()
        base_url = os.environ.get("KALSHI_BASE_URL", "").strip()
        if not base_url:
            if env == "prod":
                base_url = "https://external-api.kalshi.com/trade-api/v2"
            else:
                base_url = "https://external-api.demo.kalshi.co/trade-api/v2"

        self.base_url = base_url.rstrip("/")
        self.subaccount = int(os.environ.get("KALSHI_SUBACCOUNT", "0"))
        self.exchange_index = int(os.environ.get("KALSHI_EXCHANGE_INDEX", "0"))

        self._private_key = None

    def ready(self) -> bool:
        return bool(self.api_key_id and self.private_key_pem)

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key

        if not self.api_key_id:
            raise KalshiClientError("Missing KALSHI_API_KEY_ID.")

        if not self.private_key_pem:
            raise KalshiClientError("Missing KALSHI_PRIVATE_KEY_PEM.")

        # Environment files cannot safely contain a literal multiline value.
        # Store the PEM on one line with literal \n separators; single-quoting
        # the value preserves them in both python-dotenv and systemd.
        pem = self.private_key_pem.replace("\\n", "\n").encode("utf-8")
        try:
            self._private_key = serialization.load_pem_private_key(
                pem,
                password=None,
                backend=default_backend(),
            )
        except (TypeError, ValueError) as exc:
            raise KalshiClientError(
                "KALSHI_PRIVATE_KEY_PEM is not a valid unencrypted PEM private key."
            ) from exc
        return self._private_key

    def _timestamp_ms(self) -> str:
        return str(int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))

    def _signature(self, method: str, endpoint: str, timestamp: str) -> str:
        private_key = self._load_private_key()
        full_path = urlparse(self.base_url + endpoint).path
        path_without_query = full_path.split("?")[0]
        message = f"{timestamp}{method.upper()}{path_without_query}".encode("utf-8")

        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _headers(self, method: str, endpoint: str) -> dict[str, str]:
        timestamp = self._timestamp_ms()
        signature = self._signature(method, endpoint, timestamp)

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        headers = self._headers(method, endpoint)
        url = self.base_url + endpoint

        response = requests.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            timeout=timeout,
        )

        if response.status_code >= 400:
            raise KalshiClientError(
                f"Kalshi {method.upper()} {endpoint} failed: "
                f"{response.status_code} {response.text}"
            )

        if not response.text:
            return {}

        return response.json()

    def place_yes_buy(
        self,
        *,
        ticker: str,
        spend_up_to_dollars: float,
        mode: str,
        aggressive_buy_price: str = "0.9900",
    ) -> dict[str, Any]:
        return self.place_outcome_buy(
            ticker=ticker,
            outcome_side="yes",
            spend_up_to_dollars=spend_up_to_dollars,
            mode=mode,
            aggressive_buy_price=aggressive_buy_price,
        )

    def place_outcome_buy(
        self,
        *,
        ticker: str,
        outcome_side: str,
        spend_up_to_dollars: float,
        mode: str,
        aggressive_buy_price: str = "0.9900",
    ) -> dict[str, Any]:
        count = "1.00" if mode == "test" else self._count_from_spend(
            spend_up_to_dollars,
            aggressive_buy_price,
        )
        outcome_price = Decimal(str(aggressive_buy_price))
        book_side = "bid" if outcome_side == "yes" else "ask"
        book_price = (
            outcome_price
            if outcome_side == "yes"
            else Decimal("1") - outcome_price
        )

        payload = {
            "ticker": ticker,
            "client_order_id": f"cmd-{uuid.uuid4()}",
            "side": book_side,
            "count": count,
            "price": format(book_price, "f"),
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "cancel_order_on_pause": True,
            "reduce_only": False,
            "subaccount": self.subaccount,
            "exchange_index": self.exchange_index,
        }

        result = self._request("POST", "/portfolio/events/orders", json_body=payload)
        if outcome_side == "no" and result.get("average_fill_price") not in (None, ""):
            result = dict(result)
            result["average_fill_price"] = format(
                Decimal("1") - Decimal(str(result["average_fill_price"])), "f"
            )
        result["outcome_side"] = outcome_side
        return result

    def sell_yes_position(
        self,
        *,
        ticker: str,
        mode: str,
        aggressive_sell_price: str = "0.0100",
    ) -> dict[str, Any]:
        return self.sell_outcome_position(
            ticker=ticker,
            outcome_side="yes",
            mode=mode,
            aggressive_sell_price=aggressive_sell_price,
        )

    def sell_outcome_position(
        self,
        *,
        ticker: str,
        outcome_side: str,
        mode: str,
        aggressive_sell_price: str = "0.0100",
    ) -> dict[str, Any]:
        position = self.get_outcome_position(ticker, outcome_side)
        if position <= Decimal("0"):
            raise KalshiClientError(
                f"No {outcome_side.upper()} position found for {ticker}."
            )

        if mode == "test":
            count = min(position, Decimal("1")).quantize(Decimal("0.01"))
        else:
            count = position.quantize(Decimal("0.01"))

        outcome_price = Decimal(str(aggressive_sell_price))
        book_side = "ask" if outcome_side == "yes" else "bid"
        book_price = (
            outcome_price
            if outcome_side == "yes"
            else Decimal("1") - outcome_price
        )

        payload = {
            "ticker": ticker,
            "client_order_id": f"cmd-{uuid.uuid4()}",
            "side": book_side,
            "count": format(count, "f"),
            "price": format(book_price, "f"),
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "cancel_order_on_pause": True,
            "reduce_only": True,
            "subaccount": self.subaccount,
            "exchange_index": self.exchange_index,
        }

        return self._request("POST", "/portfolio/events/orders", json_body=payload)

    def get_yes_position(self, ticker: str) -> Decimal:
        return self.get_outcome_position(ticker, "yes")

    def get_outcome_position(self, ticker: str, outcome_side: str) -> Decimal:
        query = urlencode(
            {
                "ticker": ticker,
                "count_filter": "position",
                "subaccount": self.subaccount,
            }
        )
        data = self._request("GET", f"/portfolio/positions?{query}")
        positions = data.get("market_positions", [])

        for position in positions:
            if position.get("ticker") == ticker:
                raw = position.get("position_fp", "0")
                value = Decimal(str(raw))
                directional = value if outcome_side == "yes" else -value
                return max(directional, Decimal("0"))

        return Decimal("0")

    def cancel_order(self, order_id: str, ticker: str | None = None) -> dict[str, Any]:
        endpoint = f"/portfolio/events/orders/{order_id}"
        params: dict[str, Any] = {
            "subaccount": self.subaccount,
            "exchange_index": self.exchange_index,
        }
        return self._request("DELETE", endpoint + "?" + urlencode(params))

    def get_open_orders(self) -> list[dict[str, Any]]:
        orders: list[dict[str, Any]] = []
        cursor = ""
        while True:
            params: dict[str, Any] = {
                "status": "resting",
                "limit": 1000,
                "subaccount": self.subaccount,
            }
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", "/portfolio/orders?" + urlencode(params))
            page = data.get("orders", [])
            if isinstance(page, list):
                orders.extend(order for order in page if isinstance(order, dict))
            cursor = str(data.get("cursor", "")).strip()
            if not cursor:
                return orders

    def cancel_all_open_orders(self) -> dict[str, Any]:
        canceled: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for order in self.get_open_orders():
            order_id = str(order.get("order_id", "")).strip()
            if not order_id:
                continue
            try:
                result = self.cancel_order(order_id)
                canceled.append({"order_id": order_id, "result": result})
            except Exception as exc:
                errors.append({"order_id": order_id, "error": str(exc)})
        return {"canceled": canceled, "errors": errors}

    def _count_from_spend(self, spend_up_to_dollars: float, price: str) -> str:
        spend = Decimal(str(spend_up_to_dollars))
        px = Decimal(str(price))
        if spend <= 0:
            raise KalshiClientError("spend_up_to_dollars must be positive.")
        if px <= 0:
            raise KalshiClientError("aggressive_buy_price must be positive.")

        count = (spend / px).to_integral_value(rounding=ROUND_FLOOR)
        if count < 1:
            count = Decimal("1")

        return f"{count}.00"
