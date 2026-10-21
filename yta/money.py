"""Renders a finance episode: narration over charts drawn in R (charts/chart.R)."""
from __future__ import annotations

import re

import csv
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from . import audio, footage, headlines, metrics, music, photos
from .episode import Episode
from .render import RenderResult, _fmt_srt, encode_segment, frame_aligned, mux_segments, remove_dirs
from .story import split_sentences
from .visuals import SlideMaker, dim, draw_rich_text, generated_background, hex_rgb, thumbnail

ROOT = Path(__file__).resolve().parent.parent
CHART_SCRIPT = ROOT / "charts" / "chart.R"
BG = (14, 23, 38)

OUTRO = ("That's it for today. Everything you saw came from public data, and the sources are in the description. "
         "This video is for education only, not financial advice. Subscribe to Economics in Charts for a new one every week.")


def chart_rows(ep: Episode, chart: dict) -> list[dict]:
    """The rows R draws, computed here so that every plotted value comes from the data."""
    kind = chart["type"]
    if kind == "line":
        rows = []
        for name in chart["series"]:
            s = ep.series[name].between(chart.get("from"), chart.get("to"))
            if chart.get("yearly"):
                s = s.yearly()
            if not s.points:
                raise metrics.MetricError(f"{name} has no data between {chart.get('from')} and {chart.get('to')}")
            base = s.at(chart["index"])[1] / 100 if chart.get("index") else 1
            label = chart.get("labels", {}).get(name, s.label)
            rows += [{"x": d.isoformat(), "y": v / base, "group": label, "label": ""} for d, v in s.points]
        return rows
    if kind == "bars":
        return [
            {"x": i, "y": metrics.evaluate(b["value"], ep.series), "group": "", "label": b["label"]}
            for i, b in enumerate(chart["bars"])
        ]
    if kind == "growth":
        monthly = metrics.evaluate(str(chart["monthly"]), ep.series)
        rate = metrics.evaluate(str(chart["rate"]), ep.series)
        years = int(metrics.evaluate(str(chart["years"]), ep.series))
        rows = []
        for y in range(0, years + 1):
            rows.append({"x": y, "y": monthly * 12 * y, "group": "Money you put in", "label": ""})
            rows.append({"x": y, "y": metrics.FUNCTIONS["compound"](monthly, rate, y), "group": "What it grew to", "label": ""})
        return rows
    if kind == "scatter":
        return [
            {"x": xv, "y": yv, "group": "", "label": str(year)}
            for year, xv, yv in metrics.paired_years(ep.series[chart["x"]], ep.series[chart["y"]], chart.get("from"), chart.get("to"))
        ]
    raise ValueError(f"no rows for chart type {kind}")


def annotation_points(ep: Episode, chart: dict, rows: list[dict]) -> list[dict]:
    """Place each callout {"date", "text", optional "series"} on its line, at the nearest data point."""
    points = []
    for a in chart["annotations"]:
        name = a.get("series") or chart["series"][0]
        group = chart.get("labels", {}).get(name, ep.series[name].label)
        line = [r for r in rows if r["group"] == group]
        when = dt.date.fromisoformat(a["date"] if len(a["date"]) > 7 else a["date"] + "-01")
        near = min(line, key=lambda r: abs((dt.date.fromisoformat(r["x"]) - when).days))
        points.append({"x": near["x"], "y": near["y"], "text": a["text"]})
    return points

def shown_numbers(ep: Episode, chart: dict) -> list[tuple[float, bool]]:
    """The numbers a chart prints on screen (line ends, bar values), each with whether it reads as a percent,
    matching what charts/chart.R draws."""
    kind, fmt = chart["type"], chart.get("y_format", "num")
    if kind not in ("line", "bars"):
        return []
    if kind == "bars":
        return [(r["y"] * 100, True) if fmt == "pct" else (r["y"], False) for r in chart_rows(ep, chart)]
    shown = []
    for name in chart["series"]:
        last = max((r for r in chart_rows(ep, {**chart, "series": [name]})), key=lambda r: r["x"])
        if chart.get("index"):
            shown.append((last["y"] - 100, True))
        elif fmt == "pct":
            shown.append((last["y"] * 100, True))
        else:  # a series already in percent (unemployment, mortgage rates) reads as a percent too
            shown.append((last["y"], ep.data[name].get("unit") == "percent"))
    return shown


