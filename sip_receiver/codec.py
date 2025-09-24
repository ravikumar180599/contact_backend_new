# sip_receiver/codec.py
import numpy as np

# µ-law lookup table (256 -> int16)
_mu = np.arange(256, dtype=np.int16)
_mu = (~_mu).astype(np.uint8)
sign = ((_mu & 0x80) != 0)
exponent = (_mu >> 4) & 0x07
mantissa = _mu & 0x0F
magnitude = ((mantissa << 1) + 1) << (exponent + 2)
pcm = (magnitude - 33).astype(np.int16)
pcm[sign] = -pcm[sign]
MULAW_LUT = pcm

def mulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Convert G.711 µ-law bytes -> 16-bit PCM (little-endian)."""
    ulaw = np.frombuffer(ulaw_bytes, dtype=np.uint8)
    out = MULAW_LUT[ulaw]
    return out.tobytes()
