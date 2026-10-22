import json
import shutil

import pytest
import yaml

from yta import channels, upload
from yta.cli import ROOT


@pytest.fixture
def repo(tmp_path):
    for slug in ("money-charts", "english-stories"):
        dest = tmp_path / "channels" / slug
        dest.mkdir(parents=True)
        for name in ("channel.yaml", "WRITING_GUIDE.md"):
            shutil.copy(ROOT / "channels" / slug / name, dest / name)
    return tmp_path


def test_new_channel_copies_settings_with_its_own_login(repo):
    channels.new_channel(repo, "space-facts", "Space Facts", "Space questions answered with data.")
    dest = repo / "channels" / "space-facts"
    cfg = yaml.safe_load((dest / "channel.yaml").read_text())
    template = yaml.safe_load((repo / "channels" / "money-charts" / "channel.yaml").read_text())
    assert (cfg["name"], cfg["slug"], cfg["format"]) == ("Space Facts", "space-facts", "episode")
    assert cfg["youtube"]["refresh_token_secret"] == "YT_REFRESH_TOKEN_SPACE_FACTS"
    assert cfg["youtube"]["contains_synthetic_media"] is True
    assert cfg["engagement"]["playlist"] == "Space Facts: every video"
    assert cfg["description_footer"].startswith("Space Facts: Space questions answered with data.")
    assert cfg["render"] == template["render"] and cfg["script"] == template["script"]
    assert all((dest / sub / ".gitkeep").exists() for sub in ("queue", "published", "rejected"))
    guide = (dest / "WRITING_GUIDE.md").read_text()
    assert "--channel space-facts" in guide and "money-charts" not in guide.split("\n\n", 2)[2]


def test_new_story_channel(repo):
    channels.new_channel(repo, "kids-tales", "Kids Tales", "Calm stories.", fmt="story")
    cfg = yaml.safe_load((repo / "channels" / "kids-tales" / "channel.yaml").read_text())
    assert cfg["format"] == "story" and cfg["levels"]
    assert cfg["youtube"]["refresh_token_secret"] == "YT_REFRESH_TOKEN_KIDS_TALES"


@pytest.mark.parametrize("slug", ["Space Facts", "space_facts", "-space", "money-charts"])
def test_new_channel_refuses_bad_or_taken_slugs(repo, slug):
    with pytest.raises(channels.ChannelError):
        channels.new_channel(repo, slug, "X", "Y")


def test_pick_filters_active_channels_by_format(repo):
    assert channels.pick(repo, '["money-charts", "english-stories"]', "episode") == ["money-charts"]
    assert channels.pick(repo, "", "") == ["english-stories", "money-charts"]
    with pytest.raises(channels.ChannelError):
        channels.pick(repo, '["nope"]')


def test_secrets_come_from_the_workflow_bundle(monkeypatch):
    monkeypatch.delenv("YT_REFRESH_TOKEN_SPACE_FACTS", raising=False)
    monkeypatch.setenv("YT_SECRETS", json.dumps({"YT_REFRESH_TOKEN_SPACE_FACTS": "abc"}))
    assert upload._env("YT_REFRESH_TOKEN_SPACE_FACTS") == "abc"
    with pytest.raises(upload.UploadError):
        upload._env("YT_REFRESH_TOKEN_MISSING")
