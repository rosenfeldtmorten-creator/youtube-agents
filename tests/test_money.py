import datetime as dt
import json
import math
import shutil

import pytest
import yaml

from yta import checks, metrics
from yta.cli import ROOT
from yta.data import Series
from yta.episode import check_script, load_episode

CFG = yaml.safe_load((ROOT / "channels" / "money-charts" / "channel.yaml").read_text())
SAMPLE = ROOT / "tests" / "data" / "sample-episode.json"  # fixed copy, so tests don't depend on what's queued


def fake_series(name, start, growth, step=1):
    pts, d, i = [], dt.date(1990, 1, 1), 0
    while d <= dt.date(2026, 8, 1):
        pts.append((d, start * (1 + growth) ** (i / 12) + math.sin(i / 9)))
        i += step
        m = d.month - 1 + step
        d = dt.date(d.year + m // 12, m % 12 + 1, 1)
    return Series(name, name, "", pts)


@pytest.fixture
def series():
    return {"a": Series("a", "A", "", [(dt.date(2000, 1, 1), 100.0), (dt.date(2010, 1, 1), 200.0)])}


def test_metrics(series):
    assert metrics.evaluate('pct_change(a, "2000", "2010")', series) == pytest.approx(1.0)
    assert metrics.evaluate('ratio(a, "2000-01", "latest")', series) == 2.0
    assert metrics.evaluate('latest(a) / 4 - 1', series) == 49.0
    assert metrics.evaluate('latest(a) > value(a, "2000")', series) == 1.0
    assert metrics.fill('up {{ pct_change(a, "2000", "2010") | pct }}', series) == "up 100 percent"
    assert metrics.fill("{{ 1250000 | usd }}", series) == "1.2 million dollars"


def test_compound_matches_month_by_month():
    balance = 0.0
    monthly_rate = 1.07 ** (1 / 12) - 1
    for _ in range(12 * 30):
        balance = balance * (1 + monthly_rate) + 200
    assert metrics.FUNCTIONS["compound"](200, 0.07, 30) == pytest.approx(balance, rel=1e-9)


@pytest.mark.parametrize("expr", ["__import__('os')", "a.points", "[1, 2]", "open('x')", "lambda: 1"])
def test_metrics_rejects_code(series, expr):
    with pytest.raises(metrics.MetricError):
        metrics.evaluate(expr, series)


def test_typed_numbers_are_caught():
    assert metrics.typed_numbers("In 2000 it was {{ latest(a) | usd }}") == []
    assert metrics.typed_numbers("It rose 45 percent since 2000") == ["45"]


def test_sample_episode_script_passes():
    check_script(load_episode(SAMPLE), CFG["script"])


def test_script_with_typed_number_fails(tmp_path):
    data = json.loads(SAMPLE.read_text())
    data["scenes"][1]["narration"] += " That is 45 percent more."
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    with pytest.raises(checks.CheckFailed, match="types numbers"):
        check_script(load_episode(path), CFG["script"])


def _fake_data():
    return {
        "cpi": fake_series("cpi", 130, 0.026), "wages": fake_series("wages", 11, 0.034),
        "homes": fake_series("homes", 75, 0.05), "median_home": fake_series("median_home", 120000, 0.045, 3),
    }


def _with_fake_data(ep, monkeypatch=None):
    import yta.episode

    if monkeypatch:
        monkeypatch.setattr(yta.episode, "fetch_all", lambda specs, cache: _fake_data())
        ep.load_data(None)
        return ep
    ep.series = _fake_data()
    for sc in ep.scenes:
        sc.filled = metrics.fill(sc.narration, ep.series)
        sc.chart["title_filled"] = sc.chart.get("title", "")
    return ep


def test_load_data_fills_placeholders(monkeypatch):
    ep = _with_fake_data(load_episode(SAMPLE), monkeypatch)
    assert all("{{" not in sc.filled for sc in ep.scenes)


def test_false_claim_is_rejected(monkeypatch):
    ep = load_episode(SAMPLE)
    ep.raw = {**ep.raw, "claims": [{"says": "pay fell", "check": 'latest(wages) < value(wages, "2000")'}]}
    with pytest.raises(metrics.MetricError, match="no longer supports"):
        _with_fake_data(ep, monkeypatch)


def test_chart_rows():
    from yta.money import chart_rows

    ep = _with_fake_data(load_episode(SAMPLE))
    for sc in ep.scenes:
        if sc.chart["type"] != "card":
            rows = chart_rows(ep, sc.chart)
            assert rows and all(math.isfinite(r["y"]) for r in rows)


@pytest.mark.skipif(not shutil.which("Rscript") or not shutil.which("ffmpeg"), reason="needs R and ffmpeg")
def test_episode_renders_with_r(tmp_path):
    from yta.money import render_episode
    from yta.tts import make_narrator

    ep = _with_fake_data(load_episode(SAMPLE))
    ep.scenes = [s for s in ep.scenes if s.chart["type"] != "card"][:3] + ep.scenes[:1]
    cfg = {**CFG, "render": {**CFG["render"], "chart_frames": 4}}
    result = render_episode(ep, cfg, make_narrator({"backend": "silent"}, ROOT), tmp_path / "out", tmp_path / "cache")
    assert result.video.stat().st_size > 10_000
    assert result.thumbnail.exists()


def _model_series():
    unemp = fake_series("unemp", 6, -0.01)
    infl = Series("infl", "Inflation", "", [(d, 0.08 - v / 100) for d, v in unemp.points])
    return {"unemp": unemp, "infl": infl}


def test_linear_fit_and_correlation():
    s = _model_series()
    a, slope, r2 = metrics.linear_fit(s["unemp"], s["infl"])
    assert slope == pytest.approx(-0.01, rel=1e-6) and r2 == pytest.approx(1.0)
    assert metrics.evaluate('correlation(unemp, infl, "2000", "2020") < 0', s) == 1.0
    assert metrics.evaluate('trend_per_year(unemp, "2000", "2020") < 0', s) == 1.0


def test_year_over_year():
    from yta.data import year_over_year

    pts = [(dt.date(2020, m, 1), 100.0) for m in range(1, 13)] + [(dt.date(2021, m, 1), 103.0) for m in range(1, 13)]
    yoy = year_over_year(pts)
    assert len(yoy) == 12 and all(v == pytest.approx(0.03) for _, v in yoy)


def test_snapshot_fallback(tmp_path, monkeypatch):
    import requests

    from yta import data

    def offline(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(data.requests, "get", offline)
    spec = {"source": "fred", "id": "TEST", "transform": "yoy"}
    with pytest.raises(ValueError, match="no snapshot"):
        data.fetch("t", spec, tmp_path / "cache", tmp_path / "snap")
    data._save_points(tmp_path / "snap" / "fred-TEST-.json", [(dt.date(2020, 1, 1), 100.0), (dt.date(2021, 1, 1), 110.0)])
    s = data.fetch("t", spec, tmp_path / "cache", tmp_path / "snap")
    assert s.points == [(dt.date(2021, 1, 1), pytest.approx(0.1))]


def _scatter_episode():
    ep = _with_fake_data(load_episode(SAMPLE))
    ep.series.update(_model_series())
    ep.data = {**ep.data, "unemp": {"source": "fred", "id": "UNRATE"}, "infl": {"source": "fred", "id": "CPIAUCSL"}}
    chart = {"type": "scatter", "x": "unemp", "y": "infl", "from": "2000", "x_format": "num", "y_format": "pct",
             "fit": "linear", "connect": True, "title_filled": "Model"}
    line = {"type": "line", "series": ["cpi"], "from": "2000", "trend": "linear", "y_format": "num", "title_filled": "Trend"}
    return ep, chart, line


def test_scatter_rows():
    from yta.money import chart_rows

    ep, chart, _ = _scatter_episode()
    rows = chart_rows(ep, chart)
    assert [r["label"] for r in rows][:2] == ["2000", "2001"] and all(math.isfinite(r["x"]) for r in rows)


@pytest.mark.skipif(not shutil.which("Rscript"), reason="needs R")
def test_model_charts_render_with_r(tmp_path):
    from yta.money import draw_chart

    ep, scatter, line = _scatter_episode()
    for i, chart in enumerate((scatter, line)):
        frames = draw_chart(ep, chart, tmp_path / f"c{i}", 4, (1280, 720))
        assert len(frames) == 4 and frames[-1].stat().st_size > 5_000


def test_payment_and_real_dollars():
    from yta.episode import in_todays_dollars

    assert metrics.evaluate("payment(200000, 6, 30)", {}) == pytest.approx(1199.10, abs=0.01)
    cpi = Series("cpi", "", "", [(dt.date(2000, 1, 1), 100.0), (dt.date(2020, 1, 1), 200.0)])
    wage = Series("w", "", "", [(dt.date(2000, 1, 1), 5.0), (dt.date(2020, 1, 1), 7.0)])
    assert [v for _, v in in_todays_dollars(wage, cpi).points] == [10.0, 7.0]


def test_description_has_hashtags_chapters_and_sources(tmp_path):
    from yta import upload
    from yta.formats import FORMATS
    from yta.render import RenderResult

    data = json.loads(SAMPLE.read_text())
    data["hashtags"] = ["Economics", "Wages", "Inflation"]
    data["method"] = "We restate every wage in today's dollars with the CPI."
    data["references"] = [{"source": "Reuters", "date": "2026-10-16", "says": "wage growth slowed"}]
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    ep = load_episode(path)
    fmt = FORMATS["episode"]
    result = RenderResult(tmp_path / "v.mp4", tmp_path / "t.jpg", tmp_path / "c.srt", 300, ["X.jpg: A, CC0, url"],
                          [(0, "Intro"), (60, "The chart"), (200, "My take")], ["Kevin MacLeod: Floating Cities"])
    text = upload.build_description(ep.description, result.chapters, fmt.extra_description(ep, result),
                                    CFG["description_footer"], fmt.hashtags(ep))
    assert text.startswith("#Economics #Wages #Inflation\n")
    assert text.rstrip().endswith("#Economics #Wages #Inflation")
    assert "CHAPTERS\n00:00 Intro\n01:00 The chart\n03:20 My take" in text
    assert "HOW WE DID THE MATHS" in text and "Reuters (16 Oct 2026): wage growth slowed" in text
    assert "PHOTOS" in text and "MUSIC\nKevin MacLeod" in text


def test_hashtags_default_from_tags():
    ep = load_episode(SAMPLE)
    assert ep.hashtags and all(t.isalnum() for t in ep.hashtags)


@pytest.mark.parametrize("bad", [{"hashtags": ["#money"]}, {"references": [{"source": "x", "date": "Oct 16", "says": "y"}]}])
def test_bad_description_fields_are_rejected(tmp_path, bad):
    from yta.story import StoryError

    data = {**json.loads(SAMPLE.read_text()), **bad}
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    with pytest.raises(StoryError):
        load_episode(path)


def test_photo_licences():
    from yta.photos import is_free

    assert is_free("Public domain") and is_free("CC0") and is_free("CC BY-SA 4.0") and is_free("CC BY 2.0")
    assert not is_free("CC BY-NC 2.0") and not is_free("CC BY-ND 4.0") and not is_free("Fair use")


def test_photo_frames_push_in(tmp_path):
    from PIL import Image

    from yta.photos import Photo, frames

    src = tmp_path / "p.jpg"
    Image.new("RGB", (2000, 1200), (90, 120, 160)).save(src)
    photo = Photo(src, "File:P.jpg", "Jane Doe", "CC BY 4.0", "https://commons.wikimedia.org/wiki/File:P.jpg")
    out = frames(photo, "Washington, 1968", (640, 360), 2.0, tmp_path / "f", fps=6)
    assert len(out) == 12 and abs(sum(d for _, d in out) - 2.0) < 1e-6
    assert Image.open(out[0][0]).size == (640, 360) and out[0][0].suffix == ".jpg"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_music_is_mixed_under_the_voice(tmp_path):
    import subprocess

    import numpy as np
    from PIL import Image

    from yta import audio
    from yta.render import mux

    song = tmp_path / "song.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=220:d=3", "-ac", "2", str(song)], check=True)
    img = tmp_path / "f.png"
    Image.new("RGB", (320, 180)).save(img)
    voice = np.concatenate([np.sin(np.arange(audio.SR * 2) * 0.05).astype(np.float32) * 0.3, audio.silence(5)])
    video, seconds = mux([(img, 7.0)], voice, tmp_path, 24, music=song)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True).stdout
    assert abs(float(probe) - 7.0) < 0.3  # looped music must not make the video longer than the voice


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_short_renders_vertical(tmp_path):
    import subprocess

    from yta.shorts import render_short
    from yta.tts import Narrator, SilentVoice

    ep = _with_fake_data(load_episode(SAMPLE))
    cards = [i for i, s in enumerate(ep.scenes, 1) if s.chart["type"] == "card"][:1]
    cfg = {**CFG, "render": {**CFG["render"], "music": False}}
    video, seconds = render_short(ep, {"title": "A test short", "scenes": cards}, cfg, Narrator(SilentVoice()),
                                  tmp_path / "short", tmp_path)
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.strip()
    assert size == "1080,1920" and seconds <= 58


