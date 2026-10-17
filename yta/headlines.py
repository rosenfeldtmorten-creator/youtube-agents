"""Opening montage: news headlines that slide in one after another, each credited to its outlet and date."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .visuals import cover, font, generated_background

PAPER = (244, 241, 234)
INK = (24, 28, 36)
MUTED = (110, 116, 128)
SERIF = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSerif-Bold.ttf"]


def _serif(size: int) -> ImageFont.FreeTypeFont:
    for path in SERIF:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return font(size, "bold")


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt, width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=fnt) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return lines + [line] if line else lines


def clipping(item: dict, accent: tuple[int, int, int], width: int = 1400) -> Image.Image:
    """One headline on a paper card: outlet and date above, the headline in a bold serif."""
    day = dt.date.fromisoformat(item["date"])
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    head_font = _serif(70)
    lines = _wrap(probe, item["text"], head_font, width - 120)
    height = 150 + 88 * len(lines) + 40
    card = Image.new("RGBA", (width, height), PAPER + (255,))
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, 14, height), fill=accent + (255,))
    d.text((60, 52), item["source"].upper(), font=font(30, "bold"), fill=INK)
    d.text((width - 60, 52), f"{day.day} {day:%B %Y}", font=font(28), fill=MUTED, anchor="ra")
    d.line((60, 108, width - 60, 108), fill=(205, 200, 190), width=2)
    y = 136
    for line in lines:
        d.text((60, y), line, font=head_font, fill=INK)
        y += 88
    shadow = Image.new("RGBA", (width + 60, height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((30, 40, width + 30, height + 40), fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    shadow.alpha_composite(card, (30, 30))
    return shadow


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def frames(items: list[dict], size: tuple[int, int], seconds: float, out_dir: Path, accent: tuple[int, int, int],
           background: Image.Image | None = None, fps: int = 24) -> list[tuple[Path, float]]:
    """Each headline slides up into place in turn; earlier ones tilt back and fade a little behind it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = size
    bg = cover(background, size) if background is not None else generated_background("headlines", size)
    bg = Image.blend(bg.filter(ImageFilter.GaussianBlur(6)), Image.new("RGB", size, (14, 23, 38)), 0.55)
    cards = [clipping(it, accent) for it in items]
    angles = [-2.2, 1.6, -1.2, 2.0, -1.8]
    cards = [c.rotate(angles[k % len(angles)], resample=Image.BICUBIC, expand=True) for k, c in enumerate(cards)]
    offsets = [(-50, -40), (40, 30), (-30, 100), (40, -90), (-20, 20)]
    start = [k * seconds / len(items) for k in range(len(items))]

    n = max(2, int(seconds * fps))
    out = []
    for i in range(n):
        t = i / fps
        frame = bg.copy().convert("RGBA")
        for k, card in enumerate(cards):
            p = _ease((t - start[k]) / 0.45)
            if p <= 0:
                continue
            newest = k == max(j for j in range(len(cards)) if t >= start[j])
            if newest:
                c = card
            else:  # pushed back: smaller and darker, so only the newest headline is read
                c = card.resize((int(card.width * 0.9), int(card.height * 0.9)), Image.BILINEAR)
                c = Image.blend(Image.new("RGBA", c.size, (0, 0, 0, 0)), c, 0.45)
            if p < 1:
                c = c.copy()
                c.putalpha(c.getchannel("A").point(lambda a: int(a * p)))
            dx, dy = offsets[k % len(offsets)]
            x = (w - c.width) // 2 + dx
            y = (h - c.height) // 2 + dy + int(80 * (1 - p))
            frame.alpha_composite(c, (max(0, x), max(0, y)))
        path = out_dir / f"head_{i:04d}.png"
        frame.convert("RGB").save(path, compress_level=1)
        out.append((path, seconds / n))
    return out
