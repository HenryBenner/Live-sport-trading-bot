from __future__ import annotations

import asyncio
import json
import os
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
                print("Connected.")

                greeting = await ws.recv()
                print_pretty(greeting)

                while True:
                    key = input("> ").strip()
                    if not key:
                        continue

                    if key.lower() in {"quit", "exit"}:
                        print("Exiting.")
                        return

                    if len(key) != 1:
                        print("Use one-character commands only.")
                        continue

                    message = {
                        "type": "command",
                        "token": token,
                        "key": key,
                        "timestamp": now_iso(),
                    }

                    await ws.send(json.dumps(message))
                    response = await ws.recv()
                    print_pretty(response)

        except KeyboardInterrupt:
            print("\nExiting.")
            return
        except Exception as exc:
            print(f"Connection error: {exc}")
            print("Reconnecting in 2 seconds ...")
            await asyncio.sleep(2)


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
        print("Commands:")
        for command in profile.get("commands", []):
            enabled = "on" if command.get("enabled") else "off"
            print(f"  {command.get('key')}  {command.get('label')}  [{enabled}]")
        print()
        return

    if msg_type in {"result", "error", "kill_switch", "pong"}:
        print(data.get("message", data))
        if "kalshi" in data:
            kalshi = data["kalshi"]
            print("Kalshi:", json.dumps(kalshi, indent=2))
        return

    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    asyncio.run(run_sender())
