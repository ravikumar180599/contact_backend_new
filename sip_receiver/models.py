# sip_receiver/models.py
from pydantic import BaseModel, Field
from typing import Optional

DEFAULT_CODEC = "PCMU"
DEFAULT_SR = 8000
DEFAULT_CH = 1


class StartCallRequest(BaseModel):
    call_id: str = Field(..., description="Unique call identifier")
    codec: str = Field(DEFAULT_CODEC, description="Codec: PCMU (G.711u) supported")
    sample_rate: int = Field(DEFAULT_SR, description="Sample rate in Hz")
    channels: int = Field(DEFAULT_CH, description="Channels (1=mono)")
    ssrc: Optional[int] = Field(None, description="Optional SSRC filter (decimal)")


class StartCallResponse(BaseModel):
    call_id: str
    rtp_ip: str
    rtp_port: int
    codec: str
    sample_rate: int
    channels: int


class CallInfo(BaseModel):
    call_id: str
    rtp_ip: str
    rtp_port: int
    codec: str
    sample_rate: int
    channels: int
    ssrc: Optional[int]
    packets: int
    bytes: int
    started_at: float
    last_packet_at: Optional[float]
    last_chunk_samples: int = 0
