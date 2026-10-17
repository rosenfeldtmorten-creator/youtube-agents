"""Voice lab: compare ways to make the cloned narrator sound like a studio mic.

Runs in the Voice lab workflow. For each candidate it renders the same test line,
masters it like a real video, scores it with Microsoft's DNSMOS (1-5, higher is
cleaner) and writes short MP3s plus a score table to voice/lab/.

Round 1 compared reference clean-up (see git history); round 2 compares processing after cloning.
  current      voice/reference.wav as used today
  df-ref       the source clip cleaned with DeepFilterNet before cloning
  re-ref       the source clip restored with Resemble Enhance before cloning
  current+df   today's voice, narration cleaned with DeepFilterNet afterwards
  current+re   today's voice, narration restored with Resemble Enhance afterwards
  df-ref+re    cleaned reference, narration restored afterwards
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from yta.render import AUDIO_MASTER  # noqa: E402

LAB = ROOT / "voice" / "lab"
WORK = Path(os.environ.get("LAB_WORK", "/tmp/voice-lab"))
SOURCE = ROOT / "voice" / "source.m4a"
SEGMENT = ("10.7", "16.5")  # same stretch of the source clip as reference.wav
DEEP_FILTER = os.environ.get("DEEP_FILTER", "deep-filter")
RESEMBLE = os.environ.get("RESEMBLE_ENHANCE", "resemble-enhance")
DNSMOS_MODEL = os.environ.get("DNSMOS_MODEL", "/tmp/sig_bak_ovr.onnx")
TEXT = (
    "In nineteen sixty-eight, the federal minimum wage was a dollar sixty an hour. "
    "Adjusted for prices, that is worth more than today's seven twenty-five, "
    "and this chart shows exactly when it started slipping."
)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def deep_filter(src: Path, dst: Path) -> Path:
    out_dir = WORK / f"df-{src.stem}"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav48 = out_dir / "in.wav"
    ffmpeg("-i", str(src), "-ac", "1", "-ar", "48000", str(wav48))
    subprocess.run([DEEP_FILTER, "-o", str(out_dir / "out"), str(wav48)], check=True)
    shutil.copy(out_dir / "out" / "in.wav", dst)
    return dst


def resemble(src: Path, dst: Path) -> Path:
    tmp = WORK / f"re-{src.stem}"
    (tmp / "in").mkdir(parents=True, exist_ok=True)
    ffmpeg("-i", str(src), "-ac", "1", "-ar", "44100", str(tmp / "in" / "a.wav"))
    subprocess.run([RESEMBLE, str(tmp / "in"), str(tmp / "out"), "--device", "cpu"], check=True)
    shutil.copy(tmp / "out" / "a.wav", dst)
    return dst


def as_reference(src: Path, dst: Path) -> Path:
    # Light tidy-up so every reference reaches Chatterbox at the same level and rate.
    ffmpeg("-i", str(src), "-af", "highpass=f=70,loudnorm=I=-20:TP=-2", "-ac", "1", "-ar", "24000",
           "-c:a", "pcm_s16le", str(dst))
    return dst


def master(src: Path, dst: Path) -> Path:
    ffmpeg("-i", str(src), "-af", AUDIO_MASTER, "-ac", "1", "-ar", "48000", str(dst))
    return dst


def dnsmos(path: Path) -> tuple[float, float, float] | None:
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    if not Path(DNSMOS_MODEL).exists():
        return None
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    fs, seconds = 16000, 9.01
    need = int(seconds * fs)
    while len(audio) < need:
        audio = np.append(audio, audio)
    sess = ort.InferenceSession(DNSMOS_MODEL)
    name = sess.get_inputs()[0].name
    p_sig = np.poly1d([-0.08397278, 1.22083953, 0.0052439])
    p_bak = np.poly1d([-0.13166888, 1.60915514, -0.39604546])
    p_ovr = np.poly1d([-0.06766283, 1.11546468, 0.04602535])
    scores = []
    for hop in range(int(np.floor(len(audio) / fs) - seconds) + 1):
        seg = audio[hop * fs: hop * fs + need]
        if len(seg) < need:
            continue
        sig, bak, ovr = sess.run(None, {name: seg[np.newaxis, :].astype(np.float32)})[0][0]
        scores.append((p_sig(sig), p_bak(bak), p_ovr(ovr)))
    return tuple(float(np.mean(col)) for col in zip(*scores))


STUDIO = (
    # Broadcast-style chain: trim rumble and boxiness, tame "s" sounds, even out the level,
    # add a little warmth, presence and air.
    "highpass=f=80,equalizer=f=350:t=q:w=1.5:g=-3,deesser=i=0.4,"
    "acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=2,"
    "equalizer=f=120:t=q:w=1:g=2,equalizer=f=3500:t=q:w=1.2:g=2,highshelf=f=10000:g=3"
)


def studio(src: Path, dst: Path) -> Path:
    ffmpeg("-i", str(src), "-af", STUDIO, "-ac", "1", "-ar", "48000", str(dst))
    return dst


def main() -> None:
    """Round 2: today's voice (B) with extra processing after cloning."""
    LAB.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device="cpu")
    model.prepare_conditionals(str(ROOT / "voice" / "reference.wav"), exaggeration=0.5)
    torch.manual_seed(0)
    base = WORK / "B.wav"
    sf.write(base, model.generate(TEXT, exaggeration=0.5, cfg_weight=0.5).squeeze(0).numpy(), model.sr)

    raw: dict[str, Path] = {"B": base}
    steps = {
        "B+studio": lambda: studio(base, WORK / "B+studio.wav"),
        "B+clean": lambda: deep_filter(base, WORK / "B+clean.wav"),
        "B+clean+studio": lambda: studio(deep_filter(base, WORK / "B+clean2.wav"), WORK / "B+clean+studio.wav"),
        "B+restore": lambda: resemble(base, WORK / "B+restore.wav"),
        "B+restore+studio": lambda: studio(resemble(base, WORK / "B+restore2.wav"), WORK / "B+restore+studio.wav"),
    }
    for name, make in steps.items():
        try:
            raw[name] = make()
        except Exception as exc:  # one missing tool shouldn't sink the whole comparison
            print(f"::warning title=Voice lab::{name} skipped: {exc}")

    out = LAB / "round2"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, src in raw.items():
        mastered = master(src, WORK / f"m-{name}.wav")
        ffmpeg("-i", str(mastered), "-c:a", "libmp3lame", "-b:a", "192k", str(out / f"{name}.mp3"))
        rows.append((name, dnsmos(mastered)))

    lines = ["| Version | Voice clarity | Background | Overall |", "|---|---|---|---|"]
    for name, score in rows:
        cells = [f"{v:.2f}" for v in score] if score else ["n/a"] * 3
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    (out / "scores.md").write_text("DNSMOS scores (1-5, higher is cleaner) for the same test line.\n\n" + table + "\n")
    print(table)
    print("::notice title=Voice lab scores::" + table.replace("\n", "%0A"))


if __name__ == "__main__":
    main()
