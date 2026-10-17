"""Turns a story into a narrated video: slides + voice + subtitles."""
from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio
from .story import Story
from .visuals import Backgrounds, SlideMaker, thumbnail


@dataclass
class Segment:
    image: Path
    voice: np.ndarray
    pause: float
    caption: str = ""

    @property
    def seconds(self) -> float:
        return len(self.voice) / audio.SR + self.pause


@dataclass
class RenderResult:
    video: Path
    thumbnail: Path
    captions: Path
    seconds: float
    photo_credits: list[str]
    chapters: list[tuple[float, str]]
    music_credits: list[str] = field(default_factory=list)


def _fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_segments(story: Story, cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> tuple[list[Segment], Backgrounds]:
    r = cfg["render"]
    size = (r["width"], r["height"])
    bgs = Backgrounds(size, cache_dir / "photos", r.get("background_source", "pexels"))
    slides = SlideMaker(size, r["accent"], out_dir / "slides")
    para_bg = [bgs.get(p.image_query, f"{story.slug}-{i}") for i, p in enumerate(story.paragraphs)]
    first, last = para_bg[0], para_bg[-1]
    short_title = story.title.split("|")[0].strip()
    phrases = [v["word"] for v in story.vocabulary]
    segs: list[Segment] = []

    def add(image, text, pause, caption=None):
        segs.append(Segment(image, narrator.say(text) if text else audio.silence(0), pause, caption if caption is not None else text))

    print("  intro and key words")
    add(slides.title(first, short_title, story.level, "A slow English story with subtitles"),
        f"{short_title}. A slow English story, level {story.level}.", 1.2)
    for i, v in enumerate(story.vocabulary, 1):
        intro = "First, here are some key words from the story. " if i == 1 else ""
        add(slides.vocab(first, v["word"], v["meaning"], i, len(story.vocabulary)),
            f"{intro}{v['word']}. {v['meaning']}", 1.0, f"{v['word']}: {v['meaning']}")

    total = len(story.sentences)
    done = 0
    for pi, para in enumerate(story.paragraphs):
        print(f"  paragraph {pi + 1}/{len(story.paragraphs)}")
        sents = para.sentences
        for si, sentence in enumerate(sents):
            done += 1
            pause = r["sentence_pause"] + (0.7 if si == len(sents) - 1 else 0)
            add(slides.sentence(para_bg[pi], sentence, phrases, f"{story.level}  ·  {short_title}", done / total),
                sentence, pause)

    print("  quiz")
    for qi, q in enumerate(story.quiz, 1):
        letters = "ABCDEF"
        read_opts = " ".join(f"{letters[i]}: {o}." for i, o in enumerate(q.options))
        intro = "Now, let's check what you remember. " if qi == 1 else ""
        add(slides.quiz(last, qi, len(story.quiz), q.question, q.options, None),
            f"{intro}Question {qi}. {q.question} {read_opts}", r["quiz_think_time"], q.question)
        add(slides.quiz(last, qi, len(story.quiz), q.question, q.options, q.answer),
            f"The answer is {letters[q.answer]}: {q.options[q.answer]}.", 1.2)

    add(slides.outro(last, ["Thanks for listening!", "A new slow English story every week. Subscribe so you don't miss it."]),
        "That's the end of today's story. If you enjoyed it, subscribe for a new story every week. See you next time.", 2.5)
    return segs, bgs


# Voice mastering: cut rumble, thin out the boxy low-mids a phone mic adds, lift clarity, then even out
# loudness to YouTube's speech target (-16 LUFS, peaks below -1.5 dB).
AUDIO_MASTER = (
    "highpass=f=70,equalizer=f=300:t=q:w=1.2:g=-2,equalizer=f=5000:t=q:w=1:g=2,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


# Background music sits about 14 dB under the voice and dips further while someone is speaking.
MUSIC_LEVEL = "loudnorm=I=-30:TP=-8"
MUSIC_DUCK = "sidechaincompress=threshold=0.03:ratio=6:attack=30:release=600"


def audio_args(seconds: float, music: Path | None) -> list[str]:
    if not music:
        return ["-af", AUDIO_MASTER]
    fade = max(0.0, seconds - 4)
    graph = (
        f"[1:a]{AUDIO_MASTER},aresample=48000,asplit=2[v][sc];"
        f"[2:a]aformat=channel_layouts=mono,{MUSIC_LEVEL},aresample=48000,"
        f"afade=t=in:d=2,afade=t=out:st={fade:.2f}:d=4[m0];"
        f"[m0][sc]{MUSIC_DUCK}[m];"
        "[v][m]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.9[a]"
    )
    return ["-filter_complex", graph, "-map", "0:v", "-map", "[a]"]


def mux(frames: list[tuple[Path, float]], track: np.ndarray, out_dir: Path, fps: int,
        music: Path | None = None) -> tuple[Path, float]:
    """Join still frames (each shown for its duration) with an audio track, and optional music, into an MP4."""
    wav = out_dir / "narration.wav"
    audio.write_wav(wav, track)
    seconds = len(track) / audio.SR

    listing = out_dir / "frames.txt"
    lines = []
    for image, duration in frames:
        lines += [f"file '{Path(image).resolve()}'", f"duration {duration:.3f}"]
    lines.append(f"file '{Path(frames[-1][0]).resolve()}'")  # concat demuxer needs the last frame repeated
    listing.write_text("\n".join(lines) + "\n")

    video = out_dir / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(wav),
        *(["-stream_loop", "-1", "-i", str(music)] if music else []),
        "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "20",
        *audio_args(seconds, music), "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(video),
    ], check=True)
    return video, seconds


