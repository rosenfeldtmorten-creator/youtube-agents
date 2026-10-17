"""Small audio helpers: mono float32 arrays at one sample rate."""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 48000  # full band, so the restored voice keeps its detail above 12 kHz


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, n, ch, width = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit audio")
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
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
