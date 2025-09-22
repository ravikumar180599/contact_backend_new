# sip_receiver/sip_ua.py
import asyncio
import os
import re
import socket
import time
from typing import Dict, Tuple, Optional

from .sessions import SESSIONS
from .models import StartCallRequest

SIP_IP: str = os.getenv("SIP_BIND_IP", "0.0.0.0")
SIP_PORT: int = int(os.getenv("SIP_PORT", "5060"))
ADVERTISE_IP: Optional[str] = os.getenv("ADVERTISE_IP")
RTP_IP: str = ADVERTISE_IP or os.getenv("RTP_BIND_IP", "0.0.0.0")


# ---------- minimal parsing helpers ----------
def parse_start_line(msg: str) -> Tuple[str, str, str]:
    line = msg.split("\r\n", 1)[0]
    if line.startswith(("INVITE", "ACK", "BYE")):
        parts = line.split()
        method = parts[0]
        uri = parts[1] if len(parts) > 1 else ""
        ver = parts[2] if len(parts) > 2 else "SIP/2.0"
        return method, uri, ver
    return "", "", ""


def parse_headers(msg: str) -> Dict[str, str]:
    hdrs: Dict[str, str] = {}
    lines = msg.split("\r\n")
    for ln in lines[1:]:
        if not ln or ":" not in ln:
            break
        k, v = ln.split(":", 1)
        hdrs[k.strip().lower()] = v.strip()
    return hdrs


def header_param(v: str, name: str) -> Optional[str]:
    m = re.search(rf';\s*{re.escape(name)}=([^;>\s]+)', v or "", flags=re.I)
    return m.group(1) if m else None


def get_call_id(hdrs: Dict[str, str]) -> str:
    return hdrs.get("call-id", "").strip()


def get_cseq(hdrs: Dict[str, str]) -> Tuple[int, str]:
    raw = hdrs.get("cseq", "0 INVITE")
    parts = raw.split(None, 1)
    num = int(parts[0]) if parts else 0
    method = parts[1].strip().upper() if len(parts) > 1 else "INVITE"
    return num, method


def sdp_answer(ip: str, port: int) -> str:
    ts = int(time.time())
    return (
        "v=0\r\n"
        f"o=- {ts} {ts} IN IP4 {ip}\r\n"
        f"s=SipReceiver\r\n"
        f"c=IN IP4 {ip}\r\n"
        "t=0 0\r\n"
        f"m=audio {port} RTP/AVP 0\r\n"   # PT 0 = PCMU
        "a=rtpmap:0 PCMU/8000/1\r\n"
    )


# ---------- dialog tracking ----------
class Dialog:
    def __init__(self, call_id: str, from_tag: str, to_tag: str, peer_addr: Tuple[str, int]):
        self.call_id = call_id
        self.from_tag = from_tag
        self.to_tag = to_tag
        self.peer_addr = peer_addr
        self.rtp_port: int = -1
        self.established: bool = False


class SipUAS(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.dialogs: Dict[str, Dialog] = {}

    def connection_made(self, transport: asyncio.DatagramTransport):
        self.transport = transport
        sock = transport.get_extra_info("socket")
        if sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
        print(f"SIP UAS listening on udp://{SIP_IP}:{SIP_PORT}")

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        try:
            msg = data.decode(errors="ignore")
            method, _, _ = parse_start_line(msg)
            if not method:
                return

            hdrs = parse_headers(msg)
            call_id = get_call_id(hdrs)
            from_hdr = hdrs.get("from", "")
            to_hdr = hdrs.get("to", "")
            from_tag = header_param(from_hdr, "tag") or "fromtag"

            # ensure dialog exists
            if call_id not in self.dialogs:
                self.dialogs[call_id] = Dialog(call_id, from_tag, f"to{int(time.time()*1000)}", addr)

            if method == "INVITE":
                # provisional responses
                self._send_response(addr, 100, "Trying", hdrs, to_tag=None)
                self._send_response(addr, 180, "Ringing", hdrs, to_tag=self.dialogs[call_id].to_tag)

                async def do_start():
                    session = await SESSIONS.start_call(
                        StartCallRequest(call_id=call_id, codec="PCMU", sample_rate=8000, channels=1, ssrc=None)
                    )
                    self.dialogs[call_id].rtp_port = session.rtp_port
                    sdp = sdp_answer(RTP_IP, session.rtp_port)
                    self._send_response(addr, 200, "OK", hdrs, to_tag=self.dialogs[call_id].to_tag, sdp=sdp)

                asyncio.create_task(do_start())

            elif method == "ACK":
                d = self.dialogs.get(call_id)
                if d:
                    d.established = True

            elif method == "BYE":
                # stop RTP and confirm
                SESSIONS.stop_call(call_id)
                to_tag = self.dialogs.get(call_id).to_tag if call_id in self.dialogs else None
                self._send_response(addr, 200, "OK", hdrs, to_tag=to_tag)
                self.dialogs.pop(call_id, None)

            else:
                # keep it minimal for now
                to_tag = self.dialogs.get(call_id).to_tag if call_id in self.dialogs else None
                self._send_response(addr, 405, "Method Not Allowed", hdrs, to_tag=to_tag)

        except Exception:
            # swallow parsing/format errors for robustness
            return

    def _send_response(
        self,
        addr: Tuple[str, int],
        code: int,
        reason: str,
        req_hdrs: Dict[str, str],
        to_tag: Optional[str],
        sdp: Optional[str] = None,
    ):
        call_id = req_hdrs.get("call-id", "")
        cseq = req_hdrs.get("cseq", "")
        via = req_hdrs.get("via", "")
        from_h = req_hdrs.get("from", "")
        to_h = req_hdrs.get("to", "")

        # ensure To has a tag
        if to_tag:
            if ";tag=" in to_h:
                to_out = re.sub(r";tag=[^;>]+", "", to_h) + f";tag={to_tag}"
            else:
                to_out = f"{to_h};tag={to_tag}"
        else:
            to_out = to_h

        # echo top Via, adding rport/received if absent (helps NAT testers like StarTrinity)
        topvia = via.split(",")[0].strip()
        if "rport" not in topvia.lower():
            topvia += ";rport"
        if "received=" not in topvia.lower():
            topvia += f";received={addr[0]}"

        # contact uses the listening SIP endpoint
        contact_ip = addr[0] if SIP_IP in ("0.0.0.0", "::") else SIP_IP
        contact = f"<sip:{contact_ip}:{SIP_PORT};transport=udp>"

        lines = [
            f"SIP/2.0 {code} {reason}",
            f"Via: {topvia}",
            f"From: {from_h}",
            f"To: {to_out}",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq}",
            f"Contact: {contact}",
            "Server: SipReceiver/1.1",
        ]

        if sdp:
            body = sdp
            lines += ["Content-Type: application/sdp", f"Content-Length: {len(body)}", "", body]
        else:
            lines += ["Content-Length: 0", "", ""]

        payload = "\r\n".join(lines).encode()
        if self.transport:
            self.transport.sendto(payload, addr)


async def run_sip_uas():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: SipUAS(), local_addr=(SIP_IP, SIP_PORT))
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        transport.close()
