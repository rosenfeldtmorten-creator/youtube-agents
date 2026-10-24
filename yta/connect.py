"""Connect a channel's YouTube login without leaving GitHub: Google's sign-in for TVs and other devices.

The Connect channel workflow (.github/workflows/connect-channel.yml) runs it in two jobs:

  1. start   asks Google for a short code and shows it ("open google.com/device and type ABCD-EFGH").
  2. finish  waits while the owner signs in and picks the channel, checks the login belongs to the channel
             named in channel.yaml, then saves it as the channel's secret and points channel.yaml at the
             sign-in app it came from.

Google only hands out codes like this to apps of type "TVs and Limited Input devices", and only for the
`youtube` scope (which covers uploads, captions, thumbnails, playlists and comments). That app is made once in
the same Google Cloud project as the main one, so it shares the same upload quota (docs/SETUP.md).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import requests

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube"
CLIENT_ID = "YT_DEVICE_CLIENT_ID"
CLIENT_SECRET = "YT_DEVICE_CLIENT_SECRET"
ADMIN_TOKEN = "ADMIN_TOKEN"   # fine-grained GitHub token that may write this repository's secrets and variables


class ConnectError(RuntimeError):
    pass


def secret(name: str) -> str:
    return (os.environ.get(name, "").strip()
            or str(json.loads(os.environ.get("YT_SECRETS") or "{}").get(name, "")).strip())


def missing_setup(cfg: dict) -> list[str]:
    """The one-time secrets this channel still needs, each with where to get it."""
    need = {
        CLIENT_ID: "the Client ID of the 'TVs and Limited Input devices' app (docs/SETUP.md, 'Connect channels')",
        CLIENT_SECRET: "that app's Client secret",
        ADMIN_TOKEN: "a GitHub token that may write this repository's secrets and variables (docs/SETUP.md)",
    }
    if cfg.get("format") == "clips":
        need["PIXABAY_API_KEY"] = "a free key from https://pixabay.com/api/docs/ (one key serves every channel)"
    return [f"{name}: {why}" for name, why in need.items() if not secret(name)]


def start(client_id: str, post=requests.post) -> dict:
    """Ask Google for a sign-in code. Returns device_code, user_code, verification_url, expires_in, interval."""
    r = post(DEVICE_CODE_URL, data={"client_id": client_id, "scope": SCOPE}, timeout=30)
    body = r.json()
    if r.status_code != 200:
        raise ConnectError(f"Google refused the sign-in code: {body.get('error_description') or body.get('error')}. "
                           "Check that YT_DEVICE_CLIENT_ID is a 'TVs and Limited Input devices' app.")
    body.setdefault("verification_url", body.get("verification_uri", "https://www.google.com/device"))
    return body


def wait_for_login(client_id: str, client_secret: str, device_code: str, interval: int = 5,
                   timeout: float = 900, post=requests.post, sleep=time.sleep) -> str:
    """Poll until the owner has signed in; return the refresh token."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sleep(interval)
        r = post(TOKEN_URL, timeout=30, data={
            "client_id": client_id, "client_secret": client_secret, "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        body = r.json()
        if r.status_code == 200:
            if not body.get("refresh_token"):
                raise ConnectError("Google signed in but sent no refresh token. Run Connect channel again.")
            return body["refresh_token"]
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise ConnectError("The sign-in was declined on Google's page. Run Connect channel again and click Allow.")
        if error == "expired_token":
            break
        raise ConnectError(f"Google refused the sign-in: {body.get('error_description') or error}")
    raise ConnectError("Nobody signed in before the code ran out. Run Connect channel again for a new code.")


def same_name(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return norm(a) == norm(b)


def use_device_app(channel_yaml: Path) -> bool:
    """Point the channel's youtube settings at the device sign-in app, since a login only refreshes with the app
    that made it. Returns False when channel.yaml already does."""
    text = channel_yaml.read_text()
    if re.search(rf"(?m)^  client_id_secret: {CLIENT_ID}\b", text):
        return False
    text = re.sub(r"(?m)^  client_(id|secret)_secret: .*\n", "", text)
    lines = (f"  client_id_secret: {CLIENT_ID}         # logged in with Connect channel (yta/connect.py)\n"
             f"  client_secret_secret: {CLIENT_SECRET}\n")
    text, n = re.subn(r"(?m)^(  refresh_token_secret: .*\n)", lambda m: m[1] + lines, text, count=1)
    if not n:
        raise ConnectError(f"{channel_yaml} has no youtube.refresh_token_secret line")
    channel_yaml.write_text(text)
    return True


def with_channel(active: str, slug: str, on: bool = True) -> str:
    """ACTIVE_CHANNELS with this channel added (kept in order, no duplicates) or taken out."""
    current = json.loads(active) if active.strip() else []
    if isinstance(current, str):
        current = [current]
    if on:
        return json.dumps(current if slug in current else [*current, slug])
    return json.dumps([s for s in current if s != slug])


def gh(args: list[str], stdin: str = "", run=subprocess.run) -> str:
    """Run the GitHub CLI as ADMIN_TOKEN (the workflow token can't write secrets). Values go in on stdin, never
    on the command line."""
    env = {**os.environ, "GH_TOKEN": secret(ADMIN_TOKEN)}
    done = run(["gh", *args], input=stdin, env=env, capture_output=True, text=True)
    if done.returncode != 0:
        raise ConnectError(f"gh {args[0]} {args[1]} failed: {done.stderr.strip()[:400]}. "
                           "Check that ADMIN_TOKEN may write this repository's secrets and variables.")
    return done.stdout
