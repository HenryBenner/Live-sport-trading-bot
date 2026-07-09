from __future__ import annotations

from typing import Any

from .kalshi_client import KalshiClient


def handle_buy(
    *,
    mode: str,
    command_key: str,
    command: dict[str, Any],
    config: dict[str, Any],
    kalshi: KalshiClient,
) -> dict[str, Any]:
    label = command.get("label", "")
    ticker = command.get("market_ticker", "")
    spend = float(command.get("spend_up_to_dollars", 0))
    buy_price = config.get("aggressive_buy_price", "0.9900")

    if mode == "paper":
        return {
            "type": "result",
            "mode": mode,
            "key": command_key,
            "status": "paper_ok",
            "market_ticker": ticker,
            "message": f"Would buy {label}. No Kalshi order placed.",
        }

    result = kalshi.place_yes_buy(
        ticker=ticker,
        spend_up_to_dollars=spend,
        mode=mode,
        aggressive_buy_price=buy_price,
    )

    return {
        "type": "result",
        "mode": mode,
        "key": command_key,
        "status": "submitted",
        "market_ticker": ticker,
        "kalshi": result,
        "message": f"Submitted {mode} buy for {label}.",
    }


def handle_sell_last(
    *,
    mode: str,
    command_key: str,
    last_market_ticker: str | None,
    last_label: str | None,
    config: dict[str, Any],
    kalshi: KalshiClient,
) -> dict[str, Any]:
    if not last_market_ticker:
        return {
            "type": "error",
            "mode": mode,
            "key": command_key,
            "message": "No last bought market is stored in memory.",
        }

    sell_price = config.get("aggressive_sell_price", "0.0100")

    if mode == "paper":
        return {
            "type": "result",
            "mode": mode,
            "key": command_key,
            "status": "paper_ok",
            "market_ticker": last_market_ticker,
            "message": f"Would sell current Kalshi YES position for {last_label or last_market_ticker}.",
        }

    result = kalshi.sell_yes_position(
        ticker=last_market_ticker,
        mode=mode,
        aggressive_sell_price=sell_price,
    )

    return {
        "type": "result",
        "mode": mode,
        "key": command_key,
        "status": "submitted",
        "market_ticker": last_market_ticker,
        "kalshi": result,
        "message": f"Submitted {mode} sell for {last_label or last_market_ticker}.",
    }
