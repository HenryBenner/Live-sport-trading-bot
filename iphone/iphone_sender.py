from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import websockets


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_or_prompt(name: str, prompt: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return input(prompt).strip()


async def run_sender() -> None:
    url = env_or_prompt("COMMAND_WS_URL", "WebSocket URL, for example wss://your-vps.com/ws or ws://1.2.3.4:8765: ")
    token = env_or_prompt("CONTROL_TOKEN", "Control token: ")

    while True:
        try:
            print(f"Connecting to {url} ...")
            async with websockets.connect(url, ping_interval=10, ping_timeout=10) as ws:
                await ws.send(json.dumps({"type": "auth", "token": token}))
                print("Connected. Use /help to list controls.")
                receiver = asyncio.create_task(receive_messages(ws))

                try:
                    while True:
                        key = (await asyncio.to_thread(input, "> ")).strip()
                        if not key:
                            continue

                        if key.lower() in {"quit", "exit"}:
                            print("Exiting.")
                            return

                        if len(key) != 1 and not key.startswith("/"):
                            print("Use a one-character trade key or a /control command.")
                            continue

                        message = {
                            "type": "command",
                            "key": key,
                            "command_id": str(uuid.uuid4()),
                            "timestamp": now_iso(),
                        }

                        await ws.send(json.dumps(message))
                finally:
                    receiver.cancel()

        except KeyboardInterrupt:
            print("\nExiting.")
            return
        except Exception as exc:
            print(f"Connection error: {exc}")
            print("Reconnecting in 2 seconds ...")
            await asyncio.sleep(2)


async def receive_messages(ws) -> None:
    async for raw in ws:
        print_pretty(raw)


def print_pretty(raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(raw)
        return

    msg_type = data.get("type")

    if msg_type == "profile":
        profile = data.get("profile", {})
        print()
        print("Profile:", profile.get("profile_name", ""))
        print("Event:", profile.get("event_name", ""))
        print("Mode:", profile.get("mode", ""))
        print("Event ticker:", profile.get("event_ticker", ""))
        print("Commands:")
        for command in profile.get("commands", []):
            enabled = "on" if command.get("enabled") else "off"
            print(f"  {command.get('key')}  {command.get('label')}  [{enabled}]")
        print()
        return

    if msg_type in {"result", "error", "kill_switch", "pong", "control"}:
        print(data.get("message", data))
        if "kalshi" in data:
            kalshi = data["kalshi"]
            print("Kalshi:", json.dumps(kalshi, indent=2))
        return

    if msg_type in {"status", "commands"}:
        print()
        print(data.get("message", ""))
        print("Event:", data.get("event_name", ""))
        print("Mode:", data.get("mode", ""))
        print("Kill switch:", "ACTIVE" if data.get("kill_switch_active") else "off")
        event_cap_value = data.get("event_cap_dollars")
        event_cap = f"${event_cap_value}" if event_cap_value else "infinite"
        print(
            "Event spend:",
            f"${data.get('event_spent_all_in_dollars', '0')} / {event_cap}",
        )
        for command in data.get("commands", []):
            state = "BLOCKED" if command.get("blocked") else "ready"
            market_cap_value = command.get("market_cap_dollars")
            market_cap = (
                f"${market_cap_value}" if market_cap_value else "infinite"
            )
            print(
                f"  {command.get('key')}  {command.get('label')} | "
                f"{command.get('line_or_prop')} | {state} | "
                f"press ${command.get('press_cap_dollars')} | "
                f"market {market_cap} | spent ${command.get('spent_all_in_dollars')}"
            )
        print()
        return

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    asyncio.run(run_sender())
