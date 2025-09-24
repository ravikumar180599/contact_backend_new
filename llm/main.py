# llm/main.py
import logging
from typing import Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
import websockets

from transcriber_service import TranscriberService
from db import get_ws_url_for_call

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Audio Transcriber", version="1.0.0")

# CORS (loose for now; tighten in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/ingest/{call_id}")
async def ingest(call_id: str, request: Request):
    """
    Accept raw PCM16 (mono) bytes from SIP Receiver, run STT,
    and push the transcript to the per-call WebSocket.

    Body: application/octet-stream (PCM16-LE mono @ 8kHz)
    """
    try:
        audio_bytes: bytes = await request.body()
    except Exception:
        return Response(
            content="failed to read body",
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    if not audio_bytes:
        return Response(
            content="empty body",
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # 1) Transcribe the chunk (PCM16 8 kHz -> text via Parakeet)
    try:
        transcript: str = TranscriberService.transcribe(audio_bytes, in_sr=8000, target_lang="en") or ""
        if not transcript:
            LOG.warning("Empty transcript from STT for call_id=%s (bytes=%d)", call_id, len(audio_bytes))
    except Exception as e:
        LOG.exception("Transcription failed for call_id=%s (bytes=%d): %s", call_id, len(audio_bytes), e)
        return Response(
            content=f"transcription error: {e}",
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers={"Access-Control-Allow-Origin": "*"},
        )



    # 2) Look up the WebSocket URL for this call
    ws_url: Optional[str] = get_ws_url_for_call(call_id)
    print("WS_URL -> ", ws_url)
    if not ws_url:
        LOG.warning("No ws_url found for call_id=%s", call_id)
        return Response(
            content="websocket url not found",
            status_code=status.HTTP_404_NOT_FOUND,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # 3) Push the transcript to the WS
    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(transcript)
    except Exception:
        LOG.exception("Failed to send transcript to WS %s for call_id=%s", ws_url, call_id)
        return Response(
            content="failed to push to websocket",
            status_code=status.HTTP_502_BAD_GATEWAY,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    # 4) Return the transcript as the response too
    return Response(
        content=transcript,
        status_code=status.HTTP_200_OK,
        headers={"Access-Control-Allow-Origin": "*"},
    )
