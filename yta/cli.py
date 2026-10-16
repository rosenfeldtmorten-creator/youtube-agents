"""Command line: check the queue, or render and publish the next video for a channel.

    python -m yta check  --channel english-stories
    python -m yta run    --channel english-stories [--no-upload] [--voice silent] [--force]
    python -m yta render --channel english-stories --item path/to/story.json --voice silent
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from . import checks
from .story import StoryError, load_story

ROOT = Path(__file__).resolve().parent.parent


def load_channel(slug: str) -> tuple[Path, dict]:
    channel_dir = ROOT / "channels" / slug
    cfg_path = channel_dir / "channel.yaml"
    if not cfg_path.exists():
        sys.exit(f"No channel '{slug}' (expected {cfg_path})")
    return channel_dir, yaml.safe_load(cfg_path.read_text())


def queue_items(channel_dir: Path) -> list[Path]:
    return sorted((channel_dir / "queue").glob("*.json"))


def reject(item: Path, channel_dir: Path, reason: str) -> None:
    """Move a failed item out of the queue and record why, so the writing task can learn from it."""
    data = json.loads(item.read_text(encoding="utf-8")) if item.exists() else {}
    if isinstance(data, dict):
        data["_rejected"] = {"date": dt.date.today().isoformat(), "reason": reason}
        (channel_dir / "rejected" / item.name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    item.unlink(missing_ok=True)
    print(f"REJECTED {item.name}: {reason}")


def cmd_check(args) -> int:
    channel_dir, cfg = load_channel(args.channel)
    previous = checks.published_stories(channel_dir)
    items, bad = queue_items(channel_dir), 0
    for item in items:
        try:
            story = load_story(item)
            checks.check_level(story, cfg["levels"])
            checks.check_duplicates(story, previous)
            others = [load_story(p) for p in items if p != item]
            checks.check_duplicates(story, [o for o in others if o.path.name < item.name])
            print(f"ok   {item.name}  ({story.level}, {story.word_count} words, {story.avg_sentence_words:.1f} words/sentence)")
        except (StoryError, checks.CheckFailed) as exc:
            bad += 1
            print(f"FAIL {item.name}: {exc}")
    due, why = checks.upload_due(channel_dir, cfg["cadence"])
    print(f"{len(items)} queued, {bad} failing. Next upload: {'today' if due else why}.")
    return 1 if bad else 0


def render_item(item: Path, channel_dir: Path, cfg: dict, voice: str | None, test: bool = False):
    from .render import render_story
    from .tts import make_narrator

    story = load_story(item)
    cache = ROOT / ".cache"
    narrator = make_narrator(cfg["voice"], ROOT, backend=voice, cache_dir=cache / "voice", allow_default_voice=test)
    out_dir = ROOT / "out" / channel_dir.name / story.slug
    print(f"Rendering '{story.title}' ({story.level}, {story.word_count} words)")
    result = render_story(story, cfg, narrator, out_dir, cache)
    print(f"Rendered {result.video} ({result.seconds / 60:.1f} min)")
    return story, result


def cmd_render(args) -> int:
    channel_dir, cfg = load_channel(args.channel)
    render_item(Path(args.item), channel_dir, cfg, args.voice, test=True)
    return 0


def cmd_run(args) -> int:
    channel_dir, cfg = load_channel(args.channel)
    due, why = checks.upload_due(channel_dir, cfg["cadence"])
    if not due and not args.force:
        print(f"Nothing to do: {why}.")
        return 0

    for item in queue_items(channel_dir):
        try:
            story = load_story(item)
            checks.check_story(story, channel_dir, cfg)
        except (StoryError, checks.CheckFailed) as exc:
            reject(item, channel_dir, str(exc))
            continue

        story, result = render_item(item, channel_dir, cfg, args.voice, test=args.no_upload)
        try:
            checks.check_duration(result.seconds, cfg["render"])
        except checks.CheckFailed as exc:
            reject(item, channel_dir, str(exc))
            continue

        if args.no_upload:
            print("Test render only: nothing uploaded, queue unchanged.")
            return 0

        from . import upload

        yt = cfg["youtube"]
        vocab = "Key words:\n" + "\n".join(f"- {v['word']}: {v['meaning']}" for v in story.vocabulary)
        credits = "Photos: " + "; ".join(result.photo_credits) if result.photo_credits else ""
        description = upload.build_description(story.description, result.chapters, [vocab, credits], cfg["description_footer"])
        client = upload.youtube_client(yt["refresh_token_secret"])
        video_id = upload.upload_video(client, result.video, story.title, description, story.tags, yt)
        print(f"Uploaded: https://youtu.be/{video_id}")
        upload.set_thumbnail(client, video_id, result.thumbnail)
        if yt.get("upload_captions"):
            upload.upload_captions(client, video_id, result.captions, yt.get("language", "en"))

        data = json.loads(item.read_text(encoding="utf-8"))
        data["_published"] = {
            "date": dt.date.today().isoformat(),
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "minutes": round(result.seconds / 60, 1),
        }
        (channel_dir / "published" / item.name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        item.unlink()
        return 0

    print("Queue is empty: the writing task needs to add stories.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="yta", description="YouTube channel agents")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("--channel", required=True)
        if name != "check":
            sp.add_argument("--voice", choices=["chatterbox", "espeak", "silent"], help="override the channel's voice backend")
        if name == "run":
            sp.add_argument("--no-upload", action="store_true", help="render only; leave the queue as it is")
            sp.add_argument("--force", action="store_true", help="ignore the pacing rules (for tests)")
        if name == "render":
            sp.add_argument("--item", required=True)
    args = p.parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "render": cmd_render}[args.cmd](args)
