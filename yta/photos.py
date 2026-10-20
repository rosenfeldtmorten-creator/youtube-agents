"""Real photos from Wikimedia Commons, only with licences that allow reuse, credited on screen and in the description."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from .visuals import cover, font

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "EconomicsInCharts/1.0 (https://github.com/rosenfeldtmorten-creator/youtube-agents)"}
FREE = re.compile(r"^(public domain|pd\b|cc0|cc by(-sa)? \d)", re.I)


@dataclass
class Photo:
    path: Path
    title: str
    artist: str
    licence: str
    page: str

    @property
    def credit(self) -> str:
        return f"{self.artist} / {self.licence} / Wikimedia Commons"

    @property
    def description_line(self) -> str:
        name = re.sub(r"\.(jpe?g|png)$", "", self.title.removeprefix("File:"), flags=re.I).split(" - NARA")[0]
        if len(name) > 60:
            name = name[:57].rsplit(" ", 1)[0] + "..."
        return f"{name}: {self.artist}, {self.licence}, {self.page}"


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()


def is_free(licence: str) -> bool:
    return bool(FREE.match(licence.strip())) and not re.search(r"\b(NC|ND)\b", licence)


def _pages(params: dict) -> list[dict]:
    base = {"action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": 2400}
    r = requests.get(API, params={**base, **params}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    return sorted(pages.values(), key=lambda p: p.get("index", 0))


def _year(meta: dict) -> int | None:
    m = re.search(r"(19|20)\d\d", _strip_html(meta.get("DateTimeOriginal", {}).get("value", "")))
    return int(m.group(0)) if m else None


def _usable(page: dict, after: int | None = None) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {})
    licence = meta.get("LicenseShortName", {}).get("value", "")
    if info.get("mime") not in ("image/jpeg", "image/png") or not is_free(licence):
        return None
    if after and (_year(meta) or 0) < after:  # e.g. a 1970s petrol pump for a story about this year's prices
        return None
    if info.get("width", 0) < 1200 or info.get("width", 0) < info.get("height", 1):  # landscape, sharp enough for 1080p
        return None
    artist = _strip_html(meta.get("Artist", {}).get("value", "")) or _strip_html(meta.get("Credit", {}).get("value", ""))
    return {"title": page["title"], "url": info.get("thumburl") or info["url"], "page": info.get("descriptionurl", ""),
            "licence": licence, "artist": (artist or "Unknown author")[:80]}


def find(chart: dict, cache_dir: Path) -> Photo:
    """The photo a scene asks for: a named Commons file, or the first freely licensed match for a search."""
    want = chart.get("file") or chart.get("query")
    key = hashlib.sha1(f"{want}|{chart.get('after')}".encode()).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path, img_path = cache_dir / f"{key}.json", cache_dir / f"{key}.jpg"
    if not meta_path.exists():
        if chart.get("file"):
            title = want if want.startswith("File:") else f"File:{want}"
            candidates = _pages({"titles": title})
        else:
            candidates = _pages({"generator": "search", "gsrsearch": f"{want} filetype:bitmap", "gsrnamespace": 6,
                                 "gsrlimit": 25})
        found = next((u for u in (_usable(c, chart.get("after")) for c in candidates) if u), None)
        if not found:
            raise LookupError(f"no freely licensed landscape photo for '{want}'")
        r = requests.get(found["url"], headers=HEADERS, timeout=60)
        r.raise_for_status()
        img_path.write_bytes(r.content)
        meta_path.write_text(json.dumps(found))
    m = json.loads(meta_path.read_text())
    return Photo(img_path, m["title"], m["artist"], m["licence"], m["page"])


def photo_for(chart: dict, cache_dir: Path) -> Photo:
    """The photo a card or headlines scene asks for with "photo": a search string, {"query"/"file", "after"},
    or a list of those tried in order until one finds a freely licensed photo."""
    wants = chart["photo"] if isinstance(chart["photo"], list) else [chart["photo"]]
    errors = []
    for want in wants:
        try:
            return find(want if isinstance(want, dict) else {"query": want}, cache_dir)
        except Exception as exc:
            errors.append(str(exc))
    raise LookupError("; ".join(errors))


def _title_layer(size: tuple[int, int], title: str, label: str, accent: tuple[int, int, int]) -> Image.Image:
    from .visuals import draw_rich_text

    w, h = size
    layer = Image.new("RGB", size, (0, 0, 0))
    if label:
        draw_rich_text(layer, label, (160, int(h * 0.26), w - 320, 70), 36, accent, weight="bold", color=accent)
    draw_rich_text(layer, title, (160, int(h * 0.33), w - 320, int(h * 0.4)), 92, accent, weight="bold")
    return layer


def frames(photo: Photo, caption: str, size: tuple[int, int], seconds: float, out_dir: Path, fps: int = 24,
           title: str = "", label: str = "", accent: tuple[int, int, int] = (242, 179, 61),
           title_seconds: float = 3.0) -> list[tuple[Path, float]]:
    """A slow push-in on the photo, with the caption and the credit on screen.

    With a title, the photo starts dimmed under the title, which fades away after title_seconds,
    so no screen holds the same text for long."""
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = size
    base = cover(Image.open(photo.path).convert("RGB"), (int(w * 1.08), int(h * 1.08)))
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(int(h * 0.62), h):  # dark fade at the bottom so the text reads on any photo
        d.line((0, y, w, y), fill=(14, 23, 38, int(225 * (y - h * 0.62) / (h * 0.38))))
    if caption:
        d.text((96, h - 150), caption, font=font(56, "bold"), fill=(232, 237, 245, 255), anchor="ls")
    d.text((w - 48, h - 40), f"Photo: {photo.credit}", font=font(24), fill=(200, 208, 220, 230), anchor="rs")
    text = _title_layer(size, title, label, accent) if title else None
    text_mask = text.convert("L").point(lambda v: 255 if v > 8 else 0) if text else None

    n = max(2, int(seconds * fps))
    out = []
    for i in range(n):
        t = i / fps
        p = i / (n - 1)
        z = 1.08 - 0.08 * (p * p * (3 - 2 * p))  # crop shrinks from the full 108% image toward the centre, easing in and out
        # Fractional crop box: rounding it to whole pixels each frame is what made the push-in shake.
        cw, ch = base.width * z / 1.08, base.height * z / 1.08
        left, top = (base.width - cw) / 2, (base.height - ch) / 2
        frame = base.resize(size, Image.BICUBIC, box=(left, top, left + cw, top + ch))
        if text is not None:
            strength = max(0.0, min(1.0, (title_seconds - t) / 0.5))  # full until the last half second, then fade
            if strength > 0:
                frame = Image.blend(frame, Image.new("RGB", size, (14, 23, 38)), 0.62 * strength)
                frame.paste(Image.blend(frame, text, strength), (0, 0), text_mask)
        frame = frame.convert("RGBA")
        frame.alpha_composite(overlay)
        path = out_dir / f"photo_{i:04d}.jpg"  # one codec per scene is all ffmpeg's concat needs, as each scene is encoded on its own
        frame.convert("RGB").save(path, quality=93)
        out.append((path, seconds / n))
    return out
