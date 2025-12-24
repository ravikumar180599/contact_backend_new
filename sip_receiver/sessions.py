# sip_receiver/sessions.py
import asyncio
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
# added comment only.....

from .models import StartCallRequest

# ===== RTP bind / port-pool config =====
RTP_BIND_IP = os.getenv("RTP_BIND_IP", "0.0.0.0")
RTP_PORT_MIN = int(os.getenv("RTP_PORT_MIN", "11000"))
RTP_PORT_MAX = int(os.getenv("RTP_PORT_MAX", "12000"))

#added some comments to check the issue
# ---------- G.711 µ-law helpers ----------
def _mulaw_decode_byte(b: int) -> int:
    b ^= 0xFF
    sign = b & 0x80
    exponent = (b >> 4) & 0x07
    mantissa = b & 0x0F
    sample = ((mantissa << 4) + 0x08) << (exponent + 3)
    sample -= 0x84  # 132 bias
    if sign:
        sample = -sample
    # clamp to 16-bit
    if sample > 32767:
        return 32767
    if sample < -32768:
        return -32768
    return sample


def pcmu_to_pcm16(payload: bytes) -> bytes:
    """Convert a buffer of G.711 µ-law to 16-bit little-endian PCM."""
    out = bytearray(len(payload) * 2)
    j = 0
    for b in payload:
        s = _mulaw_decode_byte(b)
        out[j] = s & 0xFF
        out[j + 1] = (s >> 8) & 0xFF
        j += 2
    return bytes(out)


# ---------- RTP header parse ----------
def parse_rtp_header(pkt: bytes) -> Tuple[int, int, int, int, bytes]:
    """
    Minimal RTP parsing.
    Returns: (pt, seq, ts, ssrc, payload)
    """
    if len(pkt) < 12:
        raise ValueError("RTP packet too short")

    v_p_x_cc = pkt[0]
    version = v_p_x_cc >> 6
    if version != 2:
        raise ValueError("Unsupported RTP version")

    pt = pkt[1] & 0x7F
    seq = int.from_bytes(pkt[2:4], "big")
    ts = int.from_bytes(pkt[4:8], "big")
    ssrc = int.from_bytes(pkt[8:12], "big")

    cc = v_p_x_cc & 0x0F
    ext = (pkt[0] & 0x10) != 0

    idx = 12 + 4 * cc
    if ext:
        if len(pkt) < idx + 4:
            raise ValueError("RTP ext header truncated")
        ext_len = int.from_bytes(pkt[idx + 2:idx + 4], "big")
        idx += 4 + (ext_len * 4)
    if idx > len(pkt):
        raise ValueError("Bad RTP header length")

    return pt, seq, ts, ssrc, pkt[idx:]


# ---------- In-memory per-call session ----------
@dataclass
class CallSession:
    call_id: str
    rtp_ip: str
    rtp_port: int
    codec: str
    sample_rate: int
    channels: int
    ssrc: Optional[int] = None

    packets: int = 0
    bytes: int = 0
    started_at: float = field(default_factory=time.time)
    last_packet_at: Optional[float] = None

    _transport: Optional[asyncio.transports.DatagramTransport] = field(default=None, repr=False)
    _last_chunk_pcm16: bytes = field(default=b"", repr=False)

    def close(self) -> None:
        try:
            if self._transport:
                self._transport.close()
        except Exception:
            pass


# ---------- UDP protocol for RTP ----------
class RTPProtocol(asyncio.DatagramProtocol):
    def __init__(self, session: CallSession):
        super().__init__()
        self.session = session

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.session._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            pt, seq, ts, ssrc, payload = parse_rtp_header(data)
        except Exception:
            return  # ignore malformed

        if self.session.ssrc is not None and ssrc != self.session.ssrc:
            return

        self.session.packets += 1
        self.session.bytes += len(data)
        self.session.last_packet_at = time.time()

        if self.session.codec.upper() == "PCMU":
            pcm = pcmu_to_pcm16(payload)
        else:
            # extend for other codecs (e.g., PCMA) as needed
            pcm = payload  # not normalized

        # keep last chunk for observability only (not persisted)
        self.session._last_chunk_pcm16 = pcm


# ---------- Session manager ----------
class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, CallSession] = {}
        self._allocated_ports: set[int] = set()
        self._lock = asyncio.Lock()

    def get(self, call_id: str) -> Optional[CallSession]:
        return self._sessions.get(call_id)

    def list(self) -> List[CallSession]:
        return list(self._sessions.values())

    @staticmethod
    def _port_available(port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((RTP_BIND_IP, port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    async def _next_free_port(self) -> int:
        for p in range(RTP_PORT_MIN, RTP_PORT_MAX + 1):
            if p not in self._allocated_ports and self._port_available(p):
                self._allocated_ports.add(p)
                return p
        raise RuntimeError("No free RTP ports available")

    async def start_call(self, req: StartCallRequest) -> CallSession:
        # guard against concurrent start for same call_id
        async with self._lock:
            existing = self._sessions.get(req.call_id)
            if existing:
                return existing

            port = await self._next_free_port()
            session = CallSession(
                call_id=req.call_id,
                rtp_ip=RTP_BIND_IP,
                rtp_port=port,
                codec=req.codec,
                sample_rate=req.sample_rate,
                channels=req.channels,
                ssrc=req.ssrc,
            )

            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: RTPProtocol(session),
                local_addr=(RTP_BIND_IP, port),
                reuse_port=False,
            )
            session._transport = transport
            self._sessions[req.call_id] = session
            return session

    def stop_call(self, call_id: str) -> None:
        sess = self._sessions.pop(call_id, None)
        if not sess:
            return
        try:
            sess.close()
        finally:
            self._allocated_ports.discard(sess.rtp_port)


# singleton
SESSIONS = SessionManager()
