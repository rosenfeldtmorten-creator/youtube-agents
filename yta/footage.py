"""Real video footage (b-roll) for photo and card scenes, only from sources whose licence allows reuse.

Sources, tried in order for each search:
  1. Pexels videos   (free API key in PEXELS_API_KEY; Pexels licence: free to use, credit given anyway)
  2. Pixabay videos  (free API key in PIXABAY_API_KEY; Pixabay content licence, credit given anyway)
  3. Wikimedia Commons videos (no key; public domain, CC0, CC BY or CC BY-SA only)
Never clips cut from other people's YouTube videos. Each clip is credited on screen and in the description."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from .photos import HEADERS, _strip_html, is_free
from .visuals import font

COMMONS = "https://commons.wikimedia.org/w/api.php"
MIN_WIDTH = 1280


@dataclass
class Clip:
    path: Path
    title: str
    author: str
    licence: str
    page: str
    source: str

    @property
    def credit(self) -> str:
        return f"Video: {self.author} / {self.source}"

    @property
    def description_line(self) -> str:
        name = self.title if len(self.title) <= 60 else self.title[:57].rsplit(" ", 1)[0] + "..."
        return f"{name} (video): {self.author}, {self.licence}, {self.page}"


def _pexels(query: str) -> dict | None:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return None
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": "landscape", "per_page": 15})
    r.raise_for_status()
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if (f.get("width") or 0) >= MIN_WIDTH and f.get("file_type") == "video/mp4"]
        if files and v.get("duration", 0) >= 4:
            f = min(files, key=lambda f: f["width"])  # the smallest file that is still sharp at 1080p
            return {"url": f["link"], "title": query.capitalize(), "author": v.get("user", {}).get("name", "Pexels"),
                    "licence": "Pexels License", "page": v.get("url", ""), "source": "Pexels"}
    return None


def _pixabay(query: str) -> dict | None:
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None
    r = requests.get("https://pixabay.com/api/videos/", timeout=30,
                     params={"key": key, "q": query, "safesearch": "true", "per_page": 15})
    r.raise_for_status()
    for v in r.json().get("hits", []):
        sizes = [s for s in v.get("videos", {}).values() if (s.get("width") or 0) >= MIN_WIDTH and s.get("url")]
        if sizes and v.get("duration", 0) >= 4:
            s = min(sizes, key=lambda s: s["width"])
            return {"url": s["url"], "title": query.capitalize(), "author": v.get("user", "Pixabay"),
                    "licence": "Pixabay Content License", "page": v.get("pageURL", ""), "source": "Pixabay"}
    return None


def _commons(query: str) -> dict | None:
    r = requests.get(COMMONS, headers=HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime"})
    r.raise_for_status()
    pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        licence = meta.get("LicenseShortName", {}).get("value", "")
        if not (str(info.get("mime", "")).startswith(("video/webm", "video/ogg")) and is_free(licence)):
            continue
        if info.get("width", 0) < MIN_WIDTH or info.get("width", 0) < info.get("height", 1):
            continue
        if not 4 <= float(info.get("duration") or 0) <= 600:
            continue
        artist = _strip_html(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        title = re.sub(r"\.(webm|ogv|ogg)$", "", page["title"].removeprefix("File:"), flags=re.I)
        return {"url": info["url"], "title": title, "author": artist[:80], "licence": licence,
                "page": info.get("descriptionurl", ""), "source": "Wikimedia Commons"}
    return None


SOURCES = (_pexels, _pixabay, _commons)


def find(query: str, cache_dir: Path) -> Clip:
    """The first freely licensed landscape clip for a search, downloaded once and cached."""
    key = hashlib.sha1(query.encode()).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = cache_dir / f"{key}.json"
    if not meta_path.exists():
        errors, found = [], None
        for source in SOURCES:
            try:
                found = source(query)
            except Exception as exc:  # one source down shouldn't stop the others
                errors.append(f"{source.__name__.strip('_')}: {exc}")
            if found:
                break
        if not found:
            raise LookupError(f"no freely licensed video for '{query}'" + (f" ({'; '.join(errors)})" if errors else ""))
        ext = ".mp4" if found["url"].split("?")[0].endswith(".mp4") else ".webm"
        clip_path = cache_dir / f"{key}{ext}"
        with requests.get(found["url"], headers=HEADERS, timeout=120, stream=True) as r:
            r.raise_for_status()
            with open(clip_path, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        found["file"] = clip_path.name
        meta_path.write_text(json.dumps(found))
    m = json.loads(meta_path.read_text())
    return Clip(cache_dir / m["file"], m["title"], m["author"], m["licence"], m["page"], m["source"])


def clip_for(chart: dict, cache_dir: Path) -> Clip:
    """The clip a scene asks for with "video": a search string or a list of searches tried in order."""
    wants = chart["video"] if isinstance(chart["video"], list) else [chart["video"]]
    errors = []
    for want in wants:
        try:
            return find(str(want), cache_dir)
        except Exception as exc:
            errors.append(str(exc))
    raise LookupError("; ".join(errors))


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out or 0)


def _overlay(size: tuple[int, int], caption: str, credit: str) -> Image.Image:
    """Bottom fade, caption and credit, drawn once and laid over every frame of the clip."""
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(int(h * 0.62), h):
        d.line((0, y, w, y), fill=(14, 23, 38, int(225 * (y - h * 0.62) / (h * 0.38))))
    if caption:
        d.text((96, h - 150), caption, font=font(56, "bold"), fill=(232, 237, 245, 255), anchor="ls")
    d.text((w - 48, h - 40), credit, font=font(24), fill=(200, 208, 220, 230), anchor="rs")
    return layer


def segment(clip: Clip, path: Path, size: tuple[int, int], fps: int, seconds: float, caption: str = "",
            title: str = "", label: str = "", accent: tuple[int, int, int] = (242, 179, 61),
            title_seconds: float = 3.0) -> Path:
    """Encode the clip as one scene of exactly `seconds`: cropped to fill the frame, slowed down a little if it is
    short (and looped only if it is much too short), with the caption and credit on top. With a title, the clip
    starts dimmed under the title for title_seconds, like a photo card. Same codec settings as encode_segment,
    so the scenes join without re-encoding."""
    from .photos import _title_layer

    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    overlay = path.with_name(path.stem + "_overlay.png")
    _overlay(size, caption, clip.credit).save(overlay)
    inputs = ["-i", str(overlay)]
    length = duration(clip.path)
    slow = min(1.5, max(1.0, seconds / length)) if length else 1.0
    loop = ["-stream_loop", "-1"] if length * slow < seconds else []
    graph = (f"[0:v]setpts={slow:.4f}*PTS,scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
             f"fps={fps},format=rgba[v0];[v0][1:v]overlay=0:0[v1]")
    last = "v1"
    if title:
        title_png = path.with_name(path.stem + "_title.png")
        dimmed = Image.new("RGBA", size, (14, 23, 38, 158))
        text = _title_layer(size, title, label, accent).convert("RGBA")
        text.putalpha(text.convert("L").point(lambda v: 255 if v > 8 else 0))
        dimmed.alpha_composite(text)
        dimmed.save(title_png)
        inputs += ["-loop", "1", "-t", f"{title_seconds:.2f}", "-i", str(title_png)]
        fade = max(0.0, title_seconds - 0.5)
        graph += f";[2:v]format=rgba,fade=t=out:st={fade:.2f}:d=0.5:alpha=1[t];[v1][t]overlay=0:0:eof_action=pass[v2]"
        last = "v2"
    graph += f";[{last}]format=yuv420p[out]"
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", *loop, "-i", str(clip.path), *inputs,
        "-filter_complex", graph, "-map", "[out]", "-t", f"{seconds:.4f}", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-g", str(fps * 4), "-r", str(fps), str(path),
    ], check=True)
    for p in path.parent.glob(path.stem + "_*.png"):
        p.unlink()
    return path
