import json
import shutil
import subprocess

import pytest
import yaml

from yta import connect
from yta.cli import ROOT


class Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def replies(*items):
    calls, queue = [], list(items)

    def post(url, data=None, timeout=None):
        calls.append((url, data))
        return Reply(*queue.pop(0))
    return post, calls


def test_start_asks_for_the_youtube_scope():
    post, calls = replies((200, {"device_code": "dc", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device",
                                 "expires_in": 1800, "interval": 5}))
    code = connect.start("cid", post=post)
    assert code["user_code"] == "ABCD-EFGH"
    assert calls == [(connect.DEVICE_CODE_URL, {"client_id": "cid", "scope": "https://www.googleapis.com/auth/youtube"})]


def test_start_explains_a_wrong_app_type():
    post, _ = replies((401, {"error": "invalid_client", "error_description": "Invalid client type."}))
    with pytest.raises(connect.ConnectError, match="TVs and Limited Input"):
        connect.start("cid", post=post)


def test_wait_polls_until_signed_in_and_slows_down_when_asked():
    post, calls = replies((428, {"error": "authorization_pending"}), (403, {"error": "slow_down"}),
                          (200, {"access_token": "at", "refresh_token": "rt"}))
    waits = []
    assert connect.wait_for_login("cid", "cs", "dc", interval=5, post=post, sleep=waits.append) == "rt"
    assert waits == [5, 5, 10]
    assert calls[0][1]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"


@pytest.mark.parametrize("error,message", [("access_denied", "declined"), ("expired_token", "ran out")])
def test_wait_stops_on_a_refusal_or_an_old_code(error, message):
    post, _ = replies((400, {"error": error}))
    with pytest.raises(connect.ConnectError, match=message):
        connect.wait_for_login("cid", "cs", "dc", post=post, sleep=lambda s: None)


def test_same_name_ignores_case_and_punctuation():
    assert connect.same_name("Nature Unleashed", "nature-unleashed!")
    assert not connect.same_name("Economics in Charts", "Slow English Stories")


def test_device_app_is_named_in_channel_yaml_once(tmp_path):
    cfg_path = tmp_path / "channel.yaml"
    shutil.copy(ROOT / "channels" / "nature-unleashed" / "channel.yaml", cfg_path)
    assert connect.use_device_app(cfg_path)
    assert not connect.use_device_app(cfg_path)
    yt = yaml.safe_load(cfg_path.read_text())["youtube"]
    assert (yt["client_id_secret"], yt["client_secret_secret"]) == ("YT_DEVICE_CLIENT_ID", "YT_DEVICE_CLIENT_SECRET")
    assert yt["refresh_token_secret"] == "YT_REFRESH_TOKEN_NATURE_UNLEASHED"
    assert cfg_path.read_text().count("client_id_secret") == 1


def test_device_app_replaces_another_app(tmp_path):
    cfg_path = tmp_path / "channel.yaml"
    cfg_path.write_text("youtube:\n  refresh_token_secret: YT_REFRESH_TOKEN_X\n  client_id_secret: YT_CLIENT_ID_2\n"
                        "  client_secret_secret: YT_CLIENT_SECRET_2\n  privacy: public\n")
    connect.use_device_app(cfg_path)
    yt = yaml.safe_load(cfg_path.read_text())["youtube"]
    assert yt["client_id_secret"] == "YT_DEVICE_CLIENT_ID" and yt["privacy"] == "public"


def test_with_channel_adds_and_removes_in_order():
    assert connect.with_channel("", "a") == '["a"]'
    assert connect.with_channel('["a","b"]', "a") == '["a", "b"]'
    assert connect.with_channel('["a","b"]', "c") == '["a", "b", "c"]'
    assert connect.with_channel('["a","b"]', "a", on=False) == '["b"]'


def test_missing_setup_names_pixabay_only_for_footage_channels(monkeypatch):
    monkeypatch.setenv("YT_SECRETS", json.dumps({"YT_DEVICE_CLIENT_ID": "x", "YT_DEVICE_CLIENT_SECRET": "y"}))
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert [m.split(":")[0] for m in connect.missing_setup({"format": "clips"})] == ["ADMIN_TOKEN", "PIXABAY_API_KEY"]
    assert [m.split(":")[0] for m in connect.missing_setup({"format": "episode"})] == ["ADMIN_TOKEN"]


def test_gh_passes_the_value_on_stdin_with_the_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "ghp_admin")
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    connect.gh(["secret", "set", "YT_REFRESH_TOKEN_X"], stdin="rt", run=run)
    assert seen["cmd"] == ["gh", "secret", "set", "YT_REFRESH_TOKEN_X"] and "rt" not in seen["cmd"]
    assert seen["input"] == "rt" and seen["env"]["GH_TOKEN"] == "ghp_admin"
