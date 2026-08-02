from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
from datetime import datetime, timezone
from typing import Any

import websockets
from dotenv import load_dotenv
from websockets.server import WebSocketServerProtocol

from .command_router import CommandRouter
from .audit_log import AuditLogger
from .config_loader import ConfigError, load_config, profile_summary
from .kalshi_client import KalshiClient
from .open_order_manager import OpenOrderManager
from .runtime_state import RuntimeState


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

        runtime_path = os.environ.get(
            "RUNTIME_STATE_PATH", "config/runtime_state.json"
        )
        audit_path = os.environ.get("AUDIT_LOG_PATH", "logs/commands.jsonl")
        event_id = str(
            self.config.get("event_ticker")
            or self.config.get("event_name")
            or self.config.get("profile_name")
        )
        self.runtime = RuntimeState(runtime_path, event_id=event_id)
        self.audit = AuditLogger(audit_path)

        self.open_orders = OpenOrderManager()
        self.kalshi = KalshiClient()
        self.router = CommandRouter(
            config=self.config,
            kalshi=self.kalshi,
            open_orders=self.open_orders,
            runtime=self.runtime,
            audit=self.audit,
        )

    async def handler(self, websocket: WebSocketServerProtocol) -> None:
        print(f"[{now_iso()}] client connected")
        if not await self._authenticate(websocket):
            return

        profile = profile_summary(self.config)
        profile["runtime"] = self.router.status_response()
        await websocket.send(
            json.dumps(
                {
                    "type": "profile",
                    "message": "Connected to Kalshi command server.",
                    "profile": profile,
                }
            )
        )

        send_lock = asyncio.Lock()
        async for raw_message in websocket:
            asyncio.create_task(
                self._handle_and_send(websocket, send_lock, raw_message)
            )

    async def _authenticate(self, websocket: WebSocketServerProtocol) -> bool:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            data = json.loads(raw)
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await websocket.close(code=4001, reason="Authentication required")
            return False

        supplied = str(data.get("token", ""))
        if data.get("type") != "auth" or not secrets.compare_digest(
            supplied, self.control_token
        ):
            await websocket.close(code=4001, reason="Unauthorized")
            return False
        return True

    async def _handle_and_send(
        self,
        websocket: WebSocketServerProtocol,
        send_lock: asyncio.Lock,
        raw_message: str,
    ) -> None:
        response = await self.handle_message(raw_message)
        try:
            async with send_lock:
                await websocket.send(json.dumps(response))
        except Exception:
            self.audit.write("response_delivery_failed", response=response)

    async def handle_message(self, raw_message: str) -> dict[str, Any]:
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            return {"type": "error", "message": "Invalid JSON."}

        msg_type = data.get("type")
        if msg_type == "ping":
            return {"type": "pong", "timestamp": now_iso()}

        if msg_type != "command":
            return {"type": "error", "message": f"Unsupported message type: {msg_type}"}

        key = str(data.get("key", "")).strip()
        command_id = str(data.get("command_id", "")).strip()
        print(f"[{now_iso()}] command received: {key}")

        self.audit.write(
            "command_received",
            session_id=self.runtime.session_id,
            command_id=command_id,
            command=key,
        )

        response = await self.router.route(key)
        if command_id:
            response["command_id"] = command_id

        status = response.get("status") or response.get("type")
        print(f"[{now_iso()}] command result: {key} {status}")

        self.audit.write(
            "command_result",
            session_id=self.runtime.session_id,
            command_id=command_id,
            command=key,
            status=status,
            response=response,
        )

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
