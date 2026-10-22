import datetime as dt
import json
import subprocess

import pytest
import yaml

from yta import checks, clips, footage
from yta.cli import ROOT, compilation_pick
from yta.formats import FORMATS
from yta.tts import Narrator, SilentVoice

CHANNEL = ROOT / "channels" / "nature-unleashed"
CFG = yaml.safe_load((CHANNEL / "channel.yaml").read_text())


def _item(tmp_path, **changes):
    data = json.loads(sorted((CHANNEL / "queue").glob("*.json"))[0].read_text())
    data.update(changes)
    p = tmp_path / "queue" / "item.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return clips.load_clips(p)


def test_queued_shorts_pass_the_check(tmp_path):
    fmt = FORMATS["clips"]
    earlier = []
    for p in sorted((CHANNEL / "queue").glob("*.json")):
        item = fmt.load(p)
        fmt.check(item, CHANNEL, CFG, earlier, tmp_path)
        earlier.append(item)
    assert earlier


@pytest.mark.parametrize("change, reason", [
    ({"title": "You Won't Believe This Landslide"}, "clickbait"),
    ({"scenes": [{"narration": "Hit subscribe now, friends, for more of this every single day. " * 2, "video": ["x"]}] * 4},
     "subscribe"),
    ({"scenes": [{"narration": "word " * 20 + ".", "video": ["x"]}] * 4}, "opening line"),
    ({"scenes": [{"narration": "Short line here.", "video": ["x"]}] * 4}, "words of narration"),
])
def test_check_rejects(tmp_path, change, reason):
    with pytest.raises(checks.CheckFailed, match=reason):
        clips.check_script(_item(tmp_path, **change), CFG["script"])


def test_scene_needs_footage_searches(tmp_path):
    with pytest.raises(Exception, match="video"):
        _item(tmp_path, scenes=[{"narration": "No footage."}])


def test_captions_are_a_few_words_with_no_lone_last_word():
    chunks = clips.caption_chunks("In 1980, a mountain in Washington lost its entire north face in seconds.")
    assert " ".join(chunks) == "In 1980, a mountain in Washington lost its entire north face in seconds."
    assert all(1 < len(c.split()) <= 4 for c in chunks)
    times = clips.chunk_times(chunks, 4.0)
    assert times[0][0] == 0 and abs(times[-1][1] - 4.0) < 1e-9


def _fake_footage(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25:duration=2",
                    "-pix_fmt", "yuv420p", str(src)], check=True)
    seen = []

    def fake_find(query, cache_dir, portrait=False, avoid=()):
        seen.append((query, portrait, set(avoid)))
        return footage.Clip(src, query, "Tester", "CC0", f"https://example.org/{len(seen)}", "Test")

    monkeypatch.setattr(footage, "find", fake_find)
    monkeypatch.setattr(clips.music, "fetch", lambda *a, **k: None)
    return seen


def test_short_is_vertical_under_a_minute_and_records_its_footage(tmp_path, monkeypatch):
    seen = _fake_footage(tmp_path, monkeypatch)
    (tmp_path / "published").mkdir()
    (tmp_path / "published" / "old.json").write_text(json.dumps({"_published": {"clips": ["https://example.org/old"]}}))
    item = _item(tmp_path, scenes=[{"narration": "Lightning is hot.", "video": ["lightning"]},
                                   {"narration": "Very hot indeed.", "video": ["storm"]}])
    result = clips.render_clip_short(item, CFG, Narrator(SilentVoice()), tmp_path / "out", tmp_path / "cache")
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                       "stream=width,height:format=duration", "-of", "json", str(result.video)],
                                      capture_output=True, text=True, check=True).stdout)
    assert (probe["streams"][0]["width"], probe["streams"][0]["height"]) == clips.SHORT
    assert 3 < float(probe["format"]["duration"]) < clips.MAX_SHORT_SECONDS
    assert all(portrait for _, portrait, _ in seen)
    assert "https://example.org/old" in seen[0][2]  # footage already on the channel is skipped
    assert result.record["clips"] == ["https://example.org/1", "https://example.org/2"]
    assert "Subscribe" in result.captions.read_text() and "Tester" in result.photo_credits[0]


def test_footage_skips_clips_already_used(tmp_path, monkeypatch):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")

    def two_hits(query):
        return [{"url": f"https://v/{n}.mp4", "title": query, "author": "A", "licence": "CC0", "page": f"p{n}",
                 "source": "Test"} for n in (1, 2)]

    class FakeResponse:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, n): yield b"video"

    monkeypatch.setattr(footage, "SOURCES", (two_hits,))
    monkeypatch.setattr(footage.requests, "get", FakeResponse)
    assert footage.find("waves", tmp_path).page == "p1"
    assert footage.find("waves", tmp_path, avoid={"p1"}).page == "p2"


def _published(channel_dir, n, seconds=45.0):
    (channel_dir / "published").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (channel_dir / "published" / f"2026-10-{i + 10:02d}-s{i}.json").write_text(
            json.dumps({"_published": {"date": f"2026-10-{i + 10:02d}", "seconds": seconds}}))


def test_compilation_waits_for_enough_shorts_and_uses_each_once(tmp_path):
    cfg = {"compilation": {"min_minutes": 6, "max_minutes": 10, "min_days_between": 6}}
    _published(tmp_path, 7)
    picked, why = compilation_pick(tmp_path, cfg, dt.date(2026, 11, 1))
    assert not picked and "only" in why
    _published(tmp_path, 12)
    picked, _ = compilation_pick(tmp_path, cfg, dt.date(2026, 11, 1))
    assert 8 <= len(picked) <= 12 and picked[0].stem.endswith("s0")
    (tmp_path / "compilations").mkdir()
    (tmp_path / "compilations" / "2026-10-30.json").write_text(json.dumps(
        {"shorts": [p.stem for p in picked], "_published": {"date": "2026-10-30"}}))
    assert compilation_pick(tmp_path, cfg, dt.date(2026, 11, 1))[0] == []  # too soon after the last one
    assert all(p.stem not in {q.stem for q in picked} for p in compilation_pick(tmp_path, cfg, dt.date(2026, 11, 8))[0])


def test_long_footage_credits_are_shortened_but_keep_creative_commons_lines():
    from yta.cli import footage_credits

    lines = [f"Waves (video): Author {i}, Pexels License, https://www.pexels.com/video/{i}" for i in range(60)]
    lines.append("Rockfall (video): USGS, Public domain, https://commons.wikimedia.org/wiki/File:Rockfall.webm")
    out = footage_credits(lines)
    assert out[0].startswith("Rockfall") and out[1].startswith("Pexels: Author 0, Author 1")
    assert len("\n".join(out)) < 2400
