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
        self.private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()

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
        return bool(self.api_key_id and self.private_key_path)

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key

        if not self.api_key_id:
            raise KalshiClientError("Missing KALSHI_API_KEY_ID.")

        if not self.private_key_path:
            raise KalshiClientError("Missing KALSHI_PRIVATE_KEY_PATH.")

        with open(self.private_key_path, "rb") as f:
            self._private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend(),
            )
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
        count = "1.00" if mode == "test" else self._count_from_spend(
            spend_up_to_dollars,
            aggressive_buy_price,
        )

        payload = {
            "ticker": ticker,
            "client_order_id": f"cmd-{uuid.uuid4()}",
            "side": "bid",
            "count": count,
            "price": aggressive_buy_price,
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": False,
            "cancel_order_on_pause": True,
            "reduce_only": False,
            "subaccount": self.subaccount,
            "exchange_index": self.exchange_index,
        }

        return self._request("POST", "/portfolio/events/orders", json_body=payload)

    def sell_yes_position(
        self,
        *,
        ticker: str,
        mode: str,
        aggressive_sell_price: str = "0.0100",
    ) -> dict[str, Any]:
        yes_position = self.get_yes_position(ticker)
        if yes_position <= Decimal("0"):
            raise KalshiClientError(f"No YES position found for {ticker}.")

        if mode == "test":
            count = min(yes_position, Decimal("1")).quantize(Decimal("0.01"))
        else:
            count = yes_position.quantize(Decimal("0.01"))

        payload = {
            "ticker": ticker,
            "client_order_id": f"cmd-{uuid.uuid4()}",
            "side": "ask",
            "count": format(count, "f"),
            "price": aggressive_sell_price,
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
                if value > 0:
                    return value
                return Decimal("0")

        return Decimal("0")

    def cancel_order(self, order_id: str, ticker: str | None = None) -> dict[str, Any]:
        endpoint = f"/portfolio/events/orders/{order_id}"
        params: dict[str, Any] = {
            "subaccount": self.subaccount,
            "exchange_index": self.exchange_index,
        }
        if ticker:
            params["market_ticker"] = ticker

        return self._request("DELETE", endpoint + "?" + urlencode(params))

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
