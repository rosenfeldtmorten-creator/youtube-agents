"""One adapter per kind of channel, so the command line can treat every channel the same way."""
from __future__ import annotations

from pathlib import Path

from . import checks
from .story import StoryError


def published_items(channel_dir: Path, loader) -> list:
    out = []
    for p in sorted((channel_dir / "published").glob("*.json")):
        try:
            out.append(loader(p))
        except Exception:  # an old file in a different shape should not block new uploads
            continue
    return out


class StoryFormat:
    """Slow English stories."""

    @staticmethod
    def load(path: Path):
        from .story import load_story

        return load_story(path)

    def check(self, item, channel_dir: Path, cfg: dict, earlier_in_queue: list, cache_dir: Path) -> str:
        checks.check_level(item, cfg["levels"])
        checks.check_duplicates(item, published_items(channel_dir, self.load) + earlier_in_queue)
        return f"{item.level}, {item.word_count} words, {item.avg_sentence_words:.1f} words/sentence"

    @staticmethod
    def render(item, cfg, narrator, out_dir, cache_dir):
        from .render import render_story

        return render_story(item, cfg, narrator, out_dir, cache_dir)

    @staticmethod
    def hashtags(item) -> list[str]:
        return []

    @staticmethod
    def extra_description(item, result) -> list[str]:
        vocab = "Key words:\n" + "\n".join(f"- {v['word']}: {v['meaning']}" for v in item.vocabulary)
        credits = "Photos: " + "; ".join(result.photo_credits) if result.photo_credits else ""
        return [vocab, credits]


class EpisodeFormat:
    """Economics in Charts."""

    @staticmethod
    def load(path: Path):
        from .episode import load_episode

        return load_episode(path)

    def check(self, item, channel_dir: Path, cfg: dict, earlier_in_queue: list, cache_dir: Path) -> str:
        from .episode import check_script
        from .metrics import MetricError

        check_script(item, cfg["script"])
        checks.check_duplicates(item, published_items(channel_dir, self.load) + earlier_in_queue)
        try:
            item.load_data(cache_dir / "data")
            from .money import check_voice_matches_charts

            check_voice_matches_charts(item)
        except (MetricError, ValueError) as exc:
            raise checks.CheckFailed(f"data problem: {exc}") from exc
        except Exception as exc:  # network trouble is not the script's fault; report it plainly
            raise checks.CheckFailed(f"could not download the data ({exc})") from exc
        charts = sum(1 for s in item.scenes if s.chart["type"] not in ("card", "photo", "headlines"))
        return f"{len(item.scenes)} scenes, {charts} charts"

    @staticmethod
    def render(item, cfg, narrator, out_dir, cache_dir):
        from .money import render_episode

        return render_episode(item, cfg, narrator, out_dir, cache_dir)

    @staticmethod
    def hashtags(item) -> list[str]:
        return item.hashtags

    @staticmethod
    def extra_description(item, result) -> list[str]:
        sections = []
        if item.raw.get("method"):
            sections.append("HOW WE DID THE MATHS\n" + item.raw["method"].strip())
        sections.append("SOURCES\n" + "\n".join([*item.references, *(f"{s}" for s in item.sources)]))
        if result.photo_credits:
            sections.append("PHOTOS (Wikimedia Commons)\n" + "\n".join(result.photo_credits))
        sections.append("All charts and models are our own, drawn in R from the data above.")
        if result.music_credits:
            sections.append("MUSIC\n" + "\n".join(result.music_credits))
        sections.append("This video is for education only and is not financial advice.")
        return sections


FORMATS = {"story": StoryFormat(), "episode": EpisodeFormat()}
LOAD_ERRORS = (StoryError, checks.CheckFailed)
