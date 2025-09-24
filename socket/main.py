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
    # latest = sock_store.get_latest_for_agent(agent_id)  # -> Optional[tuple[str, str]] (status, url)
    latest = sock_store.get_latest_for_agent(agent_id)  # -> Optional[tuple[str, str]] (status, url)
    if latest:
        latest_status, existing_url = latest
        if latest_status in ("READY", "INPROGRESS"):

            # Re-start/ensure WS on the bind host, but return/persist the PUBLIC host.
            try:
                # Keep the same port if possible
                _, ex_port = _split_ws_host_port(existing_url)
                bind_host = get_ws_bind_host()
                requested_url = f"ws://{bind_host}:{ex_port}"

                bound_url = await WSSocketManager.create(requested_url, agent_id=agent_id)
                _, final_port = _split_ws_host_port(bound_url)

                public_host = get_ws_public_host()
                public_url = f"ws://{public_host}:{final_port}"

                if public_url != existing_url:
                    sock_store.add_url(agent_id, public_url)
                return Response(
                    content=public_url,
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
    bind_host = get_ws_bind_host()
    port = get_ws_port()  # candidate; manager will adjust if occupied
    requested_url = f"ws://{bind_host}:{port}"

    try:
        bound_url = await WSSocketManager.create(requested_url, agent_id=agent_id)
        # Persist the ACTUAL port, but with PUBLIC host
        _, url_port = _split_ws_host_port(bound_url)
        public_host = get_ws_public_host()
        sock_store.add(agent_id, public_host, url_port)

        public_url = f"ws://{public_host}:{url_port}"
        return Response(
            content=public_url,
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

def _get_agent_id_for_call(call_id: str) -> str | None:
    """
    Resolve the agent_id that handled this call_id (latest row).
    """
    sql = """
    SELECT agent_id
    FROM call_mapping
    WHERE call_id = %s
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1;
    """
    try:
        with sock_store.conn.cursor() as cur:
            cur.execute(sql, (call_id,))
            row = cur.fetchone()
            if row and row.get("agent_id"):
                return row["agent_id"]
    except Exception:
        traceback.print_exc()
    return None

@api.delete("/close/{agent_id}")
async def close_by_agent(agent_id: str):
    """
    Stop (free) the WS server for this agent and mark its latest mapping row as COMPLETED (non-destructive).
    """
    try:
        await WSSocketManager.stop(agent_id)
        sock_store.mark_latest_completed(agent_id)  # soft-close: keep row, set status=end_time

        return Response(
            content="closed",
            status_code=status.HTTP_200_OK,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception:
        traceback.print_exc()
        return Response(
            content="failed to close",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"Access-Control-Allow-Origin": "*"},
        )

@api.delete("/close/by_call/{call_id}")
async def close_by_call(call_id: str):
    """
    Resolve the agent for this call, stop its WS server, and mark the latest mapping row for this call as COMPLETED (non-destructive).
    """
    try:
        agent_id = _get_agent_id_for_call(call_id)
        if agent_id:
            await WSSocketManager.stop(agent_id)

        # Soft-close the most recent mapping row associated with this call_id
        marked_url = sock_store.mark_latest_completed(call_id)

        if not agent_id and not marked_url:
            return Response(
                content="not found",
                status_code=status.HTTP_404_NOT_FOUND,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        return Response(
            content="closed",
            status_code=status.HTTP_200_OK,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    except Exception:
        traceback.print_exc()
        return Response(
            content="failed to close",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"Access-Control-Allow-Origin": "*"},
        )

def get_ws_bind_host() -> str:
    """Interface to bind the WS server on (inside process/container)."""
    return os.getenv("WS_BIND_HOST", "0.0.0.0")

def get_ws_public_host() -> str:
    """Host/IP clients will use to connect (persisted in DB)."""
    # Fallback to bind host if not provided (dev-only).
    return os.getenv("WS_PUBLIC_HOST", os.getenv("WS_BIND_HOST", "127.0.0.1"))

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
