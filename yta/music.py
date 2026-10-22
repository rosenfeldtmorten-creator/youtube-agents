"""Background music: Kevin MacLeod tracks (incompetech.com, CC BY 4.0), quiet under the voice and credited."""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

import requests

LICENCE = "Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0"
BASE = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
# Calm, steady tracks that sit under a voice without pulling attention.
TRACKS = ("Floating Cities", "Echoes of Time v2", "Ossuary 6 - Air", "Interloper", "Impact Prelude")


def credit(title: str) -> str:
    return f"{LICENCE}: {title}"


def pick(slug: str, wanted: str | None = None, tracks=None) -> str:
    """The item's own track if it names one, else one of the channel's tracks (or TRACKS), the same one every render."""
    if wanted:
        return wanted
    tracks = tracks or TRACKS
    return tracks[int(hashlib.sha1(slug.encode()).hexdigest(), 16) % len(tracks)]


def fetch(title: str, cache_dir: Path) -> Path | None:
    """The track as a local MP3, or None if it can't be downloaded (the video then has no music)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{title}.mp3"
    if path.exists() and path.stat().st_size > 100_000:
        return path
    try:
        r = requests.get(BASE + quote(title) + ".mp3", timeout=60)
        r.raise_for_status()
        if not r.headers.get("content-type", "audio").startswith("audio") or len(r.content) < 100_000:
            raise ValueError("not an audio file")
        path.write_bytes(r.content)
        return path
    except Exception as exc:  # music is a nice-to-have; never stop a render for it
        print(f"  music: could not get '{title}' ({exc}); rendering without music")
        return None
