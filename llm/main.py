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
    Get-or-create a per-call WebSocket server for this agent_id.
    - Uses WSSocketManager to ensure the port is free (with retry) and to reuse an existing WS if present.
    - Persists the final bound ws:// URL to DB ONLY after successful bind.
    """
    if not agent_id:
        return Response(
            content=None,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # Candidate URL (manager will keep if free or swap the port if busy)
    host = get_ws_host()
    port = get_ws_port()
    requested_url = f"ws://{host}:{port}"

    try:
        final_url = await WSSocketManager.create(requested_url, agent_id=agent_id)
        # Write the ACTUAL url to DB after bind success
        sock_store.add(agent_id, final_url.split("://", 1)[1].split(":")[0], int(final_url.rsplit(":", 1)[1]))

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
    Reads raw request body and forwards it to the per-call WebSocket URL for this agent_id.
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
    Host to bind the per-call WebSocket server on.
    Keep 'localhost' for local dev; in Docker/K8s, set WS_HOST env to a reachable IP/hostname.
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
