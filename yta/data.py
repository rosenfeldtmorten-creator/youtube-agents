"""Public economic data: fetch, cache and slice time series. No API keys needed."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
from dataclasses import dataclass
from pathlib import Path

import requests


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


def fetch(name: str, spec: dict, cache_dir: Path) -> Series:
    """spec: {"source": "fred", "id": "CPIAUCSL", "label": "...", "unit": "index"}
    or {"source": "worldbank", "country": "US", "indicator": "NY.GDP.PCAP.CD", ...}
    or {"source": "inline", "points": [["2000", 1.0], ...]} for small hand-checked tables."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    source = spec.get("source")
    key = f"{source}-{spec.get('id') or spec.get('country', '')}-{spec.get('indicator', '')}".replace("/", "_")
    path = cache_dir / f"{key}.json"
    if source == "inline":
        points = [(parse_date(d, end_of_period=True), float(v)) for d, v in spec["points"]]
    elif path.exists() and (dt.date.today() - dt.date.fromtimestamp(path.stat().st_mtime)).days < 1:
        points = [(dt.date.fromisoformat(d), v) for d, v in json.loads(path.read_text())]
    else:
        if source == "fred":
            points = _fred(spec["id"])
        elif source == "worldbank":
            points = _worldbank(spec["country"], spec["indicator"])
        else:
            raise ValueError(f"Unknown data source '{source}' for {name}")
        path.write_text(json.dumps([(d.isoformat(), v) for d, v in points]))
    if not points:
        raise ValueError(f"No data for {name}")
    return Series(name, spec.get("label", name), spec.get("unit", ""), sorted(points))


def fetch_all(specs: dict, cache_dir: Path) -> dict[str, Series]:
    return {name: fetch(name, spec, cache_dir) for name, spec in specs.items()}
