"""Finance episodes: scripted scenes over charts, with every number computed from public data."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import metrics
from .data import Series, fetch_all
from .story import StoryError, split_sentences

CHART_TYPES = ("line", "bars", "growth", "scatter", "card", "photo")
TRENDS = ("linear", "smooth")
BANNED_PHRASES = ("you should buy", "guaranteed", "can't lose", "cannot lose", "financial advice", "get rich quick")


def in_todays_dollars(s: Series, cpi: Series) -> Series:
    """Restate every value in the money of the latest price index reading."""
    latest = cpi.last[1]
    pts = []
    for d, v in s.points:
        try:
            pts.append((d, v * latest / cpi.at(d.isoformat())[1]))
        except ValueError:  # before the price index starts
            continue
    return Series(s.name, s.label, s.unit, pts)


@dataclass
class Scene:
    narration: str
    chart: dict
    filled: str = ""

    @property
    def sentences(self) -> list[str]:
        return split_sentences(self.filled or self.narration)


@dataclass
class Episode:
    path: Path
    slug: str
    title: str
    description: str
    tags: list[str]
    thumbnail_text: str
    data: dict
    scenes: list[Scene]
    raw: dict = field(repr=False, default_factory=dict)
    series: dict[str, Series] = field(default_factory=dict, repr=False)

    @property
    def text(self) -> str:
        return "\n\n".join(s.filled or s.narration for s in self.scenes)

    def load_data(self, cache_dir: Path) -> None:
        """Download the series, test every claim, and fill every placeholder. Raises MetricError on any problem."""
        self.series = fetch_all(self.data, cache_dir)
        for name, spec in self.data.items():
            if spec.get("in_todays_dollars"):
                self.series[name] = in_todays_dollars(self.series[name], self.series[spec["in_todays_dollars"]])
        for claim in self.raw.get("claims", []):
            if not metrics.evaluate(claim["check"], self.series):
                raise metrics.MetricError(f"the data no longer supports: \"{claim['says']}\" ({claim['check']} is false)")
        for scene in self.scenes:
            scene.filled = metrics.fill(scene.narration, self.series)
            if "title" in scene.chart:
                scene.chart["title_filled"] = metrics.fill(scene.chart["title"], self.series)

    @property
    def hashtags(self) -> list[str]:
        if self.raw.get("hashtags"):
            return [str(t) for t in self.raw["hashtags"]]
        return ["".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", t)) for t in self.tags[:3]]

    @property
    def references(self) -> list[str]:
        """News and reports the script cites, as 'Outlet (16 Oct 2026): what it says'."""
        import datetime as dt

        out = []
        for ref in self.raw.get("references", []):
            day = dt.date.fromisoformat(ref["date"])
            line = f"{ref['source']} ({day.day} {day:%b %Y}): {ref['says']}"
            out.append(f"{line} {ref['url']}" if ref.get("url") else line)
        return out

    @property
    def sources(self) -> list[str]:
        out = []
        for spec in self.data.values():
            if spec.get("source") == "fred":
                out.append(f"FRED, Federal Reserve Bank of St. Louis: {spec.get('label', spec['id'])} ({spec['id']})")
            elif spec.get("source") == "worldbank":
                out.append(f"World Bank: {spec.get('label', spec['indicator'])} ({spec['country']}, {spec['indicator']})")
            elif spec.get("source") == "inline" and spec.get("citation"):
                out.append(spec["citation"].split(": ")[0])  # one line per report, not one per figure from it
        return list(dict.fromkeys(out))


def load_episode(path: Path) -> Episode:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryError(f"{path.name}: invalid JSON ({exc})") from exc

    for key in ("slug", "title", "description", "data", "scenes"):
        if key not in data:
            raise StoryError(f"{path.name}: missing field '{key}'")
    title = data["title"].strip()
    if not 10 <= len(title) <= 100 or "<" in title or ">" in title:
        raise StoryError(f"{path.name}: title must be 10-100 characters without < or >")
    if metrics.PLACEHOLDER.search(title):
        raise StoryError(f"{path.name}: the title may not contain placeholders")

    for c in data.get("claims", []):
        if not isinstance(c, dict) or not c.get("says") or not c.get("check"):
            raise StoryError(f"{path.name}: each claim needs 'says' and 'check'")
    for name, spec in data["data"].items():
        if not name.isidentifier():
            raise StoryError(f"{path.name}: data name '{name}' must be a single word (letters, digits, _)")
        if spec.get("source") not in ("fred", "worldbank", "inline"):
            raise StoryError(f"{path.name}: data '{name}' needs source fred, worldbank or inline")
        if spec.get("transform") not in (None, "yoy"):
            raise StoryError(f"{path.name}: data '{name}' transform must be 'yoy' or left out")
        if spec.get("in_todays_dollars") and spec["in_todays_dollars"] not in data["data"]:
            raise StoryError(f"{path.name}: data '{name}' in_todays_dollars must name a price index in data")
        if spec.get("source") == "inline" and not spec.get("citation"):
            raise StoryError(f"{path.name}: inline data '{name}' needs a 'citation' naming where the numbers come from")

    for tag in data.get("hashtags", []):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,29}", str(tag)):
            raise StoryError(f"{path.name}: hashtag '{tag}' must be one word of letters and digits, without #")
    if len(data.get("hashtags", [])) > 5:
        raise StoryError(f"{path.name}: use at most 5 hashtags")
    for ref in data.get("references", []):
        if not (isinstance(ref, dict) and ref.get("source") and ref.get("date") and ref.get("says")):
            raise StoryError(f"{path.name}: each reference needs 'source', 'date' (YYYY-MM-DD) and 'says'")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(ref["date"])):
            raise StoryError(f"{path.name}: reference date '{ref['date']}' must look like 2026-10-16")

    short = data.get("short")
    if short is not None:
        picks = short.get("scenes") if isinstance(short, dict) else None
        if not (isinstance(short, dict) and 5 <= len(str(short.get("title", ""))) <= 90 and picks
                and all(isinstance(k, int) and 1 <= k <= len(data["scenes"]) for k in picks)):
            raise StoryError(f"{path.name}: 'short' needs a 'title' (5-90 characters) and 'scenes' (scene numbers from 1)")
        if any((data["scenes"][k - 1].get("chart") or {}).get("type") == "photo" for k in picks):
            raise StoryError(f"{path.name}: a Short can't use photo scenes")

    scenes = []
    for i, sc in enumerate(data["scenes"], 1):
        chart = dict(sc.get("chart") or {"type": "card"})
        if chart.get("type") not in CHART_TYPES:
            raise StoryError(f"{path.name}: scene {i} chart type must be one of {', '.join(CHART_TYPES)}")
        if chart["type"] == "scatter" and not (chart.get("x") and chart.get("y")):
            raise StoryError(f"{path.name}: scene {i} scatter chart needs 'x' and 'y' data names")
        for name in list(chart.get("series", [])) + [chart[k] for k in ("x", "y") if chart["type"] == "scatter"]:
            if name not in data["data"]:
                raise StoryError(f"{path.name}: scene {i} charts unknown data '{name}'")
        if chart["type"] == "photo" and not (chart.get("file") or chart.get("query")):
            raise StoryError(f"{path.name}: scene {i} photo needs a Wikimedia Commons 'file' or a search 'query'")
        if chart.get("trend") not in (None, *TRENDS):
            raise StoryError(f"{path.name}: scene {i} trend must be one of {', '.join(TRENDS)}")
        if not sc.get("narration", "").strip():
            raise StoryError(f"{path.name}: scene {i} has no narration")
        scenes.append(Scene(narration=sc["narration"].strip(), chart=chart))

    return Episode(
        path=path,
        slug=data["slug"],
        title=title,
        description=data["description"],
        tags=[str(t) for t in data.get("tags", [])],
        thumbnail_text=data.get("thumbnail_text") or title.split("|")[0].strip(),
        data=data["data"],
        scenes=scenes,
        raw=data,
    )


def check_script(ep: Episode, rules: dict) -> None:
    """Checks that need no downloads: typed numbers, length, banned phrases."""
    from .checks import CheckFailed
    from .story import words

    for i, sc in enumerate(ep.scenes, 1):
        typed = metrics.typed_numbers(sc.narration) + metrics.typed_numbers(sc.chart.get("title", ""))
        if typed:
            raise CheckFailed(f"scene {i} types numbers directly ({', '.join(typed[:3])}); put every number in a {{{{ }}}} placeholder")
    raw_text = " ".join(s.narration for s in ep.scenes).lower()
    for phrase in BANNED_PHRASES:
        if phrase in raw_text:
            raise CheckFailed(f"script contains '{phrase}'; this channel explains, it doesn't give advice")
    n = len(words(metrics.PLACEHOLDER.sub(" amount ", raw_text)))
    if not rules["min_words"] <= n <= rules["max_words"]:
        raise CheckFailed(f"script needs {rules['min_words']}-{rules['max_words']} words; this one has {n}")
    if not rules["min_scenes"] <= len(ep.scenes) <= rules["max_scenes"]:
        raise CheckFailed(f"episodes need {rules['min_scenes']}-{rules['max_scenes']} scenes")
    if not ep.raw.get("claims"):
        raise CheckFailed("add 'claims': every comparison the script makes in words needs a check against the data")
    if sum(1 for s in ep.scenes if s.chart["type"] != "card") < rules["min_charts"]:
        raise CheckFailed(f"episodes need at least {rules['min_charts']} charts")
