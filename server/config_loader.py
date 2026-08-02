from __future__ import annotations

import json
from pathlib import Path
from typing import Any


VALID_MODES = {"paper", "test", "live"}
VALID_ACTIONS = {"buy", "sell_last_market_position", "kill_switch"}


class ConfigError(ValueError):
    pass


def load_config(path: str | Path = "config/active.json") -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Config must be a JSON object.")

    mode = config.get("mode")
    if mode not in VALID_MODES:
        raise ConfigError(f"mode must be one of {sorted(VALID_MODES)}.")

    for field in ("profile_name", "event_name", "event_ticker", "event_url"):
        if config.get(field) in (None, ""):
            raise ConfigError(f"Config missing required field: {field}")

    if str(config["event_ticker"]).lower() not in str(config["event_url"]).lower():
        raise ConfigError("event_url must contain the exact event_ticker.")

    commands = config.get("commands")
    if not isinstance(commands, dict) or not commands:
        raise ConfigError("commands must be a non-empty object.")

    if "K" not in commands:
        raise ConfigError("Kill switch command K is required.")

    buy_tickers: set[str] = set()
    for key, command in commands.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or key != key.strip()
            or key.startswith("/")
        ):
            raise ConfigError(
                "Command key must be non-empty, have no surrounding whitespace, "
                f"and must not start with '/': {key!r}"
            )
        if key != key.upper():
            raise ConfigError(f"Command key must be uppercase: {key!r}")

        if not isinstance(command, dict):
            raise ConfigError(f"Command {key} must be an object.")

        action = command.get("action")
        if action not in VALID_ACTIONS:
            raise ConfigError(f"Command {key} has invalid action: {action!r}")

        if command.get("enabled") is None:
            raise ConfigError(f"Command {key} must include enabled true or false.")

        if action == "buy":
            _require(command, "label", key)
            _require(command, "market_ticker", key)
            _require(command, "market_url", key)
            _require(command, "line_or_prop", key)
            _require(command, "side", key)
            _require(command, "spend_up_to_dollars", key)

            if command["side"] not in {"yes", "no"}:
                raise ConfigError(f"Command {key} side must be 'yes' or 'no'.")

            try:
                spend = float(command["spend_up_to_dollars"])
            except (TypeError, ValueError):
                raise ConfigError(f"Command {key} spend_up_to_dollars must be numeric.")

            if spend <= 0:
                raise ConfigError(f"Command {key} spend_up_to_dollars must be positive.")

            ticker = str(command["market_ticker"])
            market_url = str(command["market_url"])
            if ticker in buy_tickers:
                raise ConfigError(
                    f"Each buy command must use a unique market_ticker: {ticker}"
                )
            buy_tickers.add(ticker)
            if ticker.lower() not in market_url.lower():
                raise ConfigError(
                    f"Command {key} market_url must contain its exact market_ticker."
                )

        if action == "sell_last_market_position":
            _require(command, "label", key)

        if action == "kill_switch":
            _require(command, "label", key)


def _require(command: dict[str, Any], field: str, key: str) -> None:
    if field not in command or command[field] in (None, ""):
        raise ConfigError(f"Command {key} missing required field: {field}")


def profile_summary(config: dict[str, Any]) -> dict[str, Any]:
    commands = []
    for key, command in config["commands"].items():
        commands.append(
            {
                "key": key,
                "label": command.get("label", ""),
                "action": command.get("action", ""),
                "enabled": bool(command.get("enabled")),
                "market_ticker": command.get("market_ticker", ""),
                "market_url": command.get("market_url", ""),
                "line_or_prop": command.get("line_or_prop", ""),
                "side": command.get("side", ""),
                "spend_up_to_dollars": command.get("spend_up_to_dollars"),
            }
        )

    return {
        "profile_name": config.get("profile_name", ""),
        "sport": config.get("sport", ""),
        "event_name": config.get("event_name", ""),
        "event_ticker": config.get("event_ticker", ""),
        "event_url": config.get("event_url", ""),
        "mode": config.get("mode", ""),
        "commands": sorted(commands, key=lambda x: x["key"]),
    }
