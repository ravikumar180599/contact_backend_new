# socket/sock.py
import asyncio
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError


async def create(host: str, port: int):
    """
    Start a WebSocket server on (host, port) that:
      - accepts messages from any client (e.g., your LLM pusher)
      - broadcasts each message to all OTHER connected clients (e.g., Postman/UI)
      - shuts down cleanly when the task is cancelled
    """
    connections = set()
    broadcast_lock = asyncio.Lock()

    async def broadcast(message: str, sender=None):
        if not connections:
            return
        dead = []
        async with broadcast_lock:
            for ws in list(connections):
                if ws is sender:
                    continue
                try:
                    await ws.send(message)
                except Exception:
                    # drop dead/broken connections
                    dead.append(ws)
            for ws in dead:
                connections.discard(ws)

    async def handler(websocket):
        """
        Accept messages and broadcast them to other listeners (no echo to sender).
        """
        connections.add(websocket)
        try:
            async for message in websocket:
                print(f"Received message from client: {message}")
                await broadcast(message, sender=websocket)
        except (ConnectionClosedOK, ConnectionClosedError):
            # Peer closed cleanly / already gone — ignore
            pass
        finally:
            connections.discard(websocket)

    server = await websockets.serve(handler, host, port)
    print(f"WebSocket server started on ws://{host}:{port}")
    try:
        await asyncio.Future()  # run forever until cancelled
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()
        print(f"WebSocket server stopped on ws://{host}:{port}")


async def start(host: str, port: int) -> None:
    await create(host, port)
