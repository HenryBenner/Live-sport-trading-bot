from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from typing import Any

import websockets
from dotenv import load_dotenv
from websockets.server import WebSocketServerProtocol

from .command_router import CommandRouter
from .config_loader import ConfigError, load_config, profile_summary
from .kalshi_client import KalshiClient
from .open_order_manager import OpenOrderManager


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommandServer:
    def __init__(self) -> None:
        load_dotenv()

        self.host = os.environ.get("WS_HOST", "0.0.0.0")
        self.port = int(os.environ.get("WS_PORT", "8765"))
        self.control_token = os.environ.get("CONTROL_TOKEN", "")

        if not self.control_token:
            raise RuntimeError("CONTROL_TOKEN is required in .env.")

        config_path = os.environ.get("CONFIG_PATH", "config/active.json")
        self.config = load_config(config_path)

        self.open_orders = OpenOrderManager()
        self.kalshi = KalshiClient()
        self.router = CommandRouter(
            config=self.config,
            kalshi=self.kalshi,
            open_orders=self.open_orders,
        )

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        print(f"[{now_iso()}] client connected")

        await websocket.send(
            json.dumps(
                {
                    "type": "profile",
                    "message": "Connected to Kalshi command server.",
                    "profile": profile_summary(self.config),
                }
            )
        )

        async for raw_message in websocket:
            response = await self.handle_message(raw_message)
            await websocket.send(json.dumps(response))

    async def handle_message(self, raw_message: str) -> dict[str, Any]:
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            return {"type": "error", "message": "Invalid JSON."}

        if data.get("token") != self.control_token:
            return {"type": "error", "message": "Unauthorized."}

        msg_type = data.get("type")
        if msg_type == "ping":
            return {"type": "pong", "timestamp": now_iso()}

        if msg_type != "command":
            return {"type": "error", "message": f"Unsupported message type: {msg_type}"}

        key = str(data.get("key", "")).strip()
        print(f"[{now_iso()}] command received: {key}")

        response = await self.router.route(key)

        status = response.get("status") or response.get("type")
        print(f"[{now_iso()}] command result: {key} {status}")

        return response

    async def run(self) -> None:
        print(f"Starting Kalshi command server on {self.host}:{self.port}")
        print(f"Profile: {self.config.get('profile_name')}")
        print(f"Mode: {self.config.get('mode')}")

        stop = asyncio.Future()

        def _stop(*_: object) -> None:
            if not stop.done():
                stop.set_result(None)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except NotImplementedError:
                pass

        async with websockets.serve(self.handler, self.host, self.port):
            await stop


def main() -> None:
    try:
        server = CommandServer()
        asyncio.run(server.run())
    except ConfigError as exc:
        print(f"Config error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
