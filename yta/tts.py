"""Text-to-speech backends. Each returns mono float32 audio at audio.SR."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import audio


class SilentVoice:
    """No sound, timed like slow speech. For test renders without a voice model."""

    def say(self, text: str) -> np.ndarray:
        return audio.silence(max(1.0, len(text.split()) / 2.0))


class EspeakVoice:
    """Robotic but free and fast. Useful to hear timing during tests."""

    def __init__(self, speed: int = 140):
        self.speed = speed

    def say(self, text: str) -> np.ndarray:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.wav"
            subprocess.run(["espeak-ng", "-v", "en-us", "-s", str(self.speed), "-w", str(out), text], check=True)
            data, sr = audio.read_wav(out)
        return audio.resample(data, sr)


class ChatterboxVoice:
    """Zero-shot voice clone from a short reference clip (Resemble AI Chatterbox, MIT licence)."""

    def __init__(self, reference: Path, exaggeration: float = 0.5, cfg_weight: float = 0.5, allow_default: bool = False):
        import torch  # imported here so the light backends work without PyTorch installed
        from chatterbox.tts import ChatterboxTTS

        has_reference = Path(reference).exists()
        if not has_reference and not allow_default:
            raise FileNotFoundError(
                f"Voice reference {reference} is missing. Add a 10-20 second WAV of the narrator (see docs/SETUP.md)."
            )
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = ChatterboxTTS.from_pretrained(device=device)
        if has_reference:
            self.model.prepare_conditionals(str(reference), exaggeration=exaggeration)
        else:
            print(f"  {reference} not found: test render uses Chatterbox's built-in voice")
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        import hashlib

        ref = hashlib.sha1(Path(reference).read_bytes()).hexdigest()[:12] if has_reference else "default"
        # Part of the narration cache key, so a new voice clip or setting never reuses old audio.
        self.cache_tag = f"chatterbox-{ref}-{exaggeration}-{cfg_weight}"

    def say(self, text: str) -> np.ndarray:
        wav = self.model.generate(text, exaggeration=self.exaggeration, cfg_weight=self.cfg_weight)
        data = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
        return audio.trim_silence(audio.resample(data, self.model.sr))


class Narrator:
    """Wraps a backend with the channel's tempo and a cache, so re-renders don't re-synthesize.

    With enhance="resemble", each cached sentence also gets a restored copy (Resemble Enhance: removes
    noise and room sound, rebuilds missing detail), made in one batch by enhance_cached(); say() prefers it."""

    def __init__(self, backend, tempo: float = 1.0, cache_dir: Path | None = None, enhance: str | None = None):
        self.backend = backend
        self.tempo = tempo
        self.cache_dir = cache_dir
        self.enhance = enhance if cache_dir else None
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str) -> str:
        import hashlib

        tag = getattr(self.backend, "cache_tag", type(self.backend).__name__)
        return hashlib.sha1(f"{tag}|{self.tempo}|{text}".encode()).hexdigest()

    def _enhanced(self, key: str) -> Path:
        return self.cache_dir / self.enhance / f"{key}.wav"

    def say(self, text: str) -> np.ndarray:
        key = self._key(text)
        if self.enhance and self._enhanced(key).exists():
            data, sr = audio.read_wav(self._enhanced(key))
            return audio.resample(data, sr)
        cached = self.cache_dir / f"{key}.wav" if self.cache_dir else None
        if cached and cached.exists():
            data, sr = audio.read_wav(cached)
            return audio.resample(data, sr)  # older caches were written at 24 kHz
        data = audio.change_tempo(self.backend.say(text), self.tempo)
        if cached:
            audio.write_wav(cached, data)
        return data

    def enhance_cached(self, texts: list[str]) -> int:
        """Restore every listed sentence that has no restored copy yet, in one run of the enhancer."""
        if self.enhance != "resemble":
            return 0
        todo = [k for k in dict.fromkeys(self._key(t) for t in texts)
                if (self.cache_dir / f"{k}.wav").exists() and not self._enhanced(k).exists()]
        if not todo:
            return 0
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "in", Path(tmp) / "out"
            src.mkdir()
            for k in todo:
                (src / f"{k}.wav").symlink_to((self.cache_dir / f"{k}.wav").resolve())
            tool = os.environ.get("RESEMBLE_ENHANCE", "resemble-enhance")
            subprocess.run([tool, str(src), str(dst), "--device", "cpu"], check=True)
            self._enhanced(todo[0]).parent.mkdir(parents=True, exist_ok=True)
            for k in todo:
                out = dst / f"{k}.wav"
                if out.exists():
                    out.replace(self._enhanced(k))
        return len(todo)


def make_narrator(voice_cfg: dict, repo_root: Path, backend: str | None = None, cache_dir: Path | None = None,
                  allow_default_voice: bool = False) -> Narrator:
    name = backend or voice_cfg.get("backend", "silent")
    if name == "silent":
        impl = SilentVoice()
    elif name == "espeak":
        impl = EspeakVoice()
    elif name == "chatterbox":
        impl = ChatterboxVoice(
            repo_root / voice_cfg["reference"],
            exaggeration=voice_cfg.get("exaggeration", 0.5),
            cfg_weight=voice_cfg.get("cfg_weight", 0.5),
            allow_default=allow_default_voice,
        )
    else:
        raise ValueError(f"Unknown voice backend '{name}'")
    return Narrator(impl, tempo=voice_cfg.get("tempo", 1.0) if name != "silent" else 1.0, cache_dir=cache_dir,
                    enhance=voice_cfg.get("enhance") if name == "chatterbox" else None)