def test_short_field_is_checked(tmp_path):
    from yta.story import StoryError

    data = json.loads(SAMPLE.read_text())
    data["short"] = {"title": "Too far", "scenes": [99]}
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    with pytest.raises(StoryError, match="short"):
        load_episode(path)



def test_daily_short_candidates(tmp_path):
    from yta.shorts import candidates, tidy_opening

    data = json.loads(SAMPLE.read_text())
    charts = [i for i, sc in enumerate(data["scenes"], 1) if sc["chart"]["type"] in ("line", "bars", "growth")]
    data["short"] = {"title": "The launch Short", "scenes": [charts[0]]}
    data["shorts"] = [{"title": "Two charts together", "scenes": charts[:2]}]
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    ep = load_episode(path)
    picks = candidates(ep)
    assert picks[0]["scenes"] == charts[:2]                      # the script's own picks come first
    assert [charts[0]] not in [p["scenes"] for p in picks]      # the launch Short isn't repeated
    assert all(p["scenes"] == [i] for p, i in zip(picks[1:], charts[1:]))
    assert tidy_opening(["But look at this.", "Then that."]) == ["Look at this.", "Then that."]


def test_one_short_a_day(tmp_path):
    import datetime as dt

    from yta.cli import shorts_today

    (tmp_path / "published").mkdir()
    today = dt.date.today().isoformat()
    item = tmp_path / "published" / "a.json"
    item.write_text(json.dumps({"_published": {"date": "2026-01-01", "short_url": "x"}}))
    assert not shorts_today(tmp_path)
    item.write_text(json.dumps({"_published": {"date": "2026-01-01", "shorts": [{"date": today, "scenes": [2]}]}}))
    assert shorts_today(tmp_path)

