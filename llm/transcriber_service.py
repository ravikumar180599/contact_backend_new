# llm/transcriber_service.py
import os
import logging
from typing import Optional

import io
import wave
import numpy as np
from scipy.signal import resample_poly

PARAKEET_EXPECT_SR = int(os.getenv("PARAKEET_EXPECT_SR", "16000"))  # Parakeet expects 16kHz WAV
PARAKEET_TARGET_LANG = os.getenv("PARAKEET_TARGET_LANG", "en")      # translation target
PARAKEET_TIMEOUT_SEC = float(os.getenv("PARAKEET_TIMEOUT_SEC", "30"))


import httpx

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Parakeet STT endpoint (override via env if needed)
PARAKEET_URL = os.getenv("PARAKEET_URL", "http://192.168.14.12:8076/transcribe")
# Default sample rate for our RTP → PCM16 pipeline
DEFAULT_SAMPLE_RATE = int(os.getenv("TRANSCRIBE_SAMPLE_RATE", "8000"))


class TranscriberService:
    """
    Thin wrapper around Parakeet (or a stub) that turns audio bytes → text.

    For now, `transcribe()` accepts raw audio bytes (e.g., PCM16 from RTP).
    We call Parakeet and return the text if available; on error or empty result we return "".
    """

    @staticmethod
    def transcribe(audio_bytes: bytes, in_sr: int = DEFAULT_SAMPLE_RATE, target_lang: str = PARAKEET_TARGET_LANG) -> str:
        """
        Args:
            audio_bytes: raw audio bytes (e.g., PCM16-LE mono @ 8kHz)

        Returns:
            transcript: human-readable string (best effort)
        """
        if not audio_bytes:
            return ""

        try:
            text = TranscriberService._call_parakeet(audio_bytes, in_sr=in_sr, target_lang=target_lang)
            return text or ""
        except Exception:
            LOG.exception("Parakeet call failed.")
            return ""

    # ------------------------ internal helpers ------------------------

    @staticmethod
    def _call_parakeet(audio_bytes: bytes, *, in_sr: int, target_lang: str) -> Optional[str]:
        """
        Convert PCM16 mono (in 'sample_rate', typically 8k) to 16k WAV
        and POST as multipart/form-data to Parakeet. Returns text or None.
        """
        # 1) Convert to 16 kHz WAV in-memory
        wav_bytes = TranscriberService._to_wav_16k(audio_bytes, in_sr=in_sr)


        # 2) Single, well-formed multipart request
        timeout = httpx.Timeout(PARAKEET_TIMEOUT_SEC, connect=3.0)
        with httpx.Client(timeout=timeout) as client:
            try:
                r = client.post(
                    PARAKEET_URL,
                    data={
                        "sample_rate": str(PARAKEET_EXPECT_SR),
                        "target_lang": target_lang,
                    },
                    files={
                        "file": ("chunk.wav", wav_bytes, "audio/wav"),
                    },
                )
                if r.status_code == 200:
                    return TranscriberService._extract_text(r)
                else:
                    LOG.warning(
                        "Parakeet returned %s: %s",
                        r.status_code,
                        (r.text or "")[:200],
                    )
            except Exception:
                LOG.exception("Parakeet multipart POST failed.")
        return None
    
    @staticmethod
    def _to_wav_16k(pcm16_bytes: bytes, in_sr: int) -> bytes:
        """
        Convert raw PCM16 mono at 'in_sr' to a 16kHz mono WAV (bytes).
        """
        # bytes -> int16 numpy
        pcm = np.frombuffer(pcm16_bytes, dtype=np.int16)

        # resample to 16kHz if needed (use polyphase for good quality)
        if in_sr != PARAKEET_EXPECT_SR:
            x = pcm.astype(np.float32)
            # up = 16000, down = in_sr (resample_poly will reduce the ratio internally)
            y = resample_poly(x, PARAKEET_EXPECT_SR, in_sr)
            y = np.clip(y, -32768, 32767).astype(np.int16)
        else:
            y = pcm

        # write WAV into memory
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(PARAKEET_EXPECT_SR)
            wf.writeframes(y.tobytes())
        return buf.getvalue()

    @staticmethod
    def _extract_text(resp: httpx.Response) -> Optional[str]:
        """
        Handle common Parakeet-style response shapes:
        - {"text": "..."} or {"transcript": "..."}
        - {"transcription": {"text": "...", ...}}
        - {"result": {"text": "..."}}
        - {"results": [{"text": "..."}, ...]}
        - {"segments": [{"text": "..."}, ...]}
        - {"data": {"text": "..."}}
        Also accept plain text responses.
        """
        ctype = resp.headers.get("Content-Type", "")

        if "application/json" in ctype:
            try:
                js = resp.json()

                # Top-level direct
                for k in ("text", "transcript"):
                    v = js.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()

                # transcription object
                tr = js.get("transcription")
                if isinstance(tr, dict):
                    v = tr.get("text")
                    if isinstance(v, str) and v.strip():
                        return v.strip()

                # result object or list
                res = js.get("result")
                if isinstance(res, dict):
                    v = res.get("text")
                    if isinstance(v, str) and v.strip():
                        return v.strip()

                results = js.get("results")
                if isinstance(results, list):
                    parts = [r.get("text") for r in results if isinstance(r, dict) and isinstance(r.get("text"), str)]
                    joined = " ".join(p.strip() for p in parts if p and p.strip())
                    if joined:
                        return joined

                # segments list (ASR-style)
                segs = js.get("segments")
                if isinstance(segs, list):
                    parts = [s.get("text") for s in segs if isinstance(s, dict) and isinstance(s.get("text"), str)]
                    joined = " ".join(p.strip() for p in parts if p and p.strip())
                    if joined:
                        return joined

                # data.text
                data = js.get("data")
                if isinstance(data, dict):
                    v = data.get("text")
                    if isinstance(v, str) and v.strip():
                        return v.strip()

                # No usable text found in JSON
                return None
            except Exception:
                LOG.debug("Failed to parse Parakeet JSON", exc_info=True)
                return None

        # Plain text fallback
        try:
            txt = resp.text.strip()
            return txt if txt else None
        except Exception:
            return None
        