from __future__ import annotations

from typing import Any

from .aggressive_buyer import AggressiveBuyer
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

    if mode == "paper":
        return {
            "type": "result",
            "mode": mode,
            "key": command_key,
            "status": "paper_ok",
            "market_ticker": ticker,
            "message": (
                f"Would aggressively sweep {label} up to ${spend:.2f}. "
                "No Kalshi order placed."
            ),
        }

    if mode == "test":
        result = kalshi.place_yes_buy(
            ticker=ticker,
            spend_up_to_dollars=spend,
            mode=mode,
            aggressive_buy_price=config.get("aggressive_buy_price", "0.9900"),
        )
        message = f"Submitted one-contract test buy for {label}."
    else:
        result = AggressiveBuyer(kalshi).sweep(
            ticker=ticker,
            spend_cap_dollars=spend,
            maximum_buy_price=config.get("aggressive_buy_price", "1.0000"),
            max_attempts=int(config.get("buy_retry_max_attempts", 100)),
            max_seconds=float(config.get("buy_retry_max_seconds", 10.0)),
            no_progress_limit=int(
                config.get("buy_retry_no_progress_limit", 20)
            ),
            retry_delay_seconds=float(
                config.get("buy_retry_delay_seconds", 0.05)
            ),
            error_limit=int(config.get("buy_retry_error_limit", 10)),
        )
        message = (
            f"Aggressive sweep finished for {label}: "
            f"{result.get('fill_count', '0')} contracts filled, "
            f"${result.get('contract_cost_dollars', '0')} contract cost, "
            f"stop={result.get('stop_reason', 'unknown')}."
        )

    return {
        "type": "result",
        "mode": mode,
        "key": command_key,
        "status": "submitted",
        "market_ticker": ticker,
        "kalshi": result,
        "message": message,
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
            "message": (
                "Would sell current Kalshi YES position for "
                f"{last_label or last_market_ticker}."
            ),
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
        "message": (
            f"Submitted {mode} sell for "
            f"{last_label or last_market_ticker}."
        ),
    }
