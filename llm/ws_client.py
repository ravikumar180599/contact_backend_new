# llm/ws_client.py
import asyncio
import logging
from typing import Union

import websockets

LOG = logging.getLogger(__name__)


async def send_text(
    ws_url: str,
    text: Union[str, bytes],
    *,
    timeout: float = 5.0,
    retries: int = 2,
) -> bool:
    """
    Send a single text message to a WebSocket URL.
    Returns True on success, False if all retries fail.

    - ws_url: ws:// or wss:// endpoint
    - text: str or bytes (bytes will be decoded as UTF-8 with replace)
    - timeout: seconds for connect+send
    - retries: how many times to retry on transient failures
    """
    if isinstance(text, bytes):
        # Best-effort decode so we always send a string
        text = text.decode("utf-8", errors="replace")

    attempt = 0
    while attempt <= retries:
        try:
            # Connect and send; context manager ensures graceful close
            async with websockets.connect(
                ws_url,
                max_size=2**20,           # 1 MiB per message (adjust as needed)
                ping_interval=None,        # we don't need heartbeats for one-shot sends
                close_timeout=1.0,
            ) as ws:
                await asyncio.wait_for(ws.send(text), timeout=timeout)
                return True

        except Exception as e:
            attempt += 1
            LOG.warning(
                "WS send attempt %d/%d to %s failed: %s",
                attempt, retries, ws_url, e,
                exc_info=False,
            )
            if attempt > retries:
                break
            # small backoff
            try:
                await asyncio.sleep(min(0.25 * attempt, 1.0))
            except Exception:
                pass

    LOG.error("WS send to %s failed after %d attempts.", ws_url, retries + 1)
    return False


def send_text_sync(
    ws_url: str,
    text: Union[str, bytes],
    *,
    timeout: float = 5.0,
    retries: int = 2,
) -> bool:
    """
    Synchronous convenience wrapper.
    Only use this from non-async contexts (e.g., scripts/tests).

    NOTE: Do NOT call from within an existing event loop (e.g., FastAPI handlers).
    """
    try:
        loop = asyncio.get_running_loop()
        # If we are already in an event loop, the caller should 'await send_text(...)'
        raise RuntimeError("send_text_sync() called from an async context")
    except RuntimeError:
        # No running loop: safe to run
        return asyncio.run(send_text(ws_url, text, timeout=timeout, retries=retries))