def check_voice_matches_charts(ep: Episode) -> None:
    """A percent the voice says must not appear on the same chart as a plain number for something else
    (e.g. the voice says houses rose 237 percent while the chart prints 237 next to the pay line)."""
    for i, scene in enumerate(ep.scenes, 1):
        shown = shown_numbers(ep, scene.chart)
        if not shown:
            continue
        said = [float(n.replace(",", "")) for n in re.findall(r"(\d[\d,]*(?:\.\d+)?) percent", scene.filled or "")]
        for p in said:
            as_percent = any(pct and abs(v - p) < 0.6 for v, pct in shown)
            as_level = [v for v, pct in shown if not pct and abs(v - p) < 0.6]
            if as_level and not as_percent:
                raise metrics.MetricError(
                    f"scene {i}: the voice says {p:g} percent, but the chart shows {as_level[0]:,.0f} as a level, "
                    "so viewers will read it as something else. Show the change on the chart or reword the line.")


def draw_chart(ep: Episode, chart: dict, out_dir: Path, n_frames: int, size: tuple[int, int]) -> list[Path]:
    if not shutil.which("Rscript"):
        raise RuntimeError("Rscript not found. Install R with the ggplot2, jsonlite and scales packages.")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = chart_rows(ep, chart)
    data_csv = out_dir / "data.csv"
    with data_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["x", "y", "group", "label"])
        w.writeheader()
        w.writerows(rows)
    spec = dict(chart)
    spec["source_note"] = chart.get("source_note") or "; ".join(
        ep.data[n].get("short_source", "FRED" if ep.data[n]["source"] == "fred" else ep.data[n]["source"])
        for n in (chart.get("series") or [chart[k] for k in ("x", "y") if k in chart] or ep.data.keys())
    )
    if chart["type"] == "line" and chart.get("annotations"):
        spec["annotation_points"] = annotation_points(ep, chart, rows)
    if chart["type"] == "scatter":
        spec["x_label"] = chart.get("x_label") or ep.series[chart["x"]].label
        spec["y_label"] = chart.get("y_label") or ep.series[chart["y"]].label
    spec_json = out_dir / "spec.json"
    spec_json.write_text(json.dumps(spec, ensure_ascii=False))
    subprocess.run(
        ["Rscript", str(CHART_SCRIPT), str(spec_json), str(data_csv), str(out_dir), str(n_frames), str(size[0]), str(size[1])],
        check=True,
    )
    frames = sorted(out_dir.glob("frame_*.png"))
    if len(frames) != n_frames:
        raise RuntimeError(f"chart.R wrote {len(frames)} frames, expected {n_frames}")
    return frames


def card(slides: SlideMaker, text: str, accent_label: str = "") -> Path:
    img = dim(generated_background("money-card", slides.size), 0.55)
    if accent_label:
        draw_rich_text(img, accent_label, (160, int(slides.h * 0.22), slides.w - 320, 80), 36, slides.accent, color=slides.accent, weight="bold")
    draw_rich_text(img, text, (160, int(slides.h * 0.30), slides.w - 320, int(slides.h * 0.45)), 92, slides.accent, weight="bold")
    return slides.save(img)


