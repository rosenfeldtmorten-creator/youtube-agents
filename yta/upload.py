"""Uploads to YouTube with the Data API v3, using a stored OAuth refresh token per channel."""
from __future__ import annotations

import os
import time
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


class UploadError(RuntimeError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise UploadError(f"Missing secret {name}. Add it under the repository's Settings > Secrets > Actions (see docs/SETUP.md).")
    return value


def youtube_client(refresh_token_secret: str):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        None,
        refresh_token=_env(refresh_token_secret),
        client_id=_env("YT_CLIENT_ID"),
        client_secret=_env("YT_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build_description(intro: str, chapters, extra_sections: list[str], footer: str, hashtags: list[str] = ()) -> str:
    tags = " ".join(f"#{t}" for t in hashtags)
    parts = [p for p in (tags, intro.strip()) if p]
    if len(chapters) >= 3:
        parts.append("CHAPTERS\n" + "\n".join(f"{format_timestamp(t)} {name}" for t, name in chapters))
    parts += [s.strip() for s in extra_sections if s.strip()]
    parts.append(footer.strip())
    if tags:
        parts.append(tags)
    text = "\n\n".join(parts).replace("<", "").replace(">", "")
    return text[:4900]


def upload_video(client, video: Path, title: str, description: str, tags: list[str], yt_cfg: dict) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": yt_cfg.get("category_id", "27"),
            "defaultLanguage": yt_cfg.get("language", "en"),
            "defaultAudioLanguage": yt_cfg.get("language", "en"),
        },
        "status": {
            "privacyStatus": yt_cfg.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(yt_cfg.get("made_for_kids", False)),
            "containsSyntheticMedia": bool(yt_cfg.get("contains_synthetic_media", True)),
        },
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    request = client.videos().insert(part="snippet,status", body=body, media_body=media)
    response, retries = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  uploaded {status.progress():.0%}")
        except Exception as exc:  # network blips: retry a few times with backoff
            retries += 1
            if retries > 5:
                raise UploadError(f"Upload failed: {exc}") from exc
            time.sleep(2 ** retries)
    return response["id"]


def set_thumbnail(client, video_id: str, image: Path) -> None:
    from googleapiclient.http import MediaFileUpload

    try:
        client.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(image), mimetype="image/jpeg")).execute()
    except Exception as exc:  # custom thumbnails need a phone-verified channel; the video is still fine
        print(f"  thumbnail not set ({exc}). Verify the channel's phone number to allow custom thumbnails.")


def upload_captions(client, video_id: str, srt: Path, language: str = "en") -> None:
    from googleapiclient.http import MediaFileUpload

    try:
        client.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "language": language, "name": "English", "isDraft": False}},
            media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
        ).execute()
    except Exception as exc:
        print(f"  captions not uploaded ({exc}); subtitles are still burned into the video")