def test_headlines_montage(tmp_path):
    from PIL import Image

    from yta.headlines import frames

    items = [{"source": "Example News", "date": "2026-10-14", "text": "Prices rose in September"},
             {"source": "Example Wire", "date": "2026-10-02", "text": "Unemployment rises"}]
    out = frames(items, (640, 360), 2.0, tmp_path, (242, 179, 61), fps=12)
    assert len(out) == 24 and Image.open(out[-1][0]).size == (640, 360)


def test_long_text_card_needs_a_photo(tmp_path):
    data = json.loads(SAMPLE.read_text())
    card = next(s for s in data["scenes"] if s["chart"].get("photo"))
    del card["chart"]["photo"]
    path = tmp_path / "ep.json"
    path.write_text(json.dumps(data))
    with pytest.raises(checks.CheckFailed, match="photo"):
        check_script(load_episode(path), CFG["script"])


def test_narrator_prefers_restored_copy(tmp_path):
    import numpy as np

    from yta import audio
    from yta.tts import Narrator, SilentVoice

    n = Narrator(SilentVoice(), cache_dir=tmp_path, enhance="resemble")
    plain = n.say("one two three four")
    key = n._key("one two three four")
    old = tmp_path / f"{key}.wav"
    audio.write_wav(old, np.zeros(24000, dtype=np.float32), 24000)  # a cache file from the 24 kHz days
    assert len(n.say("one two three four")) == audio.SR
    restored = tmp_path / "resemble" / f"{key}.wav"
    restored.parent.mkdir()
    audio.write_wav(restored, np.full(44100, 0.1, dtype=np.float32), 44100)
    out = n.say("one two three four")
    assert len(out) == audio.SR and abs(float(out.mean()) - 0.1) < 1e-3
    assert len(plain) > 0


