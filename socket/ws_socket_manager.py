# socket/ws_socket_manager.py
import os
import asyncio
import random
import socket
from typing import Dict, Optional

from dotenv import load_dotenv
from sock import start  # starts a websockets server and runs forever

load_dotenv()


class WSSocketManager:
    """
    Manages per-agent WebSocket servers.
    - If a server is already running for an agent_id, returns its URL.
    - If the requested port is busy, retries on another free port in a WS-only range.
    """

    # Keep a simple in-process registry: agent_id (or url) -> info
    _registry: Dict[str, Dict] = {}
    _lock = asyncio.Lock()

    # Dedicated WS port range (avoid overlap with RTP). Override via env.
    _WS_PORT_MIN = int(os.getenv("WS_PORT_MIN", "12100"))
    _WS_PORT_MAX = int(os.getenv("WS_PORT_MAX", "13000"))

    @staticmethod
    def _parse(ws_url: str) -> tuple[str, int]:
        # "ws://host:port"
        parts = ws_url.split(":")
        host = parts[1][2:]  # strip leading "//"
        port = int(parts[2])
        return host, port

    @staticmethod
    def _port_free(host: str, port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            try:
                s.close()
            except Exception:
                pass

    @classmethod
    async def _pick_free_port(cls, host: str, retries: int = 20) -> int:
        for _ in range(retries):
            candidate = random.randint(cls._WS_PORT_MIN, cls._WS_PORT_MAX)
            if cls._port_free(host, candidate):
                return candidate
        # Fallback to linear scan if random tries failed
        for p in range(cls._WS_PORT_MIN, cls._WS_PORT_MAX + 1):
            if cls._port_free(host, p):
                return p
        raise RuntimeError("No free WS ports available in configured range")

    @classmethod
    async def create(cls, ws_url: str, *, agent_id: Optional[str] = None) -> str:
        """
        Get-or-create a WebSocket server.
        - If agent_id provided and a server exists, return existing URL.
        - Otherwise try to start on ws_url's port; if busy, pick a free one.
        Returns the (possibly adjusted) ws:// URL actually used.
        """
        host, requested_port = cls._parse(ws_url)

        async with cls._lock:
            # If we already have one for this agent_id, return the existing URL
            if agent_id and agent_id in cls._registry:
                info = cls._registry[agent_id]
                task: asyncio.Task = info["task"]
                if not task.done() and not task.cancelled():
                    # Already running
                    return info["url"]

            # Choose a port: prefer requested if free, else pick a free one
            if cls._port_free(host, requested_port):
                port = requested_port
            else:
                port = await cls._pick_free_port(host)

            final_url = f"ws://{host}:{port}"

            # Start the WS server in background (runs forever)
            async def _runner():
                await start(host, port)  # blocks forever inside websockets.serve

            task = asyncio.create_task(_runner(), name=f"ws@{host}:{port}")

            # Store by agent_id if provided, else by URL (back-compat path)
            key = agent_id if agent_id else final_url
            cls._registry[key] = {"url": final_url, "host": host, "port": port, "task": task}
            return final_url

    @classmethod
    async def stop(cls, agent_id: str) -> None:
        """
        Best-effort stop of a running WS server for this agent_id.
        (Actual graceful shutdown would require sock.py to expose a close/stop.)
        """
        async with cls._lock:
            info = cls._registry.pop(agent_id, None)
            if not info:
                return
            task: asyncio.Task = info["task"]
            try:
                task.cancel()
            except Exception:
                pass
