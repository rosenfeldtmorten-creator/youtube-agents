"""YouTube Shorts cut from an episode: one or two scenes, vertical, with big captions and a pointer to the full video."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio, music
from .render import mux
from .story import split_sentences
from .visuals import draw_rich_text, hex_rgb

W, H = 1080, 1920
BG = (14, 23, 38)
MAX_SECONDS = 58
OUTRO = "The full story, with all the charts, is on the channel."
CHARTS = ("line", "bars", "growth", "scatter")
MAX_WORDS = 115  # about 45 seconds of narration, leaving room for the outro
LEADING = re.compile(r"^(but|and|so|now|still|yet|instead)\b[,\s]*", re.I)


def _frame(chart_img: Image.Image | None, headline: str, caption: str, accent: str, label: str, path: Path) -> Path:
    img = Image.new("RGB", (W, H), BG)
    draw_rich_text(img, label, (60, 90, W - 120, 60), 34, accent, weight="bold", color=hex_rgb(accent))
    draw_rich_text(img, headline, (60, 170, W - 120, 330), 72, accent, weight="bold")
    if chart_img is not None:
        img.paste(chart_img.resize((W, W)), (0, 520))
    if caption:
        draw_rich_text(img, caption, (70, 1620, W - 140, 240), 50, accent, weight="bold")
    img.save(path)
    return path


def render_short(ep, short: dict, cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> tuple[Path, float]:
    """Render the scenes listed in short["scenes"] (1-based) as a vertical video under a minute long."""
    from .money import draw_chart

    r = cfg["render"]
    accent = r["accent"]
    out_dir.mkdir(parents=True, exist_ok=True)
    headline = short["title"]
    picked = [ep.scenes[i - 1] for i in short["scenes"]]

    voice: list[np.ndarray] = []
    frames: list[tuple[Path, float]] = []
    n = 0
    for k, scene in enumerate(picked, 1):
        sentences = split_sentences(scene.filled or scene.narration)
        if k == 1:
            sentences = tidy_opening(sentences)
        clips = [narrator.say(s) for s in sentences]
        durations = [len(c) / audio.SR + r["sentence_pause"] for c in clips]
        for c in clips:
            voice += [c, audio.silence(r["sentence_pause"])]
        chart_frames: list[Path] = []
        if scene.chart["type"] not in ("card", "photo"):
            chart_frames = draw_chart(ep, scene.chart, out_dir / f"chart_{k}", r["chart_frames"], (W, W))
        # Draw the chart over the first sentence (every frame, so the line moves smoothly), then hold it.
        for j, (sentence, seconds) in enumerate(zip(sentences, durations)):
            if chart_frames and j == 0:
                for p in chart_frames:
                    n += 1
                    frames.append((_frame(Image.open(p).convert("RGB"), headline, sentence, accent, "ECONOMICS IN CHARTS",
                                          out_dir / f"f{n:04d}.png"), seconds / len(chart_frames)))
                continue
            n += 1
            still = Image.open(chart_frames[-1]).convert("RGB") if chart_frames else None
            caption = sentence if still is not None else ""
            text_headline = headline if still is not None else (scene.chart.get("title_filled") or sentence)
            frames.append((_frame(still, text_headline, caption, accent, "ECONOMICS IN CHARTS", out_dir / f"f{n:04d}.png"),
                           seconds))

    end = narrator.say(OUTRO)
    voice += [end, audio.silence(0.6)]
    n += 1
    frames.append((_frame(None, OUTRO, "", accent, "ECONOMICS IN CHARTS", out_dir / f"f{n:04d}.png"), len(end) / audio.SR + 0.6))

    track = np.concatenate(voice)
    seconds = len(track) / audio.SR
    if seconds > MAX_SECONDS:
        raise ValueError(f"short is {seconds:.0f} s; pick shorter scenes (limit {MAX_SECONDS} s)")
    tune = music.fetch(music.pick(ep.slug, ep.raw.get("music")), cache_dir / "music") if r.get("music", True) else None
    video, seconds = mux(frames, track, out_dir, r["fps"], music=tune)
    return video, seconds


def candidates(ep) -> list[dict]:
    """Every Short an episode can give: the ones the script lists in "shorts", then one per chart scene
    whose narration fits in under a minute. The launch Short ("short") is left out, as it went up with the video."""
    launch = (ep.raw.get("short") or {}).get("scenes")
    picks = [dict(s) for s in ep.raw.get("shorts", [])]
    taken = {tuple(s["scenes"]) for s in picks} | ({tuple(launch)} if launch else set())
    for i, scene in enumerate(ep.scenes, 1):
        if scene.chart["type"] not in CHARTS or (i,) in taken:
            continue
        if len((scene.filled or scene.narration).split()) > MAX_WORDS:
            continue
        title = scene.chart.get("title_filled") or scene.chart.get("title") or ep.title
        picks.append({"title": title, "scenes": [i]})
    return [s for s in picks if tuple(s["scenes"]) != tuple(launch or ())]


def tidy_opening(sentences: list[str]) -> list[str]:
    """A scene lifted out of a video can start mid-thought ("But look at..."); drop the joining word."""
    if sentences and LEADING.match(sentences[0]):
        rest = LEADING.sub("", sentences[0], count=1)
        sentences = [rest[:1].upper() + rest[1:], *sentences[1:]]
    return sentences


def short_description(ep, video_id: str) -> str:
    tags = " ".join(f"#{t}" for t in ["Shorts", *ep.hashtags[:3]])
    return f"Full video: https://youtu.be/{video_id}\n\n{ep.description.strip()}\n\n{tags}"