def encode(segs: list[Segment], out_dir: Path, fps: int) -> tuple[Path, float]:
    track = np.concatenate([np.concatenate([s.voice, audio.silence(s.pause)]) for s in segs])
    return mux([(s.image, s.seconds) for s in segs], track, out_dir, fps)


def write_captions(segs: list[Segment], path: Path) -> Path:
    t, n, out = 0.0, 0, []
    for s in segs:
        speech = len(s.voice) / audio.SR
        if s.caption:
            n += 1
            out.append(f"{n}\n{_fmt_srt(t)} --> {_fmt_srt(t + max(speech, 1.0))}\n{s.caption}\n")
        t += s.seconds
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def render_story(story: Story, cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> RenderResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    segs, bgs = build_segments(story, cfg, narrator, out_dir, cache_dir)
    print(f"  encoding {len(segs)} slides")
    video, seconds = encode(segs, out_dir, cfg["render"]["fps"])
    first_bg = bgs.get(story.paragraphs[0].image_query, f"{story.slug}-0")
    thumb = thumbnail(first_bg, story.thumbnail_text, story.level, cfg["render"]["accent"], out_dir / "thumbnail.jpg")
    captions = write_captions(segs, out_dir / "captions.srt")
    n_vocab, n_sent = len(story.vocabulary), len(story.sentences)
    starts = {0: "Introduction", 1: "Key words", 1 + n_vocab: "The story", 1 + n_vocab + n_sent: "Quiz"}
    chapters, t = [], 0.0
    for i, s in enumerate(segs):
        if i in starts:
            chapters.append((t, starts[i]))
        t += s.seconds
    return RenderResult(video, thumb, captions, seconds, bgs.credits, chapters)


def encode_segment(frames: list[tuple[Path, float]], path: Path, fps: int, seconds: float) -> Path:
    """Encode one scene's frames to a silent clip of exactly `seconds`, so the frame files can be deleted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    listing = path.with_suffix(".txt")
    lines = []
    for image, duration in frames:
        lines += [f"file '{Path(image).resolve()}'", f"duration {duration:.4f}"]
    lines.append(f"file '{Path(frames[-1][0]).resolve()}'")
    listing.write_text("\n".join(lines) + "\n")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-vf", f"fps={fps},format=yuv420p", "-t", f"{seconds:.4f}", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", str(fps * 4), str(path),
    ], check=True)
    return path


def frame_aligned(track: np.ndarray, fps: int) -> np.ndarray:
    """Pad a scene's audio to a whole number of video frames, so clips and sound never drift apart."""
    seconds = len(track) / audio.SR
    target = math.ceil(round(seconds * fps, 6)) / fps
    return np.concatenate([track, audio.silence(target - seconds)]) if target > seconds else track


def mux_segments(segments: list[Path], track: np.ndarray, out_dir: Path, music: Path | None = None) -> tuple[Path, float]:
    """Join per-scene clips and the narration (plus optional music) into the final MP4."""
    wav = out_dir / "narration.wav"
    audio.write_wav(wav, track)
    seconds = len(track) / audio.SR
    listing = out_dir / "segments.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in segments))
    video = out_dir / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(wav),
        *(["-stream_loop", "-1", "-i", str(music)] if music else []),
        "-c:v", "copy", *audio_args(seconds, music), "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(video),
    ], check=True)
    return video, seconds


def remove_dirs(paths: list[Path]) -> None:
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)
