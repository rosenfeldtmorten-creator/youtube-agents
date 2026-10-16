"""Turns a story into a narrated video: slides + voice + subtitles."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
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


def mux(frames: list[tuple[Path, float]], track: np.ndarray, out_dir: Path, fps: int) -> tuple[Path, float]:
    """Join still frames (each shown for its duration) with an audio track into an MP4."""
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
        "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(video),
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
