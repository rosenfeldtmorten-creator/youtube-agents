"""Background music: Kevin MacLeod tracks (incompetech.com, CC BY 4.0), quiet under the voice and credited."""
from __future__ import annotations

import glob
import hashlib
from pathlib import Path
from urllib.parse import quote

import requests

LICENCE = "Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0"
BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
COMMONS = "https://commons.wikimedia.org/w/api.php"  # mirrors many of the same tracks; used when incompetech won't serve
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
MIN_BYTES = 100_000
# Calm, steady tracks that sit under a voice without pulling attention.
TRACKS = ("Floating Cities", "Echoes of Time v2", "Ossuary 6 - Air", "Interloper", "Impact Prelude")


def credit(title: str) -> str:
    return f"{LICENCE}: {title}"


def pick(slug: str, wanted: str | None = None) -> str:
    if wanted:
        return wanted
    return TRACKS[int(hashlib.sha1(slug.encode()).hexdigest(), 16) % len(TRACKS)]


def _is_audio(r: requests.Response) -> bool:
    """A real audio file, not an error or bot-check page sent with status 200."""
    head = r.content[:16]
    looks = head.startswith((b"ID3", b"OggS", b"fLaC", b"RIFF")) or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    return looks and len(r.content) >= MIN_BYTES


def _incompetech(title: str) -> tuple[bytes, str]:
    r = requests.get(BASE + quote(title) + ".mp3", headers=BROWSER, timeout=60)
    r.raise_for_status()
    if not _is_audio(r):
        raise ValueError(f"incompetech sent {r.headers.get('content-type', '?')}, not audio")
    return r.content, ".mp3"


def _commons(title: str) -> tuple[bytes, str]:
    from .photos import HEADERS

    r = requests.get(COMMONS, headers=HEADERS, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"Kevin MacLeod {title} filetype:audio",
        "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url"})
    r.raise_for_status()
    want = "".join(ch for ch in title.lower() if ch.isalnum())
    for page in sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        name = "".join(ch for ch in page.get("title", "").lower() if ch.isalnum())
        url = (page.get("imageinfo") or [{}])[0].get("url", "")
        if want in name and "macleod" in name and url.lower().endswith((".ogg", ".oga", ".mp3", ".flac")):
            f = requests.get(url, headers=HEADERS, timeout=60)
            f.raise_for_status()
            if _is_audio(f):
                return f.content, Path(url).suffix.lower()
    raise LookupError("not on Wikimedia Commons")


SOURCES = (_incompetech, _commons)


def fetch(title: str, cache_dir: Path) -> Path | None:
    """The track as a local audio file, or None if no source serves it (the video then has no music)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for cached in cache_dir.glob(f"{glob.escape(title)}.*"):
        if cached.stat().st_size >= MIN_BYTES:
            return cached
    errors = []
    for source in SOURCES:
        try:
            data, ext = source(title)
        except Exception as exc:
            errors.append(f"{source.__name__.strip('_')}: {exc}")
            continue
        path = cache_dir / f"{title}{ext}"
        path.write_bytes(data)
        return path
    # music is a nice-to-have, so never stop a render for it, but say so where the daily health check looks
    print(f"::warning title=No music::could not get '{title}' ({'; '.join(errors)}); rendering without music")
    return None
