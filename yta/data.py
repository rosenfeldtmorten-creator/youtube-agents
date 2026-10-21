"""Public economic data: fetch, cache and slice time series. No API keys needed."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass
from pathlib import Path

import requests

# Last downloaded copy of each series, kept in the repo (refreshed daily by .github/workflows/snapshot.yml).
# Used when a source can't be reached, so episodes can still be checked offline.
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshot"
TRANSFORMS = ("yoy",)


@dataclass
class Series:
    name: str
    label: str
    unit: str
    points: list[tuple[dt.date, float]]

    def between(self, start: str | None = None, end: str | None = None) -> "Series":
        lo = parse_date(start) if start and start != "latest" else dt.date.min
        hi = parse_date(end, end_of_period=True) if end and end != "latest" else dt.date.max
        return Series(self.name, self.label, self.unit, [(d, v) for d, v in self.points if lo <= d <= hi])

    def at(self, when: str) -> tuple[dt.date, float]:
        """The last observation on or before the date (or the first one, if the date is earlier)."""
        if str(when) == "latest":
            return self.points[-1]
        target = parse_date(when, end_of_period=True)
        before = [(d, v) for d, v in self.points if d <= target]
        if not before:
            raise ValueError(f"{self.name} has no data on or before {when}")
        return before[-1]

    def yearly(self) -> "Series":
        """One point per year: the last observation of each year."""
        last: dict[int, tuple[dt.date, float]] = {}
        for d, v in self.points:
            last[d.year] = (d, v)
        return Series(self.name, self.label, self.unit, [last[y] for y in sorted(last)])

    def yearly_mean(self) -> "Series":
        """One point per year: the average of that year's observations (dated 31 December)."""
        by_year: dict[int, list[float]] = {}
        for d, v in self.points:
            by_year.setdefault(d.year, []).append(v)
        pts = [(dt.date(y, 12, 31), sum(vs) / len(vs)) for y, vs in sorted(by_year.items())]
        return Series(self.name, self.label, self.unit, pts)

    @property
    def first(self) -> tuple[dt.date, float]:
        return self.points[0]

    @property
    def last(self) -> tuple[dt.date, float]:
        return self.points[-1]


def parse_date(text: str, end_of_period: bool = False) -> dt.date:
    """Accepts 2024, 2024-06 or 2024-06-30. With end_of_period, 2024 means 31 Dec 2024."""
    text = str(text).strip()
    parts = text.split("-")
    if len(parts) == 1:
        return dt.date(int(parts[0]), 12, 31) if end_of_period else dt.date(int(parts[0]), 1, 1)
    if len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        if not end_of_period:
            return dt.date(y, m, 1)
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    return dt.date.fromisoformat(text)


# ---------- sources ----------

def _fred(series_id: str) -> list[tuple[dt.date, float]]:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    r = requests.get(url, params={"id": series_id}, timeout=60)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    if not rows or len(rows[0]) < 2 or rows[0][0].strip().lower() not in ("date", "observation_date"):
        raise ValueError(f"FRED sent something other than a CSV for {series_id} (an error or maintenance page?)")
    out = []
    for row in rows[1:]:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        out.append((dt.date.fromisoformat(row[0]), float(row[1])))
    return out


def _worldbank(country: str, indicator: str) -> list[tuple[dt.date, float]]:
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
    r = requests.get(url, params={"format": "json", "per_page": 20000}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if len(payload) < 2 or not payload[1]:
        raise ValueError(f"World Bank returned no data for {country}/{indicator}")
    out = [(dt.date(int(p["date"]), 12, 31), float(p["value"])) for p in payload[1] if p["value"] is not None]
    return sorted(out)


def _key(spec: dict) -> str:
    return f"{spec.get('source')}-{spec.get('id') or spec.get('country', '')}-{spec.get('indicator', '')}".replace("/", "_")


def _download(spec: dict) -> list[tuple[dt.date, float]]:
    source = spec.get("source")
    if source == "fred":
        return _fred(spec["id"])
    if source == "worldbank":
        return _worldbank(spec["country"], spec["indicator"])
    raise ValueError(f"Unknown data source '{source}'")


def _load_points(path: Path) -> list[tuple[dt.date, float]]:
    return [(dt.date.fromisoformat(d), v) for d, v in json.loads(path.read_text())]


def _save_points(path: Path, points: list[tuple[dt.date, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([(d.isoformat(), v) for d, v in points]))


def year_over_year(points: list[tuple[dt.date, float]]) -> list[tuple[dt.date, float]]:
    """Change against the same period a year earlier, as a fraction (0.03 = 3%)."""
    by_date = {d: v for d, v in points}
    out = []
    for d, v in points:
        try:
            prev = by_date.get(d.replace(year=d.year - 1))
        except ValueError:  # 29 February
            prev = None
        if prev:
            out.append((d, v / prev - 1))
    return out


def fetch(name: str, spec: dict, cache_dir: Path, snapshot_dir: Path | None = None) -> Series:
    """spec: {"source": "fred", "id": "CPIAUCSL", "label": "...", "unit": "index"}
    or {"source": "worldbank", "country": "US", "indicator": "NY.GDP.PCAP.CD", ...}
    or {"source": "inline", "points": [["2000", 1.0], ...]} for small hand-checked tables.
    Optional "transform": "yoy" turns levels into the change on a year earlier (inflation from prices, say)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = snapshot_dir or SNAPSHOT_DIR
    source = spec.get("source")
    path = cache_dir / f"{_key(spec)}.json"
    if source == "inline":
        points = [(parse_date(d, end_of_period=True), float(v)) for d, v in spec["points"]]
    elif path.exists() and (dt.date.today() - dt.date.fromtimestamp(path.stat().st_mtime)).days < 1:
        points = _load_points(path)
    else:
        try:
            points = _download(spec)
            _save_points(path, points)
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:  # down, or sent a broken page
            snap = snapshot_dir / f"{_key(spec)}.json"
            if not snap.exists():
                raise ValueError(f"can't download {name} ({exc}) and there is no snapshot of it in data/snapshot") from exc
            print(f"  {name}: download failed, using the saved snapshot")
            points = _load_points(snap)
    transform = spec.get("transform")
    if transform == "yoy":
        points = year_over_year(sorted(points))
    elif transform:
        raise ValueError(f"{name}: unknown transform '{transform}' (allowed: {', '.join(TRANSFORMS)})")
    if not points:
        raise ValueError(f"No data for {name}")
    return Series(name, spec.get("label", name), spec.get("unit", ""), sorted(points))


def fetch_all(specs: dict, cache_dir: Path) -> dict[str, Series]:
    return {name: fetch(name, spec, cache_dir) for name, spec in specs.items()}


def refresh_snapshot(specs: list[dict], snapshot_dir: Path | None = None) -> tuple[int, list[str]]:
    """Download every distinct series in specs into the snapshot folder. Returns (saved, failures)."""
    snapshot_dir = snapshot_dir or SNAPSHOT_DIR
    seen, saved, failed = set(), 0, []
    for spec in specs:
        if spec.get("source") not in ("fred", "worldbank") or _key(spec) in seen:
            continue
        seen.add(_key(spec))
        try:
            _save_points(snapshot_dir / f"{_key(spec)}.json", _download(spec))
            saved += 1
        except (requests.RequestException, ValueError) as exc:
            failed.append(f"{_key(spec)}: {exc}")
    return saved, failed
