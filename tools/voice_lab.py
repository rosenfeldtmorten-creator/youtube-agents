"""Voice lab: compare ways to make the cloned narrator sound like a studio mic.

Runs in the Voice lab workflow. For each candidate it renders the same test line,
masters it like a real video, scores it with Microsoft's DNSMOS (1-5, higher is
cleaner) and writes short MP3s plus a score table to voice/lab/.

Candidates:
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


def main() -> None:
    LAB.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    seg = WORK / "source-seg.wav"
    ffmpeg("-ss", SEGMENT[0], "-t", SEGMENT[1], "-i", str(SOURCE), "-ac", "1", "-ar", "48000", str(seg))

    refs: dict[str, Path] = {"current": ROOT / "voice" / "reference.wav"}
    steps = {
        "df-ref": lambda: as_reference(deep_filter(seg, WORK / "seg-df.wav"), LAB / "reference-df.wav"),
        "re-ref": lambda: as_reference(resemble(seg, WORK / "seg-re.wav"), LAB / "reference-re.wav"),
    }
    for name, make in steps.items():
        try:
            refs[name] = make()
        except Exception as exc:  # one missing tool shouldn't sink the whole comparison
            print(f"::warning title=Voice lab::{name} skipped: {exc}")

    import torch
    from chatterbox.tts import ChatterboxTTS

    torch.manual_seed(0)
    model = ChatterboxTTS.from_pretrained(device="cpu")
    raw: dict[str, Path] = {}
    for name, ref in refs.items():
        print(f"Rendering {name}...", flush=True)
        model.prepare_conditionals(str(ref), exaggeration=0.5)
        torch.manual_seed(0)
        wav = model.generate(TEXT, exaggeration=0.5, cfg_weight=0.5).squeeze(0).numpy()
        out = WORK / f"{name}.wav"
        import soundfile as sf

        sf.write(out, wav, model.sr)
        raw[name] = out

    post = {
        "current+df": lambda: deep_filter(raw["current"], WORK / "current+df.wav"),
        "current+re": lambda: resemble(raw["current"], WORK / "current+re.wav"),
    }
    if "df-ref" in raw:
        post["df-ref+re"] = lambda: resemble(raw["df-ref"], WORK / "df-ref+re.wav")
    for name, make in post.items():
        try:
            raw[name] = make()
        except Exception as exc:
            print(f"::warning title=Voice lab::{name} skipped: {exc}")

    rows = []
    benches = {"your-mic": seg}
    target = WORK / "target.wav"
    if target.exists():
        benches["target-video"] = target
    for name, src in [*benches.items(), *raw.items()]:
        mastered = master(src, WORK / f"m-{name}.wav")
        ffmpeg("-i", str(mastered), "-c:a", "libmp3lame", "-b:a", "160k", str(LAB / f"{name}.mp3"))
        score = dnsmos(mastered)
        rows.append((name, score))

    lines = ["| Version | Voice clarity | Background | Overall |", "|---|---|---|---|"]
    for name, score in rows:
        cells = [f"{v:.2f}" for v in score] if score else ["n/a"] * 3
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    (LAB / "scores.md").write_text(
        "DNSMOS scores (1-5, higher is cleaner) for the same test line.\n\n" + table + "\n"
    )
    print(table)
    print("::notice title=Voice lab scores::" + table.replace("\n", "%0A"))


if __name__ == "__main__":
    main()
