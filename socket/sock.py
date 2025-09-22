import asyncio
import websockets

async def handler(websocket):
    """
    Handles incoming WebSocket connections and echoes back received messages.
    """
    async for message in websocket:
        print(f"Received message from client: {message}")
        await websocket.send(message)

async def create(host: str, port: int):
    """
    Starts the WebSocket server.
    """
    async with websockets.serve(handler, host, port):
        print(f"WebSocket server started on ws://{host}:{str(port)}")
        await asyncio.Future()  # Run forever

async def close(ws_url: str) -> None:
    async with websockets.connect(ws_url) as websocket:
        print("Connected to WebSocket.")
        # Perform some operations if needed
        # ...
        print("Closing WebSocket connection.")
        await websocket.close()  # Gracefully close the connection
        print("WebSocket connection closed.")
        
async def start(host: str, port: int) -> None:
    await create(host, port)