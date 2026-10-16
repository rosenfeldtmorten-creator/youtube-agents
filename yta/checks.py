"""Automatic quality and policy checks. These replace a human review before upload."""
from __future__ import annotations

import datetime as dt
import difflib
import json
from pathlib import Path

from .story import Story, contains_phrase, load_story, words

# Share of 5-word phrases two stories may have in common before they count as duplicates.
MAX_SHINGLE_OVERLAP = 0.15
MAX_TITLE_SIMILARITY = 0.85


class CheckFailed(Exception):
    """The item must not be published. The message says why."""


def check_level(story: Story, levels: dict) -> None:
    rules = levels[story.level]
    n = story.word_count
    if not rules["min_words"] <= n <= rules["max_words"]:
        raise CheckFailed(
            f"{story.level} stories need {rules['min_words']}-{rules['max_words']} words; this one has {n}"
        )
    avg = story.avg_sentence_words
    if avg > rules["max_avg_sentence_words"]:
        raise CheckFailed(
            f"sentences average {avg:.1f} words; {story.level} allows at most {rules['max_avg_sentence_words']}"
        )
    for v in story.vocabulary:
        if not contains_phrase(story.text, v["word"]):
            raise CheckFailed(f"vocabulary word '{v['word']}' does not appear in the story")
    if not 3 <= len(story.quiz) <= 6:
        raise CheckFailed("the quiz needs 3-6 questions")
    if not 5 <= len(story.vocabulary) <= 12:
        raise CheckFailed("the vocabulary list needs 5-12 words")


def _shingles(text: str, n: int = 5) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def published_stories(channel_dir: Path) -> list[Story]:
    out = []
    for p in sorted((channel_dir / "published").glob("*.json")):
        try:
            out.append(load_story(p))
        except Exception:  # an old file in a different shape should not block new uploads
            continue
    return out


def check_duplicates(story: Story, previous: list[Story]) -> None:
    mine = _shingles(story.text)
    for old in previous:
        if old.slug == story.slug:
            raise CheckFailed(f"slug '{story.slug}' was already published")
        ratio = difflib.SequenceMatcher(None, story.title.lower(), old.title.lower()).ratio()
        if ratio > MAX_TITLE_SIMILARITY:
            raise CheckFailed(f"title is too close to the published '{old.title}'")
        theirs = _shingles(old.text)
        if mine and theirs:
            overlap = len(mine & theirs) / min(len(mine), len(theirs))
            if overlap > MAX_SHINGLE_OVERLAP:
                raise CheckFailed(f"text overlaps {overlap:.0%} with the published '{old.title}'")


def publish_dates(channel_dir: Path) -> list[dt.date]:
    dates = []
    for p in (channel_dir / "published").glob("*.json"):
        meta = json.loads(p.read_text(encoding="utf-8")).get("_published", {})
        if meta.get("date"):
            dates.append(dt.date.fromisoformat(meta["date"]))
    return sorted(dates)


def upload_due(channel_dir: Path, cadence: dict, today: dt.date | None = None) -> tuple[bool, str]:
    """Whether the pacing rules allow an upload today."""
    today = today or dt.date.today()
    dates = publish_dates(channel_dir)
    last_week = [d for d in dates if (today - d).days < 7]
    if len(last_week) >= cadence["per_week"]:
        return False, f"already {len(last_week)} uploads in the last 7 days (limit {cadence['per_week']})"
    if dates and (today - dates[-1]).days < cadence["min_days_between"]:
        return False, f"last upload was {dates[-1]}; wait {cadence['min_days_between']} days between uploads"
    return True, "upload allowed"


def check_story(story: Story, channel_dir: Path, config: dict) -> None:
    check_level(story, config["levels"])
    check_duplicates(story, published_stories(channel_dir))


def check_duration(seconds: float, render_cfg: dict) -> None:
    minutes = seconds / 60
    if not render_cfg["min_minutes"] <= minutes <= render_cfg["max_minutes"]:
        raise CheckFailed(
            f"video is {minutes:.1f} min; allowed {render_cfg['min_minutes']}-{render_cfg['max_minutes']} min"
        )
