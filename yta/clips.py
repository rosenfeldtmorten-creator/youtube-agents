"""Nature clips: narrated Shorts built from licensed stock and public-domain footage, and a weekly compilation of them.

A Short is 4-8 scenes. Each scene is one sentence or two of our own narration over one clip found by search
(yta/footage.py: Pexels, Pixabay, Wikimedia Commons, NASA). Never clips cut from news or other people's videos.
On screen: the title at the top, big captions a few words at a time, the footage credit, and a SUBSCRIBE prompt in the
first seconds and again under the spoken outro. The compilation joins the week's Shorts into one landscape video
with chapters, re-using the cached narration.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import audio, footage, music
from .render import RenderResult, _fmt_srt, frame_aligned, mux_segments
from .story import StoryError, split_sentences, words
from .visuals import font, hex_rgb, thumbnail, wrap_tokens

SHORT = (1080, 1920)
WIDE = (1920, 1080)
MAX_SHORT_SECONDS = 59
CAPTION_WORDS = 3  # words on screen at once: Shorts are watched with the sound off as often as on
GRADE = "eq=contrast=1.06:saturation=1.12"  # a touch more punch than raw stock footage
ABBREVIATION = re.compile(r"(St|Mt|Dr|Mr|Mrs|Ms|No|vs)\.")  # not the end of a sentence
HYPE = re.compile(r"\b(you won't believe|shocking|insane|gone wrong|caught on camera|viral)\b", re.I)


@dataclass
class ClipScene:
    narration: str
    video: list[str]

    @property
    def sentences(self) -> list[str]:
        return split_sentences(self.narration)


@dataclass
class ClipItem:
    path: Path
    slug: str
    title: str
    description: str
    tags: list[str]
    scenes: list[ClipScene]
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(s.narration for s in self.scenes)

    @property
    def word_count(self) -> int:
        return len(words(self.text))

    @property
    def hashtags(self) -> list[str]:
        if self.raw.get("hashtags"):
            return [str(t).lstrip("#") for t in self.raw["hashtags"]]
        return ["".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", t)) for t in self.tags[:3]]


def load_clips(path: Path) -> ClipItem:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryError(f"{path.name}: invalid JSON ({exc})") from exc
    for key, kind in (("slug", str), ("title", str), ("description", str), ("tags", list), ("scenes", list)):
        if not isinstance(data.get(key), kind):
            raise StoryError(f"{path.name}: field '{key}' is missing or not a {kind.__name__}")
    scenes = []
    for i, s in enumerate(data["scenes"], 1):
        video = s.get("video") if isinstance(s, dict) else None
        video = [video] if isinstance(video, str) else video
        if not (isinstance(s, dict) and isinstance(s.get("narration"), str) and video
                and all(isinstance(v, str) and v.strip() for v in video)):
            raise StoryError(f"{path.name}: scene {i} needs \"narration\" and \"video\" (one or more footage searches)")
        scenes.append(ClipScene(s["narration"].strip(), [v.strip() for v in video]))
    return ClipItem(path, data["slug"], data["title"].strip(), data["description"], [str(t) for t in data["tags"]],
                    scenes, data)


def check_script(item: ClipItem, rules: dict) -> None:
    """Shape rules for a Short. CheckFailed says what to fix."""
    from .checks import CheckFailed

    n = item.word_count
    if not rules["min_words"] <= n <= rules["max_words"]:
        raise CheckFailed(f"a Short needs {rules['min_words']}-{rules['max_words']} words of narration; this one has {n}")
    if not rules["min_scenes"] <= len(item.scenes) <= rules["max_scenes"]:
        raise CheckFailed(f"a Short needs {rules['min_scenes']}-{rules['max_scenes']} scenes; this one has {len(item.scenes)}")
    if len(item.title) > rules.get("max_title_chars", 70):
        raise CheckFailed(f"title is {len(item.title)} characters; keep it under {rules.get('max_title_chars', 70)}")
    first = item.scenes[0].sentences[0] if item.scenes[0].sentences else ""
    if len(first.split()) > rules.get("max_hook_words", 14):
        raise CheckFailed(f"the opening line has {len(first.split())} words; the hook must land in the first two seconds "
                          f"(at most {rules.get('max_hook_words', 14)} words)")
    for i, s in enumerate(item.scenes, 1):
        if len(words(s.narration)) > rules.get("max_scene_words", 30):
            raise CheckFailed(f"scene {i} has {len(words(s.narration))} words; one clip shouldn't run that long "
                              f"(at most {rules.get('max_scene_words', 30)}), so split it")
    hype = HYPE.search(item.title + " " + item.text)
    if hype:
        raise CheckFailed(f"'{hype[0]}' is clickbait wording the guide rules out; say what actually happens instead")
    if re.search(r"\bsubscribe\b", item.text, re.I):
        raise CheckFailed("leave 'subscribe' out of the script; the video adds its own spoken and on-screen prompt")


# ---------------------------------------------------------------- drawing

def _stroked(d: ImageDraw.ImageDraw, xy, text: str, size: int, fill, anchor: str = "mm", stroke: int = 0) -> None:
    d.text(xy, text, font=font(size, "bold"), fill=fill, anchor=anchor, stroke_width=stroke or max(3, size // 11),
           stroke_fill=(0, 0, 0, 255))


def _lines(text: str, size: int, width: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    tokens = text.split()
    return [" ".join(tokens[i] for i in line) for line in wrap_tokens(tokens, font(size, "bold"), width, d)]


def caption_chunks(sentence: str, n: int = CAPTION_WORDS) -> list[str]:
    """A sentence cut into a few words at a time, breaking after commas where it can."""
    chunks, cur = [], []
    for w in sentence.split():
        cur.append(w)
        ends = w[-1:] in ",;:" or (w[-1:] in ".!?" and not ABBREVIATION.fullmatch(w))
        if len(cur) >= n or (ends and len(cur) >= 2):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        if chunks and len(cur) == 1 and len(chunks[-1].split()) < n + 1:
            chunks[-1] += " " + cur[0]  # no lone last word on screen
        else:
            chunks.append(" ".join(cur))
    return chunks


def chunk_times(chunks: list[str], speech: float) -> list[tuple[float, float]]:
    """When each chunk is on screen, shared out by length: longer words take longer to say."""
    weights = [len(c) + 3 for c in chunks]
    total, t, out = sum(weights), 0.0, []
    for w in weights:
        out.append((t, t + speech * w / total))
        t += speech * w / total
    return out


def _caption_png(text: str, accent, path: Path, size: tuple[int, int]) -> tuple[Path, int, int]:
    """One caption, as a small transparent image and where it goes. Numbers are picked out in the accent colour."""
    w, h = size
    tall = h > w
    px = 96 if tall else 68
    lines = _lines(text.upper() if tall else text, px, int(w * 0.84))
    line_h = int(px * 1.2)
    img = Image.new("RGBA", (w, line_h * len(lines) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for k, line in enumerate(lines):
        colour = accent + (255,) if re.search(r"\d", line) else (255, 255, 255, 255)
        _stroked(d, (w // 2, 20 + line_h * k + line_h // 2), line, px, colour)
    img.save(path)
    y = int(h * 0.60) if tall else h - img.height - 110
    return path, 0, y


def _header_png(title: str, label: str, accent, path: Path, size: tuple[int, int]) -> Path:
    """The Short's title, held at the top for the whole video, over a soft dark fade."""
    w, _ = size
    img = Image.new("RGBA", (w, 640), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(640):
        d.line((0, y, w, y), fill=(8, 12, 20, int(170 * (1 - y / 640) ** 1.6)))
    _stroked(d, (w // 2, 230), label, 34, accent + (255,), stroke=3)
    for k, line in enumerate(_lines(title.upper(), 64, int(w * 0.86))[:3]):
        _stroked(d, (w // 2, 310 + 78 * k), line, 64, (255, 255, 255, 255))
    img.save(path)
    return path


def _subscribe_png(path: Path, tall: bool) -> Path:
    px = 50 if tall else 40
    f = font(px, "bold")
    text = "SUBSCRIBE"
    tw = int(ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(text, font=f))
    bw, bh = tw + px * 3, int(px * 2.0)
    img = Image.new("RGBA", (bw + 12, bh + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((6, 10, bw + 6, bh + 10), radius=bh // 2, fill=(0, 0, 0, 110))  # shadow
    d.rounded_rectangle((4, 4, bw + 4, bh + 4), radius=bh // 2, fill=(229, 30, 37, 255))
    cx, cy = 4 + px * 1.1, 4 + bh / 2
    d.polygon([(cx - px * 0.3, cy - px * 0.38), (cx - px * 0.3, cy + px * 0.38), (cx + px * 0.4, cy)], fill="white")
    d.text((4 + px * 1.9, 4 + bh / 2), text, font=f, fill="white", anchor="lm")
    img.save(path)
    return path


def _credit_png(text: str, path: Path, size: tuple[int, int]) -> tuple[Path, int, int]:
    w, h = size
    tall = h > w
    px = 26 if tall else 24
    tw = int(ImageDraw.Draw(Image.new("RGB", (8, 8))).textlength(text, font=font(px)))
    img = Image.new("RGBA", (tw + 24, px + 20), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((12, 10), text, font=font(px), fill=(235, 235, 235, 235), stroke_width=2,
                             stroke_fill=(0, 0, 0, 200))
    img.save(path)
    return (path, 40, int(h * 0.755)) if tall else (path, w - img.width - 36, h - img.height - 24)


def _chapter_png(number: int, title: str, accent, path: Path, size: tuple[int, int]) -> tuple[Path, int, int]:
    """Compilation chapter card: '#3' and the moment's title, lower left."""
    w, h = size
    img = Image.new("RGBA", (w, 330), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(330):
        d.line((0, y, w, y), fill=(8, 12, 20, int(190 * (y / 330))))
    d.rectangle((90, 80, 102, 250), fill=accent + (255,))
    _stroked(d, (130, 120), f"#{number}", 64, accent + (255,), anchor="lm", stroke=4)
    for k, line in enumerate(_lines(title, 70, int(w * 0.75))[:2]):
        _stroked(d, (130, 196 + 74 * k), line, 70, (255, 255, 255, 255), anchor="lm", stroke=5)
    img.save(path)
    return path, 0, int(h * 0.36)


# ---------------------------------------------------------------- encoding

@dataclass
class Layer:
    """An image laid over a scene's clip from `start` to `end` seconds (scene time), fading in when `fade`."""
    path: Path
    x: int
    y: int
    start: float
    end: float
    fade: float = 0.0


def scene_video(clip: footage.Clip, path: Path, size: tuple[int, int], fps: int, seconds: float,
                layers: list[Layer]) -> Path:
    """One scene: the clip cropped to fill the frame, slowed a little if short (looped only if far too short),
    with every layer on top. Same codec settings as the other scenes, so they join without re-encoding."""
    w, h = size
    length = footage.duration(clip.path)
    slow = min(1.5, max(1.0, seconds / length)) if length else 1.0
    loop = ["-stream_loop", "-1"] if length * slow < seconds else []
    # Archive footage often opens on a title slate; start a little in when the clip is long enough to spare it.
    skip = ["-ss", f"{min(2.0, length - seconds / slow):.2f}"] if not loop and length - seconds / slow > 0.5 else []
    inputs, graph = [], [f"[0:v]setpts={slow:.4f}*PTS,scale={w}:{h}:force_original_aspect_ratio=increase,"
                         f"crop={w}:{h},{GRADE},fps={fps},format=rgba[b0]"]
    for k, layer in enumerate(layers, 1):
        inputs += ["-loop", "1", "-t", f"{seconds:.3f}", "-i", str(layer.path)]
        fade = (f",fade=t=in:st={layer.start:.3f}:d={layer.fade:.2f}:alpha=1" if layer.fade else "")
        graph.append(f"[{k}:v]format=rgba{fade}[o{k}]")
        graph.append(f"[b{k - 1}][o{k}]overlay={layer.x}:{layer.y}:eof_action=pass:"
                     f"enable='between(t,{layer.start:.3f},{layer.end:.3f})'[b{k}]")
    graph.append(f"[b{len(layers)}]format=yuv420p[out]")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", *loop, *skip, "-i", str(clip.path), *inputs,
        "-filter_complex", ";".join(graph), "-map", "[out]", "-t", f"{seconds:.4f}", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", str(fps * 2), "-r", str(fps), str(path),
    ], check=True)
    return path


def _grab(video: Path, at: float, path: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
                    str(path)], check=True)
    return path


# ---------------------------------------------------------------- shared scene builder

@dataclass
class Scene:
    clip: footage.Clip
    sentences: list[str]
    voices: list[np.ndarray]
    pause: float
    extra: list[Layer] = field(default_factory=list)  # chapter cards, subscribe prompts
    subscribe_from: float | None = None              # scene time at which the outro prompt comes up


def _say_all(narrator, sentences: list[str]) -> list[np.ndarray]:
    return [narrator.say(s) for s in sentences]


def _build(scenes: list[Scene], size: tuple[int, int], fps: int, accent, work: Path, captions: list[str],
           header: Path | None) -> tuple[list[Path], np.ndarray, list[float]]:
    """Encode every scene with its timed captions; return the segments, the narration track and when each scene starts."""
    tall = size[1] > size[0]
    segments, voice_parts, starts, t0, n = [], [], [], 0.0, 0
    sub_png = _subscribe_png(work / "subscribe.png", tall)
    sub_w = Image.open(sub_png).width
    sub_xy = ((size[0] - sub_w) // 2, int(size[1] * 0.30)) if tall else (size[0] - sub_w - 60, 60)
    for i, sc in enumerate(scenes, 1):
        parts, layers, t = [], list(sc.extra), 0.0
        if header is not None:
            layers.insert(0, Layer(header, 0, 0, 0, 1e6))
        for sentence, voice in zip(sc.sentences, sc.voices):
            speech = len(voice) / audio.SR
            chunks = caption_chunks(sentence) if tall else caption_chunks(sentence, 6)
            for chunk, (a, b) in zip(chunks, chunk_times(chunks, speech)):
                n += 1
                png, x, y = _caption_png(chunk, accent, work / f"cap{n:03d}.png", size)
                layers.append(Layer(png, x, y, t + a, t + b))
                captions.append(f"{len(captions) + 1}\n{_fmt_srt(t0 + t + a)} --> {_fmt_srt(t0 + t + b)}\n{chunk}\n")
            parts += [voice, audio.silence(sc.pause)]
            t += speech + sc.pause
        track = frame_aligned(np.concatenate(parts), fps)
        seconds = len(track) / audio.SR
        png, x, y = _credit_png(sc.clip.credit, work / f"credit{i:02d}.png", size)
        layers.append(Layer(png, x, y, 0, seconds))
        if sc.subscribe_from is not None:
            layers.append(Layer(sub_png, *sub_xy, sc.subscribe_from, seconds, fade=0.25))
        segments.append(scene_video(sc.clip, work / "segments" / f"{i:02d}.mp4", size, fps, seconds, layers))
        voice_parts.append(track)
        starts.append(t0)
        t0 += seconds
    return segments, np.concatenate(voice_parts), starts


def _subscribe_early(scenes: list[Scene], at: float, hold: float, sub_png: Path, xy: tuple[int, int]) -> None:
    """Put the SUBSCRIBE prompt on screen from `at` seconds for `hold` seconds, whichever scenes that spans."""
    t = 0.0
    for sc in scenes:
        length = sum(len(v) / audio.SR + sc.pause for v in sc.voices)
        a, b = max(at, t), min(at + hold, t + length)
        if a < b:
            sc.extra.append(Layer(sub_png, *xy, a - t, b - t, fade=0.25 if a == at else 0.0))
        t += length


def _clips_used(channel_dir: Path) -> set[str]:
    """Footage pages already shown on the channel, so a new Short never repeats one."""
    used = set()
    for p in (channel_dir / "published").glob("*.json"):
        try:
            used.update(json.loads(p.read_text(encoding="utf-8")).get("_published", {}).get("clips", []))
        except (json.JSONDecodeError, AttributeError):
            continue
    return used


def _find(scene: ClipScene, cache_dir: Path, portrait: bool, avoid: set[str]) -> footage.Clip:
    clip = footage.clip_for({"video": scene.video}, cache_dir / "footage", portrait=portrait, avoid=avoid)
    avoid.add(clip.page)
    return clip


def _music(item_or_slug, cfg: dict, cache_dir: Path) -> tuple[Path | None, list[str]]:
    r = cfg["render"]
    if not r.get("music", True):
        return None, []
    slug = item_or_slug if isinstance(item_or_slug, str) else item_or_slug.slug
    wanted = None if isinstance(item_or_slug, str) else item_or_slug.raw.get("music")
    title = music.pick(slug, wanted, r.get("music_tracks"))
    path = music.fetch(title, cache_dir / "music")
    return path, ([music.credit(title)] if path else [])


# ---------------------------------------------------------------- the Short

def outro_line(cfg: dict) -> str:
    return cfg.get("clips", {}).get("outro", f"Subscribe to {cfg['name']} for a new one every day.")


def short_sentences(item: ClipItem, cfg: dict) -> list[str]:
    """Everything the narrator says in this Short, for warming the voice cache ahead of the render."""
    return [s for sc in item.scenes for s in sc.sentences] + [outro_line(cfg)]


def render_clip_short(item: ClipItem, cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> RenderResult:
    r = cfg["render"]
    size, fps, accent = SHORT, r.get("fps", 30), hex_rgb(r["accent"])
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    avoid = _clips_used(item.path.parent.parent)
    scenes = []
    for i, s in enumerate(item.scenes, 1):
        print(f"  scene {i}/{len(item.scenes)}: footage for {s.video[0]!r}")
        sentences = s.sentences
        scenes.append(Scene(_find(s, cache_dir, True, avoid), sentences, _say_all(narrator, sentences),
                            r.get("sentence_pause", 0.15)))
    last = scenes[-1]
    last.subscribe_from = sum(len(v) / audio.SR + last.pause for v in last.voices)
    last.sentences = [*last.sentences, outro_line(cfg)]
    last.voices = [*last.voices, narrator.say(outro_line(cfg))]
    last.pause = max(last.pause, 0.5)

    sub_png = _subscribe_png(work / "subscribe-early.png", True)
    sub_w = Image.open(sub_png).width
    _subscribe_early(scenes, r.get("subscribe_at", 3.0), r.get("subscribe_seconds", 3.5), sub_png,
                     ((size[0] - sub_w) // 2, int(size[1] * 0.30)))
    header = _header_png(item.title, cfg.get("thumbnail_label", cfg["name"].upper()), accent, work / "header.png", size)
    captions: list[str] = []
    print(f"  encoding {len(scenes)} scenes")
    segments, track, _ = _build(scenes, size, fps, accent, work, captions, header)
    seconds = len(track) / audio.SR
    if seconds > MAX_SHORT_SECONDS:
        from .checks import CheckFailed

        raise CheckFailed(f"the Short runs {seconds:.0f} s; cut words so it stays under {MAX_SHORT_SECONDS} s")
    tune, music_credits = _music(item, cfg, cache_dir)
    video, seconds = mux_segments(segments, track, out_dir, music=tune)
    srt = out_dir / "captions.srt"
    srt.write_text("\n".join(captions), encoding="utf-8")
    frame = _grab(segments[0], 0.5, work / "first.png")
    thumb = out_dir / "thumbnail.jpg"
    Image.open(frame).convert("RGB").save(thumb, quality=90)
    return RenderResult(video, thumb, srt, seconds, [sc.clip.description_line for sc in scenes], [],
                        music_credits, record={"clips": [sc.clip.page for sc in scenes]})


# ---------------------------------------------------------------- the weekly compilation

def compilation_title(cfg: dict, items: list[ClipItem]) -> str:
    template = cfg.get("compilation", {}).get("title", "{n} Times Nature Showed Its Power: {first} and More")
    return template.format(n=len(items), first=items[0].title, name=cfg["name"])[:100]


def compilation_intro(cfg: dict, items: list[ClipItem]) -> list[str]:
    names = [i.title.rstrip(".!?") for i in items[:2]]
    more = f" And {len(items) - 2} more." if len(items) > 2 else ""
    lines = [f"{len(items)} moments when nature took over.", ". ".join(names) + "." + more,
             cfg.get("compilation", {}).get("subscribe", f"If you like this, subscribe to {cfg['name']}. "
                                                          "There's a new one every day.")]
    return [s for line in lines for s in split_sentences(line)]


def compilation_outro(cfg: dict) -> list[str]:
    return split_sentences(cfg.get("compilation", {}).get(
        "outro", "That's the week. Tell us in the comments which one hit hardest, and subscribe so you catch the next one."))


def compilation_sentences(cfg: dict, items: list[ClipItem]) -> list[str]:
    return compilation_intro(cfg, items) + [s for i in items for sc in i.scenes for s in sc.sentences] + \
        compilation_outro(cfg)


def render_compilation(items: list[ClipItem], cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> RenderResult:
    """The week's Shorts as one landscape video: a short intro with the subscribe ask, then each Short as a chapter."""
    r = cfg["render"]
    size, fps, accent = WIDE, r.get("fps", 30), hex_rgb(r["accent"])
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    pause = r.get("sentence_pause", 0.15) + 0.15
    avoid: set[str] = set()
    scenes: list[Scene] = []
    starts: list[tuple[int, str]] = []

    intro = compilation_intro(cfg, items)
    opener = _find(items[0].scenes[0], cache_dir, False, avoid)
    scenes.append(Scene(opener, intro, _say_all(narrator, intro), pause))
    for n, item in enumerate(items, 1):
        print(f"  chapter {n}/{len(items)}: {item.title}")
        starts.append((len(scenes), item.title))
        for k, s in enumerate(item.scenes):
            sentences = s.sentences
            scenes.append(Scene(_find(s, cache_dir, False, avoid), sentences, _say_all(narrator, sentences), pause))
            if k == 0:
                png, x, y = _chapter_png(n, item.title, accent, work / f"chapter{n:02d}.png", size)
                scenes[-1].extra.append(Layer(png, x, y, 0, 3.0, fade=0.3))
        scenes[-1].pause = 0.9  # a breath between moments
    outro = compilation_outro(cfg)
    scenes.append(Scene(scenes[-1].clip, outro, _say_all(narrator, outro), 1.2, subscribe_from=0.0))

    sub_png = _subscribe_png(work / "subscribe-early.png", False)
    sub_w = Image.open(sub_png).width
    ask = next((k for k, line in enumerate(intro) if "subscribe" in line.lower()), 1)
    ask_at = sum(len(v) / audio.SR + pause for v in scenes[0].voices[:ask])
    _subscribe_early(scenes, ask_at, 5.0, sub_png, (size[0] - sub_w - 60, 60))  # while the ask is spoken
    captions: list[str] = []
    print(f"  encoding {len(scenes)} scenes")
    segments, track, scene_starts = _build(scenes, size, fps, accent, work, captions, None)
    chapters = [(0.0, "Intro")] + [(scene_starts[i], title) for i, title in starts]
    tune, music_credits = _music(f"compilation-{items[0].slug}", cfg, cache_dir)
    video, seconds = mux_segments(segments, track, out_dir, music=tune)
    srt = out_dir / "captions.srt"
    srt.write_text("\n".join(captions), encoding="utf-8")
    still = Image.open(_grab(scenes[1].clip.path, 1.0, work / "thumb-bg.png")).convert("RGB")  # the footage alone
    thumb = thumbnail(still, items[0].raw.get("thumbnail_text") or items[0].title, f"{len(items)} CLIPS",
                      r["accent"], out_dir / "thumbnail.jpg", label=cfg.get("thumbnail_label", cfg["name"].upper()))
    credits = list(dict.fromkeys(sc.clip.description_line for sc in scenes))
    return RenderResult(video, thumb, srt, seconds, credits, chapters, music_credits,
                        record={"clips": list(dict.fromkeys(sc.clip.page for sc in scenes))})
