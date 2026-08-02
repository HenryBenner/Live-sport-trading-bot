from __future__ import annotations

import json
import os
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


class RuntimeStateError(ValueError):
    pass


def parse_optional_money(value: Any, *, name: str) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeStateError(f"{name} must be a positive dollar amount or blank.") from exc
    if not amount.is_finite() or amount <= ZERO:
        raise RuntimeStateError(f"{name} must be a positive dollar amount or blank.")
    return amount


def money_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.0001")), "f")


class RuntimeState:
    """Persistent event-session controls and all-in spending totals."""

    def __init__(self, path: str | Path, *, event_id: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.data = self._load_or_create(event_id)

    def _new(self, event_id: str) -> dict[str, Any]:
        return {
            "version": 1,
            "session_id": str(uuid.uuid4()),
            "event_id": event_id,
            "blocked_keys": [],
            "kill_switch_active": False,
            "limit_overrides": {
                "event": {},
                "market": {},
                "press": {},
            },
            "spent": {"event_all_in_dollars": "0.0000", "markets": {}},
        }

    def _load_or_create(self, event_id: str) -> dict[str, Any]:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeStateError(
                    f"Runtime state is unreadable and was not reset: {self.path}"
                ) from exc
            if isinstance(data, dict) and data.get("event_id") == event_id:
                return data

        data = self._new(event_id)
        self._save_data(data)
        return data

    def _save_data(self, data: dict[str, Any]) -> None:
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, self.path)

    def save(self) -> None:
        with self._lock:
            self._save_data(self.data)

    @property
    def session_id(self) -> str:
        return str(self.data["session_id"])

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return key in self.data.get("blocked_keys", [])

    def block(self, keys: list[str]) -> None:
        with self._lock:
            blocked = set(self.data.get("blocked_keys", []))
            blocked.update(keys)
            self.data["blocked_keys"] = sorted(blocked)
            self.save()

    def unblock(self, keys: list[str]) -> None:
        with self._lock:
            blocked = set(self.data.get("blocked_keys", []))
            blocked.difference_update(keys)
            self.data["blocked_keys"] = sorted(blocked)
            self.save()

    def kill(self) -> None:
        with self._lock:
            self.data["kill_switch_active"] = True
            self.save()

    def reset_kill(self) -> None:
        with self._lock:
            self.data["kill_switch_active"] = False
            self.save()

    def kill_active(self) -> bool:
        with self._lock:
            return bool(self.data.get("kill_switch_active"))

    def set_limit_override(
        self, scope: str, key: str | None, amount: Decimal | None
    ) -> None:
        if scope not in {"event", "market", "press"}:
            raise RuntimeStateError(f"Unsupported limit scope: {scope}")
        with self._lock:
            overrides = self.data.setdefault("limit_overrides", {}).setdefault(scope, {})
            override_key = "value" if scope == "event" else str(key)
            overrides[override_key] = money_text(amount)
            self.save()

    def limit_override(self, scope: str, key: str | None = None) -> tuple[bool, Decimal | None]:
        with self._lock:
            overrides = self.data.get("limit_overrides", {}).get(scope, {})
            override_key = "value" if scope == "event" else str(key)
            if override_key not in overrides:
                return False, None
            value = overrides[override_key]
            return True, parse_optional_money(value, name=f"{scope} limit")

    def spent_event(self) -> Decimal:
        with self._lock:
            return Decimal(str(self.data.get("spent", {}).get("event_all_in_dollars", "0")))

    def spent_market(self, key: str) -> Decimal:
        with self._lock:
            markets = self.data.get("spent", {}).get("markets", {})
            return Decimal(str(markets.get(key, "0")))

    def record_spend(self, key: str, all_in_dollars: Decimal) -> None:
        if all_in_dollars < ZERO:
            raise RuntimeStateError("Recorded spending cannot be negative.")
        with self._lock:
            spent = self.data.setdefault("spent", {})
            event_total = Decimal(str(spent.get("event_all_in_dollars", "0")))
            markets = spent.setdefault("markets", {})
            market_total = Decimal(str(markets.get(key, "0")))
            spent["event_all_in_dollars"] = money_text(event_total + all_in_dollars)
            markets[key] = money_text(market_total + all_in_dollars)
            self.save()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self.data))
