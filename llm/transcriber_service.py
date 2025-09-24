# llm/transcriber_service.py
import os
import logging
import random
from typing import Optional

import io
import wave
import numpy as np
from scipy.signal import resample_poly

PARAKEET_EXPECT_SR = int(os.getenv("PARAKEET_EXPECT_SR", "16000"))  # Parakeet expects 16kHz WAV
PARAKEET_TARGET_LANG = os.getenv("PARAKEET_TARGET_LANG", "en")      # translation target
PARAKEET_TIMEOUT_SEC = float(os.getenv("PARAKEET_TIMEOUT_SEC", "10"))


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
    We'll first try Parakeet. If Parakeet is unreachable or errors, we fall
    back to a deterministic fake transcript (so the rest of the pipeline keeps working).
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

        # Try Parakeet first
        try:
            text = TranscriberService._call_parakeet(audio_bytes, in_sr=in_sr, target_lang=target_lang)

            if text:
                return text
        except Exception:
            LOG.exception("Parakeet call failed; falling back to fake transcript.")

        # Fallback: generate a deterministic pseudo transcript
        return TranscriberService._fake_transcript(audio_bytes)

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
        Try to parse a few likely response shapes:
        - JSON: {"text": "..."} or {"transcript": "..."}
        - Plain text body
        """
        # JSON?
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                js = resp.json()
                for key in ("text", "transcript", "result"):
                    if key in js and isinstance(js[key], str) and js[key].strip():
                        return js[key].strip()
            except Exception:
                LOG.debug("Failed to parse Parakeet JSON", exc_info=True)

        # Plain text?
        try:
            txt = resp.text.strip()
            return txt if txt else None
        except Exception:
            return None

    @staticmethod
    def _fake_transcript(audio_bytes: bytes, words: int = 12) -> str:
        """
        Deterministic fake transcript generator (so tests are repeatable).
        Seeds RNG with hash of the audio to keep output consistent per chunk.
        """
        seed = (sum(audio_bytes[:64]) + len(audio_bytes) * 131) % (2**32)
        rnd = random.Random(seed)
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        out = []
        for _ in range(words):
            word_len = rnd.randint(3, 9)
            word = "".join(alphabet[rnd.randint(0, 25)] for _ in range(word_len))
            out.append(word)
        return " ".join(out)
