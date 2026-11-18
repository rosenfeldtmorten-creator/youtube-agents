"""Small audio helpers: mono float32 arrays at one sample rate."""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 48000  # full band, so the restored voice keeps its detail above 12 kHz


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a WAV as mono float32. Takes 16/24/32-bit PCM and 32/64-bit float (the enhancer writes float)."""
    raw = Path(path).read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a WAV file")
    fmt = body = None
    pos = 12
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], int.from_bytes(raw[pos + 4:pos + 8], "little")
        chunk = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = chunk
        elif cid == b"data":
            body = chunk
        pos += 8 + size + (size & 1)
    if fmt is None or body is None:
        raise ValueError(f"{path}: WAV has no fmt or data chunk")
    tag, ch, sr = int.from_bytes(fmt[0:2], "little"), int.from_bytes(fmt[2:4], "little"), int.from_bytes(fmt[4:8], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if tag == 0xFFFE and len(fmt) >= 26:  # WAVE_FORMAT_EXTENSIBLE: real tag is in the sub-format GUID
        tag = int.from_bytes(fmt[24:26], "little")
    width = bits // 8
    body = body[:len(body) - len(body) % (width * ch)]
    if tag == 3 and width in (4, 8):
        data = np.frombuffer(body, dtype="<f4" if width == 4 else "<f8").astype(np.float32)
    elif tag == 1 and width == 2:
        data = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768
    elif tag == 1 and width == 3:
        b = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        data = (np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)).astype(np.float32)
    elif tag == 1 and width == 4:
        data = (np.frombuffer(body, dtype="<i4") / float(1 << 31)).astype(np.float32)
    else:
        raise ValueError(f"{path}: unsupported WAV format (tag {tag}, {bits}-bit)")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data, sr


def write_wav(path: Path, data: np.ndarray, sr: int = SR) -> None:
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def resample(data: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    if sr == target or len(data) == 0:
        return data
    n = int(round(len(data) * target / sr))
    return np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)


def silence(seconds: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(round(seconds * sr)), dtype=np.float32)


def change_tempo(data: np.ndarray, tempo: float, sr: int = SR) -> np.ndarray:
    """Slow down or speed up speech without changing pitch (ffmpeg atempo)."""
    if abs(tempo - 1.0) < 1e-3 or len(data) == 0:
        return data
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        write_wav(src, data, sr)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", f"atempo={tempo}", str(dst)],
            check=True,
        )
        out, out_sr = read_wav(dst)
    return resample(out, out_sr, sr)


def trim_silence(data: np.ndarray, threshold: float = 0.01, pad: float = 0.05, sr: int = SR) -> np.ndarray:
    loud = np.flatnonzero(np.abs(data) > threshold)
    if len(loud) == 0:
        return data
    p = int(pad * sr)
    return data[max(0, loud[0] - p): loud[-1] + p]


def even_level(data: np.ndarray, target_db: float = -20.0, sr: int = SR) -> np.ndarray:
    """Scale one spoken sentence to a common speech level.

    Each sentence is cloned on its own, so some come out louder or quieter than the next; the mastering
    compressor can't fix jumps of several dB between sentences, this does. Only the voiced 20 ms windows
    count, so pauses don't drag the level down."""
    if data.size == 0:
        return data
    win = max(1, int(sr * 0.02))
    frames = data[: len(data) // win * win].reshape(-1, win) if len(data) >= win else data.reshape(1, -1)
    rms = np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1))
    voiced = rms[rms > rms.max() * 0.1] if rms.max() > 0 else rms
    level = float(np.sqrt((voiced ** 2).mean())) if voiced.size else 0.0
    if level <= 1e-6:
        return data
    gain = min(4.0, 10 ** (target_db / 20) / level)
    out = data * gain
    peak = float(np.abs(out).max())
    return (out / peak * 0.98 if peak > 0.98 else out).astype(data.dtype)
