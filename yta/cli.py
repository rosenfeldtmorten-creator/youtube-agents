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


_NARRATORS: dict = {}


def get_narrator(cfg: dict, voice: str | None, test: bool):
    """One narrator per run, so a Short reuses the loaded voice model and its cached sentences."""
    from .tts import make_narrator

    key = (cfg["slug"], voice, test)
    if key not in _NARRATORS:
        _NARRATORS[key] = make_narrator(cfg["voice"], ROOT, backend=voice, cache_dir=ROOT / ".cache" / "voice",
                                        allow_default_voice=test)
    return _NARRATORS[key]


def make_short(obj, channel_dir: Path, cfg: dict, voice: str | None, test: bool):
    """Render the episode's Short, or None if it has none or it can't be made (the long video still goes out)."""
    if not getattr(obj, "raw", {}).get("short"):
        return None
    from .shorts import render_short

    try:
        out_dir = ROOT / "out" / channel_dir.name / obj.slug / "short"
        video, seconds = render_short(obj, obj.raw["short"], cfg, get_narrator(cfg, voice, test), out_dir, ROOT / ".cache")
        print(f"Rendered Short {video} ({seconds:.0f} s)")
        return video
    except Exception as exc:
        print(f"Short skipped: {exc}")
        return None


def render_item(obj, channel_dir: Path, cfg: dict, voice: str | None, test: bool = False):
    cache = ROOT / ".cache"
    narrator = get_narrator(cfg, voice, test)
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
        short = make_short(obj, channel_dir, cfg, args.voice, test=args.no_upload)
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
        upload.engage(client, video_id, cfg, obj.raw.get("comment", ""))

        data = json.loads(item.read_text(encoding="utf-8"))
        data["_published"] = {
            "date": dt.date.today().isoformat(),
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
            "minutes": round(result.seconds / 60, 1),
        }
        if short:
            from .shorts import short_description

            try:
                short_id = upload.upload_video(client, short, f"{obj.raw['short']['title']} #Shorts",
                                               short_description(obj, video_id), obj.tags, yt)
                data["_published"]["short_url"] = f"https://youtube.com/shorts/{short_id}"
                upload.engage(client, short_id, cfg, short=True)
                print(f"Uploaded Short: https://youtube.com/shorts/{short_id}")
            except Exception as exc:  # the long video is already up; don't lose its record over the Short
                print(f"Short not uploaded: {exc}")
        (channel_dir / "published" / item.name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        item.unlink()
        return 0

    print("Queue is empty: the writing task needs to add more.")
    return 0


def cmd_narrate(args) -> int:
    """Speak every sentence of the next episode (or the next --episodes N) into the narration cache.

    The workflows save the cache right after this step, so a render that later fails (full disk, timeout)
    never throws away an hour of voice synthesis. The Prepare voices workflow runs it ahead of time, so
    an upload day only has to render."""
    channel_dir, cfg = load_channel(args.channel)
    fmt = FORMATS[cfg["format"]]
    if cfg["format"] != "episode":
        print("Narration warm-up is only needed for finance episodes.")
        return 0
    from .money import OUTRO
    from .shorts import OUTRO as SHORT_OUTRO
    from .story import split_sentences

    wanted, done_episodes = getattr(args, "episodes", 1) or 1, 0
    for item in queue_items(channel_dir):
        try:
            obj = fmt.load(item)
            fmt.check(obj, channel_dir, cfg, [], ROOT / ".cache")
        except LOAD_ERRORS as exc:
            print(f"Skipping {item.name}: {exc}")
            continue
        narrator = get_narrator(cfg, args.voice, test=False)
        sentences = [s for sc in obj.scenes for s in split_sentences(sc.filled or sc.narration)]
        sentences += split_sentences(OUTRO) + ([SHORT_OUTRO] if obj.raw.get("short") else [])
        import time

        began = time.time()
        for k, sentence in enumerate(sentences, 1):
            narrator.say(sentence)
            print(f"  {k}/{len(sentences)} ({time.time() - began:.0f} s)", flush=True)
        spoken = time.time() - began
        print(f"::notice title=Narration ({obj.slug})::{len(sentences)} sentences in {spoken / 60:.0f} min")
        if narrator.enhance:
            began = time.time()
            try:
                done = narrator.enhance_cached(sentences)
                print(f"::notice title=Voice restoration::{done} sentences restored in {(time.time() - began) / 60:.0f} min")
            except Exception as exc:  # the video still works with the plain voice
                print(f"::warning title=Voice restoration skipped::{exc}")
        done_episodes += 1
        if done_episodes >= wanted:
            return 0
    if done_episodes:
        return 0
    print("Nothing queued to narrate.")
    return 0


def shorts_today(channel_dir: Path) -> bool:
    """True if a Short already went up today, with a video or on its own."""
    today = dt.date.today().isoformat()
    for p in (channel_dir / "published").glob("*.json"):
        meta = json.loads(p.read_text(encoding="utf-8")).get("_published", {})
        if meta.get("date") == today and meta.get("short_url"):
            return True
        if any(s.get("date") == today for s in meta.get("shorts", [])):
            return True
    return False


def cmd_short(args) -> int:
    """Post one Short a day, cut from a video that is already up (newest video first), and record it."""
    channel_dir, cfg = load_channel(args.channel)
    if cfg["format"] != "episode":
        print("Daily Shorts are only made for finance episodes.")
        return 0
    if shorts_today(channel_dir) and not args.force:
        print("Nothing to do: a Short already went up today.")
        return 0
    from .shorts import candidates, render_short, short_description, split_sentences, tidy_opening

    fmt = FORMATS[cfg["format"]]
    narrator = get_narrator(cfg, args.voice, test=args.no_upload)
    for path in sorted((channel_dir / "published").glob("*.json"), reverse=True):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("_published", {})
        done = {tuple(s["scenes"]) for s in meta.get("shorts", [])}
        try:
            ep = fmt.load(path)
            ep.load_data(ROOT / ".cache" / "data")
            from .money import check_voice_matches_charts

            check_voice_matches_charts(ep)  # the same voice-versus-chart check every video passes
        except Exception as exc:  # e.g. a claim the newest data no longer supports
            print(f"Skipping {path.name}: {exc}")
            continue
        for pick in candidates(ep):
            if tuple(pick["scenes"]) in done:
                continue
            sentences = []
            for k, i in enumerate(pick["scenes"], 1):
                scene = ep.scenes[i - 1]
                said = split_sentences(scene.filled or scene.narration)
                sentences += tidy_opening(said) if k == 1 else said
            if narrator.enhance:  # restore any sentence the long video didn't already need
                for sentence in sentences:
                    narrator.say(sentence)
                try:
                    narrator.enhance_cached(sentences)
                except Exception as exc:
                    print(f"::warning title=Voice restoration skipped::{exc}")
            out_dir = ROOT / "out" / channel_dir.name / ep.slug / f"short-{'-'.join(map(str, pick['scenes']))}"
            try:
                video, seconds = render_short(ep, pick, cfg, narrator, out_dir, ROOT / ".cache")
            except ValueError as exc:  # too long for a Short; try the next scene
                print(f"Skipping scenes {pick['scenes']} of {ep.slug}: {exc}")
                continue
            print(f"Rendered Short '{pick['title']}' from {ep.slug} ({seconds:.0f} s)")
            if args.no_upload:
                print("Test render only: nothing uploaded.")
                return 0
            from . import upload

            yt = cfg["youtube"]
            client = upload.youtube_client(yt["refresh_token_secret"])
            short_id = upload.upload_video(client, video, f"{pick['title']} #Shorts",
                                           short_description(ep, meta["video_id"]), ep.tags, yt)
            url = f"https://youtube.com/shorts/{short_id}"
            upload.engage(client, short_id, cfg, short=True)
            meta.setdefault("shorts", []).append({"date": dt.date.today().isoformat(), "scenes": pick["scenes"],
                                                  "title": pick["title"], "url": url})
            data["_published"] = meta
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"::notice title=Short uploaded::{pick['title']} {url}")
            return 0
    print("::warning title=No Short left::every published video has used up its Shorts; add \"shorts\" to an episode")
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
    for name in ("check", "run", "render", "narrate", "short"):
        sp = sub.add_parser(name)
        sp.add_argument("--channel", required=True)
        if name != "check":
            sp.add_argument("--voice", choices=["chatterbox", "espeak", "silent"], help="override the channel's voice backend")
        if name in ("run", "short"):
            sp.add_argument("--no-upload", action="store_true", help="render only; leave the queue as it is")
            sp.add_argument("--force", action="store_true", help="ignore the pacing rules (for tests)")
        if name == "render":
            sp.add_argument("--item", required=True)
        if name == "narrate":
            sp.add_argument("--episodes", type=int, default=1, help="how many queued episodes to narrate")
    sub.add_parser("snapshot")
    args = p.parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "render": cmd_render, "snapshot": cmd_snapshot,
            "narrate": cmd_narrate, "short": cmd_short}[args.cmd](args)
