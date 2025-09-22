# socket/main.py
from fastapi import FastAPI, status, Response, Request
import asyncio
import os
import random
import traceback
import websockets

from ws_socket_manager import WSSocketManager
from socket_store import SocketStorePg

api = FastAPI()
sock_store = SocketStorePg()


@api.put("/init/{agent_id}")
async def init(agent_id: str = ""):
    """
    Get-or-create a per-agent WebSocket server URL.

    Behavior:
    - If an existing mapping for this agent_id is found (agent assumed READY),
      reuse and return the SAME ws:// URL (do NOT insert a new row).
    - Otherwise, create a new WS server with a free port, then persist the URL.
    """
    if not agent_id:
        return Response(
            content=None,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers={"Access-Control-Allow-Origin": "*"},
        )


    # 1) Check the latest row for this agent_id by created_at
    latest = sock_store.get_latest_for_agent(agent_id)  # -> Optional[tuple[str, str]] (status, url)
    if latest:
        latest_status, existing_url = latest
        if latest_status in ("READY", "INPROGRESS"):

            try:
                final_url = await WSSocketManager.create(existing_url, agent_id=agent_id)
                if final_url != existing_url:
                    # Port changed (old was occupied). Persist the actual bound URL.
                    sock_store.add_url(agent_id, final_url)
                return Response(
                    content=final_url,
                    status_code=status.HTTP_200_OK,
                    headers={"Access-Control-Allow-Origin": "*"},
                )
            except Exception:
                traceback.print_exc()
                return Response(
                    content="Failed to ensure websocket",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    headers={"Access-Control-Allow-Origin": "*"},
                )

    # 2) No existing URL: create a new one on a free port
    host = get_ws_host()
    port = get_ws_port()  # candidate; manager will adjust if occupied
    requested_url = f"ws://{host}:{port}"

    try:
        final_url = await WSSocketManager.create(requested_url, agent_id=agent_id)
        # Persist the ACTUAL bound URL
        url_host, url_port = _split_ws_host_port(final_url)
        sock_store.add(agent_id, url_host, url_port)

        return Response(
            content=final_url,
            status_code=status.HTTP_201_CREATED,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception:
        traceback.print_exc()
        return Response(
            content="Failed to create websocket",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"Access-Control-Allow-Origin": "*"},
        )


@api.post("/transcription/{agent_id}")
async def send_transcription(req: Request, agent_id: str):
    """
    Reads raw request body and forwards it to the per-agent WebSocket URL.
    """
    try:
        ws_url = sock_store.get(agent_id)
        if not ws_url:
            return Response(
                content="WebSocket URL not found for agent_id",
                status_code=status.HTTP_404_NOT_FOUND,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        payload = await req.body()
        text = payload.decode("utf-8", errors="ignore")

        # Async, non-blocking WebSocket client
        async with websockets.connect(ws_url) as ws:
            await ws.send(text)

        print(f"Sent transcription to {ws_url}: {text[:200]}...")
        return Response(
            content=text,
            status_code=status.HTTP_200_OK,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    except Exception:
        traceback.print_exc()
        return Response(
            content="Error while sending transcription",
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"Access-Control-Allow-Origin": "*"},
        )


def get_ws_host() -> str:
    """
    Host to bind the per-agent WebSocket server on.
    Use WS_HOST env if set; defaults to localhost.
    """
    return os.getenv("WS_HOST", "localhost")


def get_ws_port() -> int:
    """
    Pick a candidate port from a dedicated WS range.
    The manager will retry/change it if occupied.
    """
    ws_min = int(os.getenv("WS_PORT_MIN", "12100"))
    ws_max = int(os.getenv("WS_PORT_MAX", "13000"))
    return random.randint(ws_min, ws_max)


def _split_ws_host_port(ws_url: str) -> tuple[str, int]:
    # "ws://host:port" -> ("host", port)
    parts = ws_url.split(":")
    host = parts[1][2:]  # strip leading "//"
    port = int(parts[2])
    return host, port
