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


def _usable(page: dict) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata", {})
    licence = meta.get("LicenseShortName", {}).get("value", "")
    if info.get("mime") not in ("image/jpeg", "image/png") or not is_free(licence):
        return None
    if info.get("width", 0) < 1200 or info.get("width", 0) < info.get("height", 1):  # landscape, sharp enough for 1080p
        return None
    artist = _strip_html(meta.get("Artist", {}).get("value", "")) or _strip_html(meta.get("Credit", {}).get("value", ""))
    return {"title": page["title"], "url": info.get("thumburl") or info["url"], "page": info.get("descriptionurl", ""),
            "licence": licence, "artist": (artist or "Unknown author")[:80]}


def find(chart: dict, cache_dir: Path) -> Photo:
    """The photo a scene asks for: a named Commons file, or the first freely licensed match for a search."""
    want = chart.get("file") or chart.get("query")
    key = hashlib.sha1(want.encode()).hexdigest()[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path, img_path = cache_dir / f"{key}.json", cache_dir / f"{key}.jpg"
    if not meta_path.exists():
        if chart.get("file"):
            title = want if want.startswith("File:") else f"File:{want}"
            candidates = _pages({"titles": title})
        else:
            candidates = _pages({"generator": "search", "gsrsearch": f"{want} filetype:bitmap", "gsrnamespace": 6,
                                 "gsrlimit": 25})
        found = next((u for u in map(_usable, candidates) if u), None)
        if not found:
            raise LookupError(f"no freely licensed landscape photo for '{want}'")
        r = requests.get(found["url"], headers=HEADERS, timeout=60)
        r.raise_for_status()
        img_path.write_bytes(r.content)
        meta_path.write_text(json.dumps(found))
    m = json.loads(meta_path.read_text())
    return Photo(img_path, m["title"], m["artist"], m["licence"], m["page"])


def frames(photo: Photo, caption: str, size: tuple[int, int], seconds: float, out_dir: Path,
           fps: int = 12) -> list[tuple[Path, float]]:
    """A slow push-in on the photo, with the caption and the credit on screen."""
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

    n = max(2, int(seconds * fps))
    out = []
    for i in range(n):
        z = 1.08 - 0.08 * i / (n - 1)  # crop shrinks from the full 108% image toward the centre
        cw, ch = int(w * z), int(h * z)
        left, top = (base.width - cw) // 2, (base.height - ch) // 2
        frame = base.crop((left, top, left + cw, top + ch)).resize(size, Image.BILINEAR).convert("RGBA")
        frame.alpha_composite(overlay)
        path = out_dir / f"photo_{i:04d}.png"  # PNG like every other frame: ffmpeg's concat needs one image codec
        frame.convert("RGB").save(path, compress_level=1)
        out.append((path, seconds / n))
    return out
