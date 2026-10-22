"""Many channels from one pipeline: list them, and make the folder and settings for a new one.

Every channel lives in channels/<slug>/ and shares the code, the workflows and the Google Cloud app.
The only thing a channel needs that can't be made here is its YouTube login (see docs/NEW_CHANNEL.md).
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import yaml

SLUG = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
TEMPLATES = {"episode": "money-charts", "story": "english-stories"}


class ChannelError(ValueError):
    pass


def token_secret(slug: str) -> str:
    return "YT_REFRESH_TOKEN_" + slug.upper().replace("-", "_")


def all_channels(root: Path) -> dict[str, dict]:
    out = {}
    for cfg_path in sorted((root / "channels").glob("*/channel.yaml")):
        out[cfg_path.parent.name] = yaml.safe_load(cfg_path.read_text())
    return out


def pick(root: Path, active: str = "", fmt: str = "") -> list[str]:
    """The channels a workflow should run: those named in `active` (a JSON list, like ACTIVE_CHANNELS), of format `fmt`."""
    channels = all_channels(root)
    wanted = json.loads(active) if active.strip() else list(channels)
    if isinstance(wanted, str):
        wanted = [wanted]
    unknown = [s for s in wanted if s not in channels]
    if unknown:
        raise ChannelError(f"no channel folder for {', '.join(unknown)} (channels/: {', '.join(channels)})")
    return [s for s in wanted if not fmt or channels[s].get("format") == fmt]


def _block(text: str, key: str, value: str) -> str:
    """Replace a top-level `key: |` block (the indented lines under it)."""
    body = "".join(f"  {line}\n" if line else "\n" for line in value.strip().splitlines())
    return re.sub(rf"(?m)^{key}: \|\n(?:(?:  .*)?\n)*", f"{key}: |\n{body}", text, count=1)


def _line(text: str, key: str, value: str, indent: str = "") -> str:
    """Replace the value of `key:` at this indent, keeping any comment after it."""
    return re.sub(rf"(?m)^({indent}{key}:) [^#\n]*?(\s*#.*)?$", lambda m: f"{m[1]} {value}{m[2] or ''}", text, count=1)


def channel_yaml(template: str, name: str, slug: str, about: str) -> str:
    text = re.sub(r"\A#.*\n", f"# {name}: {about}\n", template, count=1)
    text = _line(text, "name", name)
    text = _line(text, "slug", slug)
    text = _line(text, "thumbnail_label", name.upper())
    text = re.sub(r"(?m)^(  refresh_token_secret:) .*$", rf"\1 {token_secret(slug)}   # see docs/NEW_CHANNEL.md", text, count=1)
    # A new channel starts with the AI label on; turn it off only as a deliberate choice.
    text = re.sub(r"(?m)^(  contains_synthetic_media:) .*$", r"\1 true   # narration is a cloned voice", text, count=1)
    text = _line(text, "playlist", json.dumps(f"{name}: every video"), "  ")
    text = _line(text, "shorts_playlist", json.dumps(f"{name}: Shorts"), "  ")
    text = _line(text, "playlist_description", json.dumps(about), "  ")
    text = _line(text, "default_comment", json.dumps("What should we cover next? Tell us below."), "  ")
    text = _block(text, "description_footer", f"{name}: {about}\nNarration uses an AI clone of the creator's own voice.")
    return text


def writing_guide(template: str, old_name: str, old_slug: str, name: str, slug: str) -> str:
    text = template.replace(old_name, name).replace(old_slug, slug)
    note = ("> **New channel.** This guide was copied from `{}` and still describes that channel's subject.\n"
            "> Rewrite the sections about topics, tone and audience for this channel before the writing task runs.\n\n")
    head, _, rest = text.partition("\n\n")
    return f"{head}\n\n{note.format(old_slug)}{rest}"


def new_channel(root: Path, slug: str, name: str, about: str, like: str = "", fmt: str = "episode") -> list[Path]:
    """Make channels/<slug>/ from an existing channel. Returns the files written."""
    if not SLUG.match(slug):
        raise ChannelError(f"'{slug}' is not a usable slug: use lowercase letters, digits and single dashes, like 'space-facts'")
    dest = root / "channels" / slug
    if dest.exists():
        raise ChannelError(f"channels/{slug} already exists")
    like = like or TEMPLATES.get(fmt, "")
    src = root / "channels" / like
    if not (src / "channel.yaml").exists():
        raise ChannelError(f"no channel '{like}' to copy settings from")
    old = yaml.safe_load((src / "channel.yaml").read_text())

    written = []
    for sub in ("queue", "published", "rejected"):
        (dest / sub).mkdir(parents=True)
        (dest / sub / ".gitkeep").touch()
        written.append(dest / sub / ".gitkeep")
    (dest / "channel.yaml").write_text(channel_yaml((src / "channel.yaml").read_text(), name, slug, about))
    written.append(dest / "channel.yaml")
    if (src / "WRITING_GUIDE.md").exists():
        guide = writing_guide((src / "WRITING_GUIDE.md").read_text(), old["name"], like, name, slug)
        (dest / "WRITING_GUIDE.md").write_text(guide)
        written.append(dest / "WRITING_GUIDE.md")
    cfg = yaml.safe_load((dest / "channel.yaml").read_text())  # must still parse, and say what we meant
    if (cfg["slug"], cfg["name"], cfg["youtube"]["refresh_token_secret"]) != (slug, name, token_secret(slug)):
        shutil.rmtree(dest)
        raise ChannelError(f"could not adapt {like}/channel.yaml; copy it by hand")
    return written
