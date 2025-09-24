# llm/audio_utils.py
"""
Audio utilities for the LLM transcriber.

Helpers to:
- Convert raw PCM16 bytes → np.int16 array.
- Resample mono 8 kHz (or any sr) → 16 kHz using polyphase resampling.
- Write an in-memory WAV (16-bit, mono, 16 kHz) to BytesIO.
- One-shot convenience: PCM16 @ 8 kHz bytes → WAV (mono, 16 kHz) bytes.
"""

from __future__ import annotations

import io
import wave
from typing import Optional

import numpy as np
from scipy.signal import resample_poly


DEFAULT_OUT_SR = 16_000


def pcm16_bytes_to_np(pcm_bytes: bytes) -> np.ndarray:
    """
    Convert raw PCM16-LE mono bytes into a numpy int16 array.

    Args:
        pcm_bytes: raw PCM16-LE mono audio bytes

    Returns:
        np.ndarray dtype=int16, shape=(n_samples,)
    """
    if not pcm_bytes:
        return np.zeros(0, dtype=np.int16)
    # Memoryview avoids an extra copy in frombuffer
    return np.frombuffer(memoryview(pcm_bytes), dtype=np.int16)


def resample_to_16k_mono(pcm: np.ndarray, in_sr: int, out_sr: int = DEFAULT_OUT_SR) -> np.ndarray:
    """
    Resample a mono int16 PCM signal from in_sr → out_sr (default 16 kHz).

    Uses polyphase resampling for quality & speed.

    Args:
        pcm: int16 mono samples
        in_sr: input sample rate
        out_sr: desired output sample rate (default 16_000)

    Returns:
        int16 mono samples at out_sr
    """
    if pcm.size == 0:
        return pcm.astype(np.int16)

    if in_sr == out_sr:
        return pcm.astype(np.int16)

    # Convert to float for filtering, then back to int16 with clipping
    x = pcm.astype(np.float32)
    y = resample_poly(x, up=out_sr, down=in_sr)
    y = np.clip(y, -32768, 32767).astype(np.int16)
    return y


def wav_bytes_from_pcm16_mono(pcm: np.ndarray, sr: int = DEFAULT_OUT_SR) -> bytes:
    """
    Write a mono int16 PCM array into an in-memory WAV (16-bit) file.

    Args:
        pcm: int16 mono samples at sample rate 'sr'
        sr: sample rate to store in the WAV header (default 16_000)

    Returns:
        bytes of a .wav file
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def pcm16_8k_bytes_to_wav_16k(
    pcm_bytes: bytes,
    in_sr: int = 8000,
    out_sr: int = DEFAULT_OUT_SR,
) -> bytes:
    """
    Convenience: Convert raw PCM16-LE mono bytes (default 8 kHz) to a
    mono 16-bit WAV at 16 kHz (or 'out_sr').

    Args:
        pcm_bytes: raw PCM16-LE mono audio bytes
        in_sr: input sample rate of pcm_bytes (default 8000)
        out_sr: desired output sample rate (default 16000)

    Returns:
        bytes of a .wav file (mono, 16-bit, out_sr)
    """
    pcm = pcm16_bytes_to_np(pcm_bytes)
    pcm_16k = resample_to_16k_mono(pcm, in_sr=in_sr, out_sr=out_sr)
    return wav_bytes_from_pcm16_mono(pcm_16k, sr=out_sr)