def test_engagement_after_upload():
    from yta import upload

    calls = []

    class Call:
        def __init__(self, name, kw):
            self.name, self.kw = name, kw

        def execute(self):
            calls.append((self.name, self.kw))
            if self.name == "playlists.list":
                return {"items": [{"id": "PL1", "snippet": {"title": "All episodes"}}]}
            return {"id": "new"}

    class Res:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, verb):
            return lambda **kw: Call(f"{self.name}.{verb}", kw)

    class Client:
        def __getattr__(self, name):
            return lambda: Res(name)

    cfg = {"engagement": {"playlist": "All episodes", "shorts_playlist": "Shorts", "default_comment": "Which chart surprised you?"}}
    upload.engage(Client(), "vid", cfg, "What year were you born?")
    names = [n for n, _ in calls]
    assert names == ["playlists.list", "playlistItems.insert", "commentThreads.insert"]  # existing playlist reused
    assert calls[1][1]["body"]["snippet"]["playlistId"] == "PL1"
    assert "born" in calls[2][1]["body"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
    calls.clear()
    upload.engage(Client(), "short", cfg, short=True)
    assert [n for n, _ in calls] == ["playlists.list", "playlists.insert", "playlistItems.insert"]  # no comment on Shorts


def test_voice_must_match_chart_labels(monkeypatch):
    from pathlib import Path

    from yta import metrics, money

    path = Path(__file__).resolve().parents[1] / "channels/money-charts/published/2026-10-18-did-your-paycheck-keep-up.json"
    ep = load_episode(path)
    ep.load_data(Path(__file__).resolve().parents[1] / ".cache" / "data")
    houses = next(s for s in ep.scenes if s.chart.get("index") and "homes" in s.chart.get("series", []))
    shown = money.shown_numbers(ep, houses.chart)
    assert all(pct for _, pct in shown)          # rebased lines are labelled with their rise, like the voice
    money.check_voice_matches_charts(ep)
    # The bug a viewer caught: the chart printed index levels, so "risen 237 percent" sat next to the pay line's 237.
    monkeypatch.setattr(money, "shown_numbers", lambda ep, chart: [(v + 100, False) for v, _ in shown]
                        if chart is houses.chart else [])
    with pytest.raises(metrics.MetricError, match="percent"):
        money.check_voice_matches_charts(ep)