def render_episode(ep: Episode, cfg: dict, narrator, out_dir: Path, cache_dir: Path) -> RenderResult:
    r = cfg["render"]
    size = (r["width"], r["height"])
    out_dir.mkdir(parents=True, exist_ok=True)
    slides = SlideMaker(size, r["accent"], out_dir / "cards")
    segments: list[Path] = []
    voice_parts: list[np.ndarray] = []
    captions: list[tuple[float, float, str]] = []
    chapters: list[tuple[float, str]] = []
    photo_credits: list[str] = []
    last_photo = None
    t = 0.0
    first_chart: Path | None = None

    outro = {"type": "card", "title_filled": "Thanks for watching", "label": "ECONOMICS IN CHARTS"}
    if ep.raw.get("outro_photo"):
        outro["photo"] = ep.raw["outro_photo"]
    scenes = [(sc.filled, sc.chart) for sc in ep.scenes] + [(OUTRO, outro)]
    for i, (text, chart) in enumerate(scenes, 1):
        print(f"  scene {i}/{len(scenes)} ({chart['type']})")
        scene_audio = []
        for sentence in split_sentences(text):
            voice = narrator.say(sentence)
            start = t + sum(len(a) for a in scene_audio) / audio.SR
            captions.append((start, start + len(voice) / audio.SR, sentence))
            scene_audio += [voice, audio.silence(r["sentence_pause"])]
        scene_audio.append(audio.silence(r["scene_pause"]))
        track = frame_aligned(np.concatenate(scene_audio), r["fps"])
        frames: list[tuple[Path, float]] = []
        seconds = len(track) / audio.SR
        voice_parts.append(track)
        if chart.get("chapter"):
            chapters.append((t, chart["chapter"]))

        # Real footage first where the scene asks for it; the photo below is the fallback if no clip is found.
        ready = None
        if chart.get("video") and chart["type"] in ("photo", "card"):
            try:
                clip = footage.clip_for(chart, cache_dir / "footage")
                ready = footage.segment(clip, out_dir / "segments" / f"{i:02d}.mp4", size, r["fps"], seconds,
                                        caption=chart.get("caption", "") if chart["type"] == "photo" else "",
                                        title=chart.get("title_filled", "") if chart["type"] == "card" else "",
                                        label=chart.get("label", ""), accent=hex_rgb(r["accent"]))
                if clip.description_line not in photo_credits:
                    photo_credits.append(clip.description_line)
            except Exception as exc:  # footage is a bonus; never let it stop a render
                print(f"  video: {exc}; using the photo instead")

        if ready is not None:
            pass
        elif chart["type"] == "headlines":
            background = None
            if chart.get("photo"):
                try:
                    photo = last_photo = photos.photo_for(chart, cache_dir / "photos")
                    background = Image.open(photo.path).convert("RGB")
                    if photo.description_line not in photo_credits:
                        photo_credits.append(photo.description_line)
                except Exception as exc:
                    print(f"  photo: {exc}; plain background behind the headlines")
            frames += headlines.frames(chart["headlines"], size, seconds, out_dir / f"headlines_{i:02d}",
                                       hex_rgb(r["accent"]), background)
        elif chart["type"] == "card" and chart.get("photo"):
            # The title shows for a few seconds over a dimmed photo, then the photo keeps moving on its own.
            try:
                photo = last_photo = photos.photo_for(chart, cache_dir / "photos")
                frames += photos.frames(photo, "", size, seconds, out_dir / f"card_{i:02d}",
                                        title=chart.get("title_filled", ""), label=chart.get("label", ""),
                                        accent=hex_rgb(r["accent"]))
                if photo.description_line not in photo_credits:
                    photo_credits.append(photo.description_line)
            except Exception as exc:
                print(f"  photo: {exc}; " + ("reusing the last photo" if last_photo else "showing a plain title card"))
                if last_photo:  # a moving photo beats a long still title card
                    frames += photos.frames(last_photo, "", size, seconds, out_dir / f"card_{i:02d}",
                                            title=chart.get("title_filled", ""), label=chart.get("label", ""),
                                            accent=hex_rgb(r["accent"]))
                else:
                    frames.append((card(slides, chart.get("title_filled", ""), chart.get("label", "")), seconds))
        elif chart["type"] == "card":
            frames.append((card(slides, chart.get("title_filled", ""), chart.get("label", "")), seconds))
        elif chart["type"] == "photo":
            try:
                photo = last_photo = photos.find(chart, cache_dir / "photos")
                frames += photos.frames(photo, chart.get("caption", ""), size, seconds, out_dir / f"photo_{i:02d}")
                if photo.description_line not in photo_credits:
                    photo_credits.append(photo.description_line)
            except Exception as exc:  # a missing photo should never stop a render
                print(f"  photo: {exc}; showing a title card instead")
                frames.append((card(slides, chart.get("caption", ""), chart.get("label", "")), seconds))
        else:
            n = r["chart_frames"]
            imgs = draw_chart(ep, chart, out_dir / f"chart_{i:02d}", n, size)
            reveal = min(seconds * 0.6, r["chart_reveal_seconds"])
            frames += [(p, reveal / n) for p in imgs[:-1]]
            frames.append((imgs[-1], seconds - reveal * (n - 1) / n))
            if first_chart is None or i == ep.raw.get("thumbnail_scene"):
                first_chart = out_dir / "first_chart.png"
                shutil.copy(imgs[-1], first_chart)
        segments.append(ready or encode_segment(frames, out_dir / "segments" / f"{i:02d}.mp4", r["fps"], seconds))
        # Frames are big (24 a second at full HD); drop them once the scene is encoded so the disk never fills.
        remove_dirs([out_dir / f"{kind}_{i:02d}" for kind in ("chart", "photo", "card", "headlines")])
        t += seconds

    if chapters and chapters[0][0] > 0:
        chapters.insert(0, (0.0, "Introduction"))
    print(f"  joining {len(segments)} scenes")
    track = music.pick(ep.slug, ep.raw.get("music"))
    music_file = music.fetch(track, cache_dir / "music") if r.get("music", True) else None
    video, seconds = mux_segments(segments, np.concatenate(voice_parts), out_dir, music=music_file)

    srt = out_dir / "captions.srt"
    srt.write_text("\n".join(f"{n}\n{_fmt_srt(a)} --> {_fmt_srt(b)}\n{txt}\n" for n, (a, b, txt) in enumerate(captions, 1)),
                   encoding="utf-8")
    bg = Image.open(first_chart).convert("RGB") if first_chart else generated_background(ep.slug, size)
    thumb = thumbnail(bg, ep.thumbnail_text, ep.raw.get("thumbnail_badge_filled"), r["accent"], out_dir / "thumbnail.jpg",
                      label=cfg["thumbnail_label"])
    return RenderResult(video, thumb, srt, seconds, photo_credits, chapters if len(chapters) >= 3 else [],
                        [music.credit(track)] if music_file else [])
