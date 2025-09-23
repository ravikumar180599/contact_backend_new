# sip_receiver/receiver.py
from __future__ import annotations

import asyncio
import os
import logging
from typing import List

import psycopg2  # optional: used only for a quick startup connectivity check

from fastapi import FastAPI, Response, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import StartCallRequest, StartCallResponse, CallInfo
from .sessions import SESSIONS
from .sip_ua import run_sip_uas

LOG = logging.getLogger(__name__)

app = FastAPI(title="SIP/RTP Receiver", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/start", response_model=StartCallResponse)
async def sip_start(req: StartCallRequest):
    """
    Allocate an RTP port and start receiving RTP for this call_id.
    """
    session = await SESSIONS.start_call(req)
    return StartCallResponse(
        call_id=session.call_id,
        rtp_ip=session.rtp_ip,
        rtp_port=session.rtp_port,
        codec=session.codec,
        sample_rate=session.sample_rate,
        channels=session.channels,
    )

@app.post("/stop/{call_id}")
def sip_end(call_id: str):
    """
    Stop receiving RTP for this call_id and free the port.
    """
    if not SESSIONS.get(call_id):
        raise HTTPException(status_code=404, detail="call_id not found")
    SESSIONS.stop_call(call_id)
    return Response(
        content="success",
        status_code=status.HTTP_200_OK,
        headers={"Access-Control-Allow-Origin": "*"},
    )

@app.get("/calls", response_model=List[CallInfo])
def list_calls():
    """
    List active RTP call sessions and basic stats.
    """
    out: List[CallInfo] = []
    for s in SESSIONS.list():
        out.append(
            CallInfo(
                call_id=s.call_id,
                rtp_ip=s.rtp_ip,
                rtp_port=s.rtp_port,
                codec=s.codec,
                sample_rate=s.sample_rate,
                channels=s.channels,
                ssrc=s.ssrc,
                packets=s.packets,
                bytes=s.bytes,
                started_at=s.started_at,
                last_packet_at=s.last_packet_at,
                last_chunk_samples=len(s._last_chunk_pcm16) // 2,  # 2 bytes per sample
            )
        )
    return out

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.on_event("startup")
async def _start_sip():
    # Optional early DB connectivity check (fail-fast): uses PG_* env if present.
    pg_host = os.getenv("PG_HOST")
    if pg_host:
        try:
            conn = psycopg2.connect(
                host=pg_host,
                port=int(os.getenv("PG_PORT", "5432")),
                dbname=os.getenv("PG_DATABASE", "postgres"),
                user=os.getenv("PG_USER", "postgres"),
                password=os.getenv("PG_PASSWORD", ""),
            )
            conn.close()
            LOG.info("SIP Receiver DB connectivity OK at startup.")
        except Exception:
            LOG.exception("SIP Receiver DB connectivity failed at startup.")

    # Run SIP UAS (UDP 5060) alongside the API
    asyncio.create_task(run_sip_uas())
