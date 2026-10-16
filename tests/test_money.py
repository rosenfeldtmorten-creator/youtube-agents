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
SAMPLE = next((ROOT / "channels" / "money-charts" / "queue").glob("*.json"), None) or next(
    (ROOT / "channels" / "money-charts" / "published").glob("*.json")
)


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
