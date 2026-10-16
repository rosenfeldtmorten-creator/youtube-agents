import datetime as dt
import json
import shutil

import pytest
import yaml

from yta import checks
from yta.cli import ROOT
from yta.story import contains_phrase, load_story, split_sentences, word_matches
from yta.visuals import highlight_mask

CHANNEL = ROOT / "channels" / "english-stories"
CFG = yaml.safe_load((CHANNEL / "channel.yaml").read_text())
SAMPLE = ROOT / "tests" / "data" / "sample-story.json"


def test_split_sentences_keeps_closing_quotes():
    text = 'He smiled. "Catch the rope!" Thomas shouted. She caught it.'
    assert split_sentences(text) == ["He smiled.", '"Catch the rope!"', "Thomas shouted.", "She caught it."]


@pytest.mark.parametrize("token,base,ok", [
    ("rescuing", "rescue", True), ("walked", "walk", True), ("cities", "city", True),
    ("grandmother", "ran", False), ("shore", "shore", True),
])
def test_word_matches(token, base, ok):
    assert word_matches(token, base) is ok


def test_highlight_mask_marks_vocab_words():
    tokens = "Thank you for rescuing me, she said.".split()
    assert highlight_mask(tokens, ["rescue"]) == [False, False, False, True, False, False, False]
    assert contains_phrase("The supply boat came.", "supply boat")


def test_sample_story_passes_checks():
    story = load_story(SAMPLE)
    checks.check_level(story, CFG["levels"])
    checks.check_duplicates(story, [])


def test_duplicate_story_is_rejected():
    story = load_story(SAMPLE)
    with pytest.raises(checks.CheckFailed):
        checks.check_duplicates(story, [story])


def test_pacing(tmp_path):
    (tmp_path / "published").mkdir()
    today = dt.date(2026, 10, 20)
    cadence = {"per_week": 2, "min_days_between": 2}
    assert checks.upload_due(tmp_path, cadence, today)[0]

    def publish(day, name):
        (tmp_path / "published" / f"{name}.json").write_text(json.dumps({"_published": {"date": day}}))

    publish("2026-10-19", "a")
    assert not checks.upload_due(tmp_path, cadence, today)[0]       # too soon after the last one
    assert checks.upload_due(tmp_path, cadence, dt.date(2026, 10, 21))[0]
    publish("2026-10-21", "b")
    assert not checks.upload_due(tmp_path, cadence, dt.date(2026, 10, 24))[0]  # weekly limit reached


def test_silent_render_produces_video(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    from yta.render import render_story
    from yta.tts import make_narrator

    story = load_story(SAMPLE)
    story.paragraphs = story.paragraphs[:1]
    story.quiz = story.quiz[:1]
    story.vocabulary = story.vocabulary[:1]
    cfg = {**CFG, "render": {**CFG["render"], "background_source": "generated"}}
    result = render_story(story, cfg, make_narrator({"backend": "silent"}, ROOT), tmp_path / "out", tmp_path / "cache")
    assert result.video.stat().st_size > 10_000
    assert result.seconds > 10
    assert [name for _, name in result.chapters] == ["Introduction", "Key words", "The story", "Quiz"]
