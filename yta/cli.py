"""Command line: check the queue, or render and publish the next video for a channel.

    python -m yta check  --channel english-stories
    python -m yta run    --channel english-stories [--no-upload] [--voice silent] [--force]
    python -m yta render --channel english-stories --item path/to/story.json --voice silent
    python -m yta snapshot   # save a copy of every data series in use (data/snapshot), for offline checks
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import yaml

from . import checks
from .formats import FORMATS, LOAD_ERRORS

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
    fmt = FORMATS[cfg["format"]]
    items, bad, earlier = queue_items(channel_dir), 0, []
    for item in items:
        try:
            obj = fmt.load(item)
            summary = fmt.check(obj, channel_dir, cfg, earlier, ROOT / ".cache")
            earlier.append(obj)
            print(f"ok   {item.name}  ({summary})")
        except LOAD_ERRORS as exc:
            bad += 1
            print(f"FAIL {item.name}: {exc}")
    due, why = checks.upload_due(channel_dir, cfg["cadence"])
    print(f"{len(items)} queued, {bad} failing. Next upload: {'today' if due else why}.")
    return 1 if bad else 0


def render_item(obj, channel_dir: Path, cfg: dict, voice: str | None, test: bool = False):
    from .tts import make_narrator

    cache = ROOT / ".cache"
    narrator = make_narrator(cfg["voice"], ROOT, backend=voice, cache_dir=cache / "voice", allow_default_voice=test)
    out_dir = ROOT / "out" / channel_dir.name / obj.slug
    print(f"Rendering '{obj.title}'")
    result = FORMATS[cfg["format"]].render(obj, cfg, narrator, out_dir, cache)
    print(f"Rendered {result.video} ({result.seconds / 60:.1f} min)")
    return result


def cmd_render(args) -> int:
    channel_dir, cfg = load_channel(args.channel)
    fmt = FORMATS[cfg["format"]]
    obj = fmt.load(Path(args.item))
    if cfg["format"] == "episode":
        obj.load_data(ROOT / ".cache" / "data")
    render_item(obj, channel_dir, cfg, args.voice, test=True)
    return 0


def cmd_run(args) -> int:
    channel_dir, cfg = load_channel(args.channel)
    fmt = FORMATS[cfg["format"]]
    due, why = checks.upload_due(channel_dir, cfg["cadence"])
    if not due and not args.force:
        print(f"Nothing to do: {why}.")
        return 0

    for item in queue_items(channel_dir):
        try:
            obj = fmt.load(item)
            fmt.check(obj, channel_dir, cfg, [], ROOT / ".cache")
        except LOAD_ERRORS as exc:
            if "could not download" in str(exc):
                print(f"Skipping {item.name} for now: {exc}")
                continue
            reject(item, channel_dir, str(exc))
            continue

        result = render_item(obj, channel_dir, cfg, args.voice, test=args.no_upload)
        try:
            checks.check_duration(result.seconds, cfg["render"])
        except checks.CheckFailed as exc:
            reject(item, channel_dir, str(exc))
            continue

        from . import upload

        description = upload.build_description(
            obj.description, result.chapters, fmt.extra_description(obj, result), cfg["description_footer"],
            fmt.hashtags(obj),
        )
        result.video.with_name("description.txt").write_text(description, encoding="utf-8")
        if args.no_upload:
            print("Test render only: nothing uploaded, queue unchanged.")
            return 0

        yt = cfg["youtube"]
        client = upload.youtube_client(yt["refresh_token_secret"])
        video_id = upload.upload_video(client, result.video, obj.title, description, obj.tags, yt)
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

    print("Queue is empty: the writing task needs to add more.")
    return 0


def cmd_snapshot(args) -> int:
    """Refresh data/snapshot with every series listed in data/series.json or used by any episode."""
    from .data import refresh_snapshot

    specs = list(json.loads((ROOT / "data" / "series.json").read_text()).values())
    for path in sorted(ROOT.glob("channels/*/*/*.json")):
        try:
            specs += list(json.loads(path.read_text(encoding="utf-8")).get("data", {}).values())
        except (json.JSONDecodeError, AttributeError):
            continue
    saved, failed = refresh_snapshot(specs)
    print(f"Saved {saved} series to data/snapshot.")
    for f in failed:
        print(f"FAIL {f}")
    return 1 if failed and not saved else 0


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
    sub.add_parser("snapshot")
    args = p.parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "render": cmd_render, "snapshot": cmd_snapshot}[args.cmd](args)
