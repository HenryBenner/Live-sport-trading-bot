import asyncio
import json
import threading
from decimal import Decimal

from server.aggressive_buyer import AggressiveBuyer
from server.audit_log import AuditLogger
from server.command_router import CommandRouter
from server.config_loader import ConfigError, validate_config
from server.open_order_manager import OpenOrderManager
from server.runtime_state import RuntimeState


class FakeKalshi:
    base_url = "https://example.invalid"
    subaccount = 0
    exchange_index = 0

    def ready(self):
        return False

    def _headers(self, method, endpoint):
        return {}


def event_config():
    return {
        "profile_name": "Test match",
        "event_name": "A vs B",
        "event_ticker": "EVENT-1",
        "event_url": "https://kalshi.com/events/EVENT-1",
        "mode": "paper",
        "commands": {
            "A": {
                "label": "A wins",
                "action": "buy",
                "market_ticker": "EVENT-1-A",
                "market_url": "https://kalshi.com/markets/EVENT-1-A",
                "line_or_prop": "A to win",
                "side": "yes",
                "spend_up_to_dollars": 50,
                "enabled": True,
            },
            "M": {
                "label": "Sell last",
                "action": "sell_last_market_position",
                "enabled": True,
            },
            "K": {"label": "Kill", "action": "kill_switch", "enabled": True},
        },
    }


def make_router(tmp_path, monkeypatch):
    monkeypatch.setenv("DEFAULT_MARKET_COST_CAP_DOLLARS", "100")
    monkeypatch.setenv("EVENT_COST_CAP_DOLLARS", "200")
    runtime = RuntimeState(tmp_path / "state.json", event_id="EVENT-1")
    router = CommandRouter(
        config=event_config(),
        kalshi=FakeKalshi(),
        open_orders=OpenOrderManager(),
        runtime=runtime,
        audit=AuditLogger(tmp_path / "audit.jsonl"),
    )
    return router, runtime


def test_block_and_limits_persist_for_same_event(tmp_path, monkeypatch):
    router, runtime = make_router(tmp_path, monkeypatch)

    response = asyncio.run(router.route("/block A"))
    assert response["type"] == "control"
    assert runtime.is_blocked("A")

    asyncio.run(router.route("/limit market A 40"))
    runtime.record_spend("A", Decimal("30"))

    reloaded = RuntimeState(tmp_path / "state.json", event_id="EVENT-1")
    assert reloaded.is_blocked("A")
    assert reloaded.spent_event() == Decimal("30.0000")
    assert reloaded.spent_market("A") == Decimal("30.0000")
    assert reloaded.limit_override("market", "A") == (True, Decimal("40.0000"))


def test_new_event_gets_a_fresh_session(tmp_path):
    path = tmp_path / "state.json"
    first = RuntimeState(path, event_id="EVENT-1")
    first.block(["A"])
    first_id = first.session_id

    second = RuntimeState(path, event_id="EVENT-2")
    assert second.session_id != first_id
    assert not second.is_blocked("A")
    assert second.spent_event() == Decimal("0")


def test_kill_state_blocks_trades_until_explicit_reset(tmp_path, monkeypatch):
    router, runtime = make_router(tmp_path, monkeypatch)

    killed = asyncio.run(router.route("K"))
    assert killed["type"] == "kill_switch"
    assert runtime.kill_active()
    assert "Kill switch is active" in asyncio.run(router.route("A"))["message"]

    reset = asyncio.run(router.route("/reset kill"))
    assert reset["type"] == "control"
    assert not runtime.kill_active()


def test_already_canceled_sweep_never_calls_kalshi():
    buyer = AggressiveBuyer(FakeKalshi())
    buyer._request = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("Kalshi should not be called")
    )
    cancel = threading.Event()
    cancel.set()

    result = buyer.sweep(
        ticker="EVENT-1-A",
        spend_cap_dollars=10,
        cancel_event=cancel,
    )

    assert result["stop_reason"] == "canceled_by_control_command"
    assert result["attempts"] == 0


def test_config_requires_exact_urls_and_prop_text():
    config = event_config()
    del config["commands"]["A"]["line_or_prop"]
    try:
        validate_config(config)
    except ConfigError as exc:
        assert "line_or_prop" in str(exc)
    else:
        raise AssertionError("Config without line_or_prop should fail validation")


def test_audit_log_is_json_lines(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLogger(path).write("test", session_id="session-1", value=2)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["event"] == "test"
    assert record["session_id"] == "session-1"
